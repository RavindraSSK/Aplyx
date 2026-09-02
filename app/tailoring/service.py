"""Persist tailoring results and advance application status."""
import anthropic
from sqlalchemy.orm import Session

from app.db.models import ApplicationStatus, Job, TailoredResume
from app.matching.service import load_resume
from app.tailoring.tailor import tailor_resume


def tailor_job(
    db: Session,
    job: Job,
    resume_text: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> TailoredResume:
    resume_text = resume_text if resume_text is not None else load_resume()
    result = tailor_resume(resume_text, job.title, job.description, client=client)

    record = TailoredResume(
        job_id=job.id,
        content_md=result.content_md,
        diff=result.diff,
        model=result.model,
    )
    db.add(record)
    db.flush()

    if job.application is not None:
        job.application.resume_version_id = record.id
        if job.application.status in (
            ApplicationStatus.discovered,
            ApplicationStatus.matched,
        ):
            job.application.status = ApplicationStatus.tailored
    db.commit()
    return record
