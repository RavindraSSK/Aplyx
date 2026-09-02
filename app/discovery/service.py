"""Run all fetchers over targets.yaml and upsert results (deduped by url)."""
import logging
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Application, ApplicationStatus, Job
from app.discovery.ashby import AshbyFetcher
from app.discovery.base import BaseFetcher, NormalizedJob
from app.discovery.greenhouse import GreenhouseFetcher
from app.discovery.lever import LeverFetcher

logger = logging.getLogger(__name__)

FETCHERS: dict[str, type[BaseFetcher]] = {
    "greenhouse": GreenhouseFetcher,
    "lever": LeverFetcher,
    "ashby": AshbyFetcher,
}


def load_targets(path: str | None = None) -> dict:
    target_path = Path(path or get_settings().targets_path)
    with target_path.open() as f:
        return yaml.safe_load(f) or {}


def upsert_job(db: Session, normalized: NormalizedJob) -> tuple[Job, bool]:
    """Insert or update a job keyed on url. Returns (job, created)."""
    existing = db.scalar(select(Job).where(Job.url == normalized.url))
    if existing is not None:
        existing.title = normalized.title
        existing.location = normalized.location
        existing.remote = normalized.remote
        existing.description = normalized.description
        existing.posted_at = normalized.posted_at
        return existing, False

    job = Job(**normalized.model_dump())
    db.add(job)
    db.flush()
    db.add(Application(job_id=job.id, status=ApplicationStatus.discovered))
    return job, True


def run_discovery(db: Session, targets: dict | None = None) -> dict:
    """Fetch every configured board and upsert. Returns per-company counts."""
    targets = targets if targets is not None else load_targets()
    summary = {"created": 0, "updated": 0, "errors": []}
    for company_cfg in targets.get("companies", []):
        name = company_cfg["name"]
        source = company_cfg["source"]
        slug = company_cfg["slug"]
        fetcher_cls = FETCHERS.get(source)
        if fetcher_cls is None:
            summary["errors"].append(f"{name}: unknown source '{source}'")
            continue
        try:
            normalized_jobs = fetcher_cls().fetch(slug, name)
        except Exception as exc:  # keep one bad board from killing the run
            logger.exception("discovery failed for %s (%s/%s)", name, source, slug)
            summary["errors"].append(f"{name}: {exc}")
            continue
        for normalized in normalized_jobs:
            if not normalized.url:
                continue
            _, created = upsert_job(db, normalized)
            summary["created" if created else "updated"] += 1
    db.commit()
    return summary
