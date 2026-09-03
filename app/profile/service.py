"""Resume ingestion and versioned candidate profiles."""
from types import SimpleNamespace

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, ResumeFile, User
from app.embeddings.provider import embed_text
from app.llm.metering import record_usage
from app.profile.extract import extract_text
from app.profile.parser import PROFILE_PROMPT_VERSION, ParsedProfile, parse_resume
from app.vertical.loader import load_vertical

# Fields the user may override via PATCH /api/profile (everything in the parsed
# schema plus the taxonomy-derived list).
EDITABLE_FIELDS = set(ParsedProfile.model_fields) | {"other_skills"}


class NoProfile(LookupError):
    pass


class InvalidProfileField(ValueError):
    pass


def latest_profile(db: Session, user: User) -> CandidateProfile | None:
    return db.scalar(
        select(CandidateProfile)
        .where(CandidateProfile.user_id == user.id)
        .order_by(CandidateProfile.version.desc())
        .limit(1)
    )


def merge_effective(parsed: dict, overrides: dict) -> dict:
    """User edits always win. A None override means 'no override'."""
    effective = dict(parsed)
    for key, value in overrides.items():
        if value is not None:
            effective[key] = value
    return effective


def profile_embedding_text(effective: dict, resume_text: str) -> str:
    parts = [resume_text]
    if effective.get("skills"):
        parts.append("Skills: " + ", ".join(effective["skills"]))
    if effective.get("other_skills"):
        parts.append("Other skills: " + ", ".join(effective["other_skills"]))
    if effective.get("inferred_target_titles"):
        parts.append("Target titles: " + ", ".join(effective["inferred_target_titles"]))
    return "\n\n".join(p for p in parts if p)


def _normalize_parsed(parsed: ParsedProfile) -> dict:
    data = parsed.model_dump()
    canonical, other = load_vertical().normalize_skills(parsed.skills)
    data["skills_raw"] = list(parsed.skills)
    data["skills"] = canonical
    data["other_skills"] = other
    return data


def ingest_resume(
    db: Session,
    user: User,
    data: bytes,
    filename: str,
    content_type: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> CandidateProfile:
    text = extract_text(data, filename, content_type)
    resume = ResumeFile(
        user_id=user.id,
        filename=filename,
        content_type=content_type or "",
        size_bytes=len(data),
        data=data,
        extracted_text=text,
    )
    db.add(resume)
    db.flush()

    result = parse_resume(text, client=client)
    record_usage(
        db,
        user_id=user.id,
        feature="profile_parse",
        model=result.model,
        usage=SimpleNamespace(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_input_tokens=result.cache_read_tokens,
        ),
        prompt_version=PROFILE_PROMPT_VERSION,
    )

    parsed = _normalize_parsed(result.profile)
    previous = latest_profile(db, user)
    overrides = dict(previous.overrides) if previous else {}
    effective = merge_effective(parsed, overrides)
    emb = embed_text(profile_embedding_text(effective, text))

    profile = CandidateProfile(
        user_id=user.id,
        version=(previous.version + 1) if previous else 1,
        resume_file_id=resume.id,
        parsed=parsed,
        overrides=overrides,
        effective=effective,
        prompt_version=PROFILE_PROMPT_VERSION,
        parser_model=result.model,
        embedding=emb.vector,
        embedding_model=emb.model,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def update_profile(db: Session, user: User, patch: dict) -> CandidateProfile:
    """Apply manual corrections as overrides -> new profile version."""
    previous = latest_profile(db, user)
    if previous is None:
        raise NoProfile("upload a resume first")
    unknown = set(patch) - EDITABLE_FIELDS
    if unknown:
        raise InvalidProfileField(f"unknown profile field(s): {sorted(unknown)}")

    overrides = dict(previous.overrides)
    for key, value in patch.items():
        if value is None:
            overrides.pop(key, None)  # null clears the override -> back to parsed value
        else:
            overrides[key] = value

    effective = merge_effective(previous.parsed, overrides)
    resume_text = previous.resume_file.extracted_text if previous.resume_file else ""
    emb = embed_text(profile_embedding_text(effective, resume_text))

    profile = CandidateProfile(
        user_id=user.id,
        version=previous.version + 1,
        resume_file_id=previous.resume_file_id,
        parsed=previous.parsed,
        overrides=overrides,
        effective=effective,
        prompt_version=previous.prompt_version,
        parser_model=previous.parser_model,
        embedding=emb.vector,
        embedding_model=emb.model,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile
