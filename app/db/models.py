"""SQLAlchemy models: jobs, applications, tailored resumes."""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ApplicationStatus(str, enum.Enum):
    discovered = "discovered"
    matched = "matched"
    tailored = "tailored"
    ready_to_apply = "ready_to_apply"
    applied = "applied"
    interview = "interview"
    rejected = "rejected"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("url", name="uq_jobs_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32))  # greenhouse | lever | ashby
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    location: Mapped[str] = mapped_column(String(512), default="")
    remote: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1024))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    application: Mapped["Application | None"] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    tailored_resumes: Mapped[list["TailoredResume"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="application_status"),
        default=ApplicationStatus.discovered,
    )
    resume_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("tailored_resumes.id"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    job: Mapped[Job] = relationship(back_populates="application")
    resume_version: Mapped["TailoredResume | None"] = relationship(
        foreign_keys=[resume_version_id]
    )


class TailoredResume(Base):
    __tablename__ = "tailored_resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    content_md: Mapped[str] = mapped_column(Text)
    diff: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(
        back_populates="tailored_resumes", foreign_keys=[job_id]
    )
