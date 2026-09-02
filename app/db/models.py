"""SQLAlchemy models: jobs, applications, tailored resumes."""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    LargeBinary,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.types import EmbeddingVector


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Tenant. Single owner today; every per-user table carries user_id (Section 4)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
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
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    content_md: Mapped[str] = mapped_column(Text)
    diff: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(
        back_populates="tailored_resumes", foreign_keys=[job_id]
    )


class ResumeFile(Base):
    """An uploaded resume, stored as bytes (Vercel has no persistent disk)."""
    __tablename__ = "resume_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128), default="")
    size_bytes: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    extracted_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CandidateProfile(Base):
    """Versioned structured profile. `parsed` is the LLM output for the source
    resume; `overrides` are the user's manual edits (they always win);
    `effective` = parsed merged with overrides, and is what matching uses."""
    __tablename__ = "candidate_profiles"
    __table_args__ = (Index("ix_candidate_profiles_user_version", "user_id", "version", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    resume_file_id: Mapped[int | None] = mapped_column(ForeignKey("resume_files.id"), nullable=True)
    parsed: Mapped[dict] = mapped_column(JSON)
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    effective: Mapped[dict] = mapped_column(JSON)
    prompt_version: Mapped[str] = mapped_column(String(32))
    parser_model: Mapped[str] = mapped_column(String(64), default="")
    embedding: Mapped[list | None] = mapped_column(EmbeddingVector, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    resume_file: Mapped[ResumeFile | None] = relationship()


class LlmUsage(Base):
    """Per-call LLM metering (Section 4.5): tokens and cost per user per feature."""
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    feature: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
