"""API routers: discovery, jobs (match/tailor/diff), applications."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ApplicationOut,
    DiscoverSummary,
    JobOut,
    StatusUpdate,
    TailoredOut,
)
from app.auth import current_user
from app.db.models import Application, Job, TailoredResume, User
from app.db.session import get_db
from app.ingest.service import run_discovery, run_summary
from app.matching.service import run_matching
from app.tailoring.service import tailor_job
from app.tracker.service import InvalidTransition, update_status

router = APIRouter()


@router.post("/discover/run", response_model=DiscoverSummary)
def discover(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Legacy endpoint: advances the current ingestion run by one slice."""
    run = run_discovery(db, user_id=user.id)
    summary = run_summary(run)
    return {"created": summary["created"], "updated": summary["updated"], "errors": summary["errors"],
            "status": summary["status"], "run_id": summary["id"]}


@router.post("/match/run")
def match(rescore_all: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return run_matching(db, rescore_all=rescore_all, user_id=user.id)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(min_score: float | None = None, db: Session = Depends(get_db)):
    query = select(Job).order_by(Job.score.desc().nulls_last(), Job.id)
    if min_score is not None:
        query = query.where(Job.score >= min_score)
    return db.scalars(query).all()


def _get_job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/jobs/{job_id}/tailor", response_model=TailoredOut)
def tailor(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = _get_job_or_404(db, job_id)
    return tailor_job(db, job, user_id=user.id)


@router.get("/jobs/{job_id}/diff")
def get_diff(job_id: int, db: Session = Depends(get_db)):
    _get_job_or_404(db, job_id)
    latest = db.scalar(
        select(TailoredResume)
        .where(TailoredResume.job_id == job_id)
        .order_by(TailoredResume.created_at.desc(), TailoredResume.id.desc())
        .limit(1)
    )
    if latest is None:
        raise HTTPException(status_code=404, detail="no tailored resume for this job yet")
    return Response(content=latest.diff, media_type="text/x-diff")


@router.patch("/applications/{application_id}/status", response_model=ApplicationOut)
def patch_status(application_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="application not found")
    try:
        return update_status(db, application, body.status, notes=body.notes)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
