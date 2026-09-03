"""Milestone 1.1 API: resume upload, profile read, manual corrections."""
from datetime import datetime

import anthropic
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db.models import CandidateProfile, User
from app.db.session import get_db
from app.profile.extract import UnsupportedResume
from app.profile.service import (
    InvalidProfileField,
    NoProfile,
    ingest_resume,
    latest_profile,
    update_profile,
)
from app.vertical.loader import load_vertical

router = APIRouter(prefix="/api")

MAX_RESUME_BYTES = 5 * 1024 * 1024


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    resume_file_id: int | None
    parsed: dict
    overrides: dict
    effective: dict
    prompt_version: str
    parser_model: str
    embedding_model: str
    created_at: datetime
    resume_filename: str | None = None


def _out(profile: CandidateProfile) -> ProfileOut:
    out = ProfileOut.model_validate(profile)
    out.resume_filename = profile.resume_file.filename if profile.resume_file else None
    return out


@router.post("/resume", response_model=ProfileOut)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="resume larger than 5 MB")
    try:
        profile = ingest_resume(db, user, data, file.filename or "resume", file.content_type)
    except UnsupportedResume as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    except anthropic.AuthenticationError:
        raise HTTPException(
            status_code=502,
            detail="Claude rejected the API key. Set a valid ANTHROPIC_API_KEY in .env "
            "(or Vercel env vars) and restart.",
        )
    except anthropic.APIStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc.message}")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=502, detail="Could not reach the Claude API (network).")
    except httpx.HTTPStatusError as exc:  # embedding provider (Voyage) errors
        raise HTTPException(
            status_code=502,
            detail=f"Embedding provider error {exc.response.status_code} - check VOYAGE_API_KEY "
            f"(or unset it to use the local fallback).",
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach the embedding provider (network).")
    return _out(profile)


@router.get("/profile", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db), user: User = Depends(current_user)):
    profile = latest_profile(db, user)
    if profile is None:
        raise HTTPException(status_code=404, detail="no profile yet - upload a resume")
    return _out(profile)


@router.patch("/profile", response_model=ProfileOut)
def patch_profile(patch: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        return _out(update_profile(db, user, patch))
    except NoProfile as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidProfileField as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/vertical")
def get_vertical():
    """The active vertical's bands, role families and skill taxonomy (for UI pickers)."""
    v = load_vertical()
    return {
        "name": v.name,
        "bands": v.bands,
        "families": {
            k: {"band": f.band, "label": f.label, "title_synonyms": list(f.title_synonyms)}
            for k, f in v.families.items()
        },
        "ai_relevance_levels": v.ai_relevance_levels,
        "dashboard_default_ai_relevance": list(v.dashboard_default_ai_relevance),
        "skills": [{"canonical": s.canonical, "category": s.category} for s in v.skills],
    }
