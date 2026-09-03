"""Discovery/ingestion: pull every configured company board + enabled
aggregators, normalize, upsert, dedupe across sources, and close jobs that a
source stopped returning. Serverless-safe: work is done in slices, tracked on
an IngestionRun row, so a run can span many short invocations."""
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Application, ApplicationStatus, Company, IngestionRun, Job
from app.sources.base import RawJob, aggregator_adapters, get_adapter
from app.sources.normalize import normalize_company, to_job_columns
from app.vertical.loader import load_vertical

logger = logging.getLogger(__name__)
AGGREGATOR_STALE_DAYS = 45  # query-based sources can't signal "closed"; expire after this


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── upsert / dedupe / close ──────────────────────────────────────────────────

def upsert_raw_jobs(db: Session, raws: list[RawJob], *, user_id: int, company: Company | None = None,
                    source_kind: str = "ats") -> dict:
    """Insert or update jobs by url. Cross-source dedupe on (company, title,
    location): an ATS posting always wins over an aggregator copy."""
    now = utcnow()
    counts = {"created": 0, "updated": 0, "duplicates": 0, "seen_urls": []}
    for raw in raws:
        if not raw.url or not raw.title:
            continue
        cols = to_job_columns(raw)
        counts["seen_urls"].append(cols["url"])
        job = db.scalar(select(Job).where(Job.url == cols["url"]))
        if job is not None:
            for k, v in cols.items():
                if k in ("external_id", "source"):
                    continue
                if v is not None or k in ("description", "location", "title"):
                    setattr(job, k, v)
            job.last_seen_at = now
            if job.status == "closed":
                job.status, job.closed_at = "open", None
            if company is not None:
                job.company_id = company.id
            counts["updated"] += 1
            continue

        twin = db.scalar(select(Job).where(Job.dedupe_key == cols["dedupe_key"], Job.status == "open"))
        if twin is not None:
            if source_kind == "aggregator":
                counts["duplicates"] += 1
                twin.last_seen_at = now
                continue
            # ATS copy of an aggregator posting: the ATS row replaces it
            job = Job(**cols, first_seen_at=now, last_seen_at=now, status="open",
                      company_id=company.id if company else _company_id_for(db, raw.company))
            db.add(job)
            db.flush()
            twin.status, twin.duplicate_of, twin.closed_at = "duplicate", job.id, now
            _move_application(db, twin, job)
            counts["created"] += 1
            continue

        job = Job(**cols, first_seen_at=now, last_seen_at=now, status="open",
                  company_id=company.id if company else _company_id_for(db, raw.company))
        db.add(job)
        db.flush()
        db.add(Application(job_id=job.id, user_id=user_id, status=ApplicationStatus.discovered))
        counts["created"] += 1
    return counts


def _company_id_for(db: Session, name: str) -> int | None:
    """Link an aggregator posting to a seeded company when names match."""
    key = normalize_company(name)
    if not key:
        return None
    for c in db.scalars(select(Company)).all():
        if normalize_company(c.name) == key:
            return c.id
    return None


def _move_application(db: Session, old: Job, new: Job) -> None:
    if old.application is not None and new.application is None:
        old.application.job_id = new.id


def close_missing(db: Session, company: Company, seen_urls: list[str]) -> int:
    """Rule 5: jobs the board no longer returns are closed, never left stale."""
    now = utcnow()
    q = select(Job).where(Job.company_id == company.id, Job.status == "open")
    closed = 0
    for job in db.scalars(q).all():
        if job.url not in seen_urls:
            job.status, job.closed_at = "closed", now
            closed += 1
    return closed


def expire_stale_aggregator_jobs(db: Session, days: int = AGGREGATOR_STALE_DAYS) -> int:
    cutoff = utcnow() - timedelta(days=days)
    agg_sources = list(aggregator_adapters())
    q = select(Job).where(Job.status == "open", Job.source.in_(agg_sources), Job.last_seen_at < cutoff)
    n = 0
    for job in db.scalars(q).all():
        job.status, job.closed_at = "closed", utcnow()
        n += 1
    db.commit()
    return n


# ── per-company / per-aggregator ────────────────────────────────────────────

def ingest_company(db: Session, company: Company, *, user_id: int) -> dict:
    t0 = time.monotonic()
    entry = {"source": company.ats_provider, "target": company.slug, "status": "ok",
             "count": 0, "created": 0, "updated": 0, "closed": 0, "seconds": 0.0, "error": ""}
    try:
        raws = get_adapter(company.ats_provider).fetch(company.ats_slug, company.name)
        c = upsert_raw_jobs(db, raws, user_id=user_id, company=company, source_kind="ats")
        entry.update(count=len(raws), created=c["created"], updated=c["updated"],
                     closed=close_missing(db, company, c["seen_urls"]))
        company.verified = True
        company.last_fetch_status, company.last_fetch_count, company.last_fetch_error = "ok", len(raws), ""
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        entry.update(status="not_found" if code == 404 else "error", error=f"HTTP {code}")
        company.last_fetch_status, company.last_fetch_error = entry["status"], entry["error"]
    except Exception as exc:  # one bad board never kills a run
        logger.exception("ingest failed for %s", company.slug)
        entry.update(status="error", error=f"{type(exc).__name__}: {exc}"[:500])
        company.last_fetch_status, company.last_fetch_error = "error", entry["error"]
    company.last_fetch_at = utcnow()
    entry["seconds"] = round(time.monotonic() - t0, 2)
    db.commit()
    return entry


def aggregator_queries() -> list[str]:
    v = load_vertical()
    return list(getattr(v, "aggregator_queries", None) or _default_queries())


def _default_queries() -> list[str]:
    return ["machine learning engineer", "data scientist", "AI engineer", "applied scientist",
            "NLP engineer", "computer vision engineer", "MLOps engineer", "data engineer",
            "AI product manager", "research engineer"]


def ingest_aggregator(db: Session, name: str, *, user_id: int) -> dict:
    t0 = time.monotonic()
    entry = {"source": name, "target": "*", "status": "ok", "count": 0, "created": 0,
             "updated": 0, "duplicates": 0, "seconds": 0.0, "error": ""}
    cls = aggregator_adapters()[name]
    if not cls.available():
        entry.update(status="skipped", error="missing API key(s): " + ", ".join(cls.required_settings))
        return entry
    adapter = cls()
    try:
        for query in aggregator_queries():
            raws = adapter.fetch(query=query)
            c = upsert_raw_jobs(db, raws, user_id=user_id, source_kind="aggregator")
            entry["count"] += len(raws)
            for k in ("created", "updated", "duplicates"):
                entry[k] += c[k]
            db.commit()
            if adapter.rate_limit_seconds:
                time.sleep(adapter.rate_limit_seconds)
    except Exception as exc:
        logger.exception("aggregator %s failed", name)
        entry.update(status="error", error=f"{type(exc).__name__}: {exc}"[:500])
        db.rollback()
    entry["seconds"] = round(time.monotonic() - t0, 2)
    return entry


# ── runs (sliced) ───────────────────────────────────────────────────────────

def enabled_aggregators() -> list[str]:
    wanted = [s.strip() for s in get_settings().aggregators_enabled.split(",") if s.strip()]
    return [a for a in wanted if a in aggregator_adapters()]


def pending_companies(db: Session, run: IngestionRun, limit: int) -> list[Company]:
    q = (select(Company)
         .where(Company.active.is_(True), Company.ats_provider.isnot(None),
                or_(Company.last_fetch_at.is_(None), Company.last_fetch_at < run.started_at))
         .order_by(Company.last_fetch_at.asc().nulls_first(), Company.id)
         .limit(limit))
    return db.scalars(q).all()


def current_run(db: Session) -> IngestionRun | None:
    return db.scalar(select(IngestionRun).where(IngestionRun.status == "running")
                     .order_by(IngestionRun.id.desc()).limit(1))


def start_run(db: Session, *, user_id: int) -> IngestionRun:
    total = db.scalar(select(func.count(Company.id)).where(Company.active.is_(True), Company.ats_provider.isnot(None)))
    run = IngestionRun(user_id=user_id, total_companies=total or 0, sources=[])
    db.add(run)
    db.commit()
    return run


def process_slice(db: Session, run: IngestionRun, *, user_id: int, batch_size: int | None = None) -> IngestionRun:
    """Advance a run by one slice: up to `batch_size` companies, or one
    aggregator, or finalize. Safe to call repeatedly until status == done."""
    batch_size = batch_size or get_settings().ingest_batch_size
    sources = list(run.sources or [])
    companies = pending_companies(db, run, batch_size)
    if companies:
        for company in companies:
            entry = ingest_company(db, company, user_id=user_id)
            sources.append(entry)
            run.created += entry["created"]
            run.updated += entry["updated"]
            run.closed += entry["closed"]
            run.processed_companies += 1
        run.sources = sources
        db.commit()
        return run

    done_aggs = {e["source"] for e in sources if e.get("target") == "*"}
    remaining = [a for a in enabled_aggregators() if a not in done_aggs]
    if remaining:
        entry = ingest_aggregator(db, remaining[0], user_id=user_id)
        sources.append(entry)
        run.created += entry["created"]
        run.updated += entry["updated"]
        run.duplicates += entry.get("duplicates", 0)
        run.sources = sources
        run.aggregators_done = len(remaining) == 1
        db.commit()
        return run

    run.closed += expire_stale_aggregator_jobs(db)
    run.aggregators_done = True
    run.status = "done"
    run.finished_at = utcnow()
    db.commit()
    return run


def run_discovery(db: Session, *, user_id: int, time_budget_seconds: float | None = None,
                  batch_size: int | None = None) -> IngestionRun:
    """One step (dashboard) or many steps within a time budget (CLI / cron)."""
    run = current_run(db) or start_run(db, user_id=user_id)
    t0 = time.monotonic()
    while True:
        run = process_slice(db, run, user_id=user_id, batch_size=batch_size)
        if run.status != "running":
            break
        if time_budget_seconds is None or (time.monotonic() - t0) > time_budget_seconds:
            break
    return run


def run_summary(run: IngestionRun) -> dict:
    return {
        "id": run.id, "status": run.status, "started_at": run.started_at, "finished_at": run.finished_at,
        "total_companies": run.total_companies, "processed_companies": run.processed_companies,
        "aggregators_done": run.aggregators_done, "created": run.created, "updated": run.updated,
        "closed": run.closed, "duplicates": run.duplicates, "sources": run.sources or [],
        "errors": [f"{e['source']}:{e['target']} {e['error']}" for e in (run.sources or []) if e.get("error")],
    }
