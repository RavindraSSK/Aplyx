"""Score all unscored (or all) jobs against the master resume."""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Application, ApplicationStatus, CandidateProfile, Job
from app.discovery.service import load_targets
from app.matching.scorer import score_job
from app.vertical.loader import load_vertical


def load_resume(path: str | None = None) -> str:
    return Path(path or get_settings().resume_path).read_text()


def profile_resume_text(db: Session, user_id: int) -> str | None:
    """Text of the user's latest uploaded profile (resume text + effective
    skills/targets), or None if they haven't uploaded a resume yet."""
    from app.profile.service import profile_embedding_text

    profile = db.scalar(
        select(CandidateProfile)
        .where(CandidateProfile.user_id == user_id)
        .order_by(CandidateProfile.version.desc())
        .limit(1)
    )
    if profile is None:
        return None
    resume_text = profile.resume_file.extracted_text if profile.resume_file else ""
    return profile_embedding_text(profile.effective, resume_text)


def effective_rules(rules: dict) -> dict:
    """targets.yaml rules with vertical-config defaults: an empty
    required_title_keywords means 'any title synonym of any role family'."""
    rules = dict(rules)
    if not rules.get("required_title_keywords"):
        vertical = load_vertical()
        rules["required_title_keywords"] = sorted(
            {syn for fam in vertical.families.values() for syn in fam.title_synonyms}
        )
    return rules


def run_matching(
    db: Session,
    resume_text: str | None = None,
    targets: dict | None = None,
    rescore_all: bool = False,
    user_id: int | None = None,
) -> dict:
    source = "explicit"
    if resume_text is None and user_id is not None:
        resume_text = profile_resume_text(db, user_id)
        source = "profile"
    if resume_text is None:
        resume_text = load_resume()
        source = "resume.md"
    targets = targets if targets is not None else load_targets()
    rules = effective_rules(targets.get("matching", {}))

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
    return {"scored": scored, "resume_source": source}
