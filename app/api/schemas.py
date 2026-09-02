"""Pydantic response/request schemas for the API."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import ApplicationStatus


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    status: ApplicationStatus
    resume_version_id: int | None
    notes: str
    created_at: datetime
    updated_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    company: str
    title: str
    location: str
    remote: bool
    url: str
    posted_at: datetime | None
    score: float | None
    score_reasons: list | None
    application: ApplicationOut | None = None


class StatusUpdate(BaseModel):
    status: ApplicationStatus
    notes: str | None = None


class TailoredOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    content_md: str
    diff: str
    model: str
    created_at: datetime


class DiscoverSummary(BaseModel):
    created: int
    updated: int
    errors: list[str]
