"""Milestone 1.2 API: discovery runs and the company registry."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db.models import Company, IngestionRun, Job, User
from app.db.session import get_db
from app.ingest.seed import seed_companies, slugify
from app.ingest.service import run_discovery, run_summary
from app.sources.detect import detect

router = APIRouter(prefix="/api")

CRON_BUDGET_SECONDS = 45  # Vercel maxDuration is 60


@router.api_route("/discover", methods=["POST", "GET"])
def discover(all: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """POST from the dashboard: one slice (call again until status == done).
    GET from the Vercel cron (or ?all=1): loop slices within the time budget."""
    budget = CRON_BUDGET_SECONDS if all else None
    run = run_discovery(db, user_id=user.id, time_budget_seconds=budget)
    return run_summary(run)


@router.get("/runs")
def list_runs(limit: int = 10, db: Session = Depends(get_db), user: User = Depends(current_user)):
    runs = db.scalars(select(IngestionRun).order_by(IngestionRun.id.desc()).limit(limit)).all()
    return [run_summary(r) for r in runs]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    run = db.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run_summary(run)


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    ats_provider: str | None
    ats_slug: str | None
    careers_url: str
    domain: str
    category: str
    hq_location: str
    headcount_band: str
    is_public: bool
    tier_seed: int | None
    tier: int | None
    tier_reason: str
    tier_confidence: float | None
    tier_override: int | None
    active: bool
    verified: bool
    last_fetch_at: datetime | None
    last_fetch_status: str
    last_fetch_count: int
    last_fetch_error: str
    open_jobs: int = 0


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(status: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(Company).order_by(Company.tier_seed.asc().nulls_last(), Company.name)
    if status:
        q = q.where(Company.last_fetch_status == status)
    companies = db.scalars(q).all()
    counts = dict(db.execute(
        select(Job.company_id, func.count(Job.id)).where(Job.status == "open").group_by(Job.company_id)
    ).all())
    out = []
    for c in companies:
        o = CompanyOut.model_validate(c)
        o.open_jobs = counts.get(c.id, 0)
        out.append(o)
    return out


@router.post("/companies/seed")
def seed(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return seed_companies(db)


class CompanyIn(BaseModel):
    careers_url: str
    name: str | None = None
    tier_seed: int | None = None
    category: str = ""


@router.post("/companies", response_model=CompanyOut)
def add_company(body: CompanyIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    hit = detect(body.careers_url)
    if hit is None:
        raise HTTPException(status_code=422, detail="could not detect a supported ATS (Greenhouse/Lever/Ashby/"
                            "SmartRecruiters/Workday) from that URL")
    provider, ats_slug = hit
    name = body.name or ats_slug.split("/")[0].split(".")[0].replace("-", " ").title()
    slug = slugify(name)
    company = db.scalar(select(Company).where(Company.slug == slug))
    if company is None:
        company = Company(name=name, slug=slug)
        db.add(company)
    company.ats_provider, company.ats_slug, company.careers_url = provider, ats_slug, body.careers_url
    company.category = body.category or company.category
    company.tier_seed = body.tier_seed or company.tier_seed or 3
    company.headcount_band = company.headcount_band or "<500"
    db.commit()
    db.refresh(company)
    return CompanyOut.model_validate(company)


class CompanyPatch(BaseModel):
    active: bool | None = None
    tier_override: int | None = None
    ats_provider: str | None = None
    ats_slug: str | None = None


@router.patch("/companies/{company_id}", response_model=CompanyOut)
def patch_company(company_id: int, body: CompanyPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(company, k, v)
    db.commit()
    db.refresh(company)
    return CompanyOut.model_validate(company)
