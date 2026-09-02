"""Score all unscored (or all) jobs against the master resume."""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Application, ApplicationStatus, Job
from app.discovery.service import load_targets
from app.matching.scorer import score_job


def load_resume(path: str | None = None) -> str:
    return Path(path or get_settings().resume_path).read_text()


def run_matching(
    db: Session,
    resume_text: str | None = None,
    targets: dict | None = None,
    rescore_all: bool = False,
) -> dict:
    resume_text = resume_text if resume_text is not None else load_resume()
    targets = targets if targets is not None else load_targets()
    rules = targets.get("matching", {})

    query = select(Job)
    if not rescore_all:
        query = query.where(Job.score.is_(None))
    jobs = db.scalars(query).all()

    scored = 0
    for job in jobs:
        result = score_job(
            resume_text, job.title, job.description, job.location, job.remote, rules
        )
        job.score = result.score
        job.score_reasons = result.reasons
        if result.score > 0 and job.application is not None:
            if job.application.status == ApplicationStatus.discovered:
                job.application.status = ApplicationStatus.matched
        scored += 1
    db.commit()
    return {"scored": scored}
