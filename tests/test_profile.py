import io
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import CandidateProfile, LlmUsage, ResumeFile
from app.profile.extract import UnsupportedResume, extract_text
from app.profile.parser import PROFILE_PROMPT_VERSION, ParsedProfile, parse_resume
from app.profile.service import ingest_resume, latest_profile, merge_effective, update_profile

RESUME_TEXT = """Jane Doe
jane@example.com · Boston, MA
M.S. Artificial Intelligence, Example University, Dec 2026
Skills: Python, PyTorch, LLMs, Kubeflow, Tableau
Machine Learning Intern — Acme (Jun 2025 – Aug 2025)
"""

PARSED = ParsedProfile(
    name="Jane Doe",
    email="jane@example.com",
    education=[{"degree": "M.S.", "field": "Artificial Intelligence", "school": "Example University", "graduation_date": "2026-12"}],
    years_of_experience=0.25,
    skills=["Python", "PyTorch", "LLMs", "Kubeflow", "Tableau"],
    titles_held=["Machine Learning Intern"],
    inferred_target_titles=["Machine Learning Engineer", "Applied Scientist"],
    seniority_band="new_grad",
    locations=["Boston, MA"],
)


class FakeClient:
    """Stands in for anthropic.Anthropic: .messages.parse returns PARSED."""

    def __init__(self, parsed=PARSED):
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)
        self._parsed = parsed

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed_output=self._parsed,
            usage=SimpleNamespace(input_tokens=1200, output_tokens=300, cache_read_input_tokens=0),
        )


def make_pdf(text: str) -> bytes:
    """Minimal valid single-page PDF with a text stream (Helvetica)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    import docx

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ── extraction ──────────────────────────────────────────────────────────────

def test_extract_pdf_docx_and_text():
    assert "Hello Resume" in extract_text(make_pdf("Hello Resume"), "cv.pdf", "application/pdf")
    assert "Jane Doe\nM.S. AI" == extract_text(make_docx(["Jane Doe", "M.S. AI"]), "cv.docx")
    assert extract_text(b"# Jane\n\nPython", "resume.md", "text/markdown") == "# Jane\n\nPython"


def test_extract_rejects_unknown_and_empty():
    with pytest.raises(UnsupportedResume):
        extract_text(b"...", "photo.png", "image/png")
    with pytest.raises(UnsupportedResume):
        extract_text(b"   \n", "empty.txt", "text/plain")


# ── parser ──────────────────────────────────────────────────────────────────

def test_parse_resume_uses_strict_prompt_and_schema():
    client = FakeClient()
    result = parse_resume(RESUME_TEXT, client=client)
    assert result.profile.name == "Jane Doe"
    assert result.input_tokens == 1200 and result.output_tokens == 300
    [call] = client.calls
    assert call["output_format"] is ParsedProfile
    assert "Never invent" in call["system"]
    assert RESUME_TEXT.strip() in call["messages"][0]["content"]


# ── service ─────────────────────────────────────────────────────────────────

def test_ingest_creates_versioned_profile_with_normalized_skills_and_metering(db, user):
    profile = ingest_resume(db, user, RESUME_TEXT.encode(), "resume.txt", "text/plain", client=FakeClient())
    assert profile.version == 1
    assert profile.user_id == user.id
    assert profile.prompt_version == PROFILE_PROMPT_VERSION
    # taxonomy normalization: aliases mapped, unknowns preserved
    assert profile.parsed["skills"] == ["python", "pytorch", "large language models", "kubernetes", "tableau"]
    assert profile.parsed["skills_raw"] == ["Python", "PyTorch", "LLMs", "Kubeflow", "Tableau"]
    assert profile.parsed["other_skills"] == []
    assert profile.effective == profile.parsed
    # embedding stored with its provenance
    assert profile.embedding and len(profile.embedding) == 512
    assert profile.embedding_model == "hashing-bow-512"
    # resume bytes + text stored
    rf = db.get(ResumeFile, profile.resume_file_id)
    assert rf.data == RESUME_TEXT.encode() and "Jane Doe" in rf.extracted_text
    # LLM call metered with cost
    [usage] = db.scalars(select(LlmUsage)).all()
    assert usage.feature == "profile_parse" and usage.user_id == user.id
    assert usage.input_tokens == 1200 and usage.cost_usd > 0
    assert usage.prompt_version == PROFILE_PROMPT_VERSION


def test_overrides_win_and_survive_reparse(db, user):
    ingest_resume(db, user, RESUME_TEXT.encode(), "resume.txt", client=FakeClient())
    v2 = update_profile(db, user, {"years_of_experience": 1.5, "inferred_target_titles": ["NLP Engineer"]})
    assert v2.version == 2
    assert v2.effective["years_of_experience"] == 1.5
    assert v2.effective["inferred_target_titles"] == ["NLP Engineer"]
    assert v2.parsed["years_of_experience"] == 0.25  # parsed value untouched

    # re-upload: new parse, same overrides still applied
    v3 = ingest_resume(db, user, RESUME_TEXT.encode(), "resume-v2.txt", client=FakeClient())
    assert v3.version == 3
    assert v3.overrides == {"years_of_experience": 1.5, "inferred_target_titles": ["NLP Engineer"]}
    assert v3.effective["years_of_experience"] == 1.5

    # null clears an override -> back to parsed
    v4 = update_profile(db, user, {"years_of_experience": None})
    assert v4.effective["years_of_experience"] == 0.25
    assert "years_of_experience" not in v4.overrides
    assert latest_profile(db, user).id == v4.id


def test_update_profile_rejects_unknown_fields_and_missing_profile(db, user):
    from app.profile.service import InvalidProfileField, NoProfile

    with pytest.raises(NoProfile):
        update_profile(db, user, {"name": "X"})
    ingest_resume(db, user, RESUME_TEXT.encode(), "r.txt", client=FakeClient())
    with pytest.raises(InvalidProfileField):
        update_profile(db, user, {"favourite_color": "blue"})


def test_merge_effective_ignores_none_overrides():
    assert merge_effective({"a": 1, "b": 2}, {"a": None, "b": 3}) == {"a": 1, "b": 3}


# ── API ─────────────────────────────────────────────────────────────────────

def test_profile_api_roundtrip(client, monkeypatch):
    monkeypatch.setattr("app.profile.service.parse_resume", lambda text, client=None: FakeClient()._parse() and _fake_result())

    assert client.get("/api/profile").status_code == 404

    resp = client.post("/api/resume", files={"file": ("resume.txt", RESUME_TEXT.encode(), "text/plain")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 1 and body["resume_filename"] == "resume.txt"
    assert body["effective"]["name"] == "Jane Doe"

    got = client.get("/api/profile").json()
    assert got["id"] == body["id"]

    patched = client.patch("/api/profile", json={"name": "Jane A. Doe"}).json()
    assert patched["version"] == 2 and patched["effective"]["name"] == "Jane A. Doe"
    assert patched["overrides"] == {"name": "Jane A. Doe"}

    bad = client.patch("/api/profile", json={"nope": 1})
    assert bad.status_code == 422

    unsupported = client.post("/api/resume", files={"file": ("x.png", b"\x89PNG", "image/png")})
    assert unsupported.status_code == 415

    vertical = client.get("/api/vertical").json()
    assert "ml_engineer" in vertical["families"] and vertical["name"] == "ai"


def _fake_result():
    from app.profile.parser import ParseResult

    return ParseResult(profile=PARSED, model="claude-sonnet-4-6", input_tokens=10, output_tokens=5)


def test_profile_page_served(client):
    resp = client.get("/profile")
    assert resp.status_code == 200 and "Review" in resp.text
    assert client.get("/static/app.css").status_code == 200


def test_upload_falls_back_to_heuristic_when_no_credits(client, monkeypatch):
    """A rejected Claude call (bad key / no credits) must not 500: the free
    extractive parser takes over and the profile says so."""
    import httpx
    import anthropic

    def boom(text, client=None):
        raise anthropic.AuthenticationError(
            "API key is invalid.",
            response=httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
            body=None,
        )

    from app.config import get_settings

    monkeypatch.setattr("app.profile.service.get_settings",
                        lambda: get_settings().model_copy(update={"anthropic_api_key": "sk-ant-bad"}))
    monkeypatch.setattr("app.profile.service.parse_resume", boom)
    resp = client.post("/api/resume", files={"file": ("resume.txt", RESUME_TEXT.encode(), "text/plain")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parser_model"] == "heuristic-1.0"
    assert body["effective"]["email"] == "jane@example.com"


def test_upload_reports_embedding_provider_error_cleanly(client, monkeypatch):
    import httpx

    monkeypatch.setattr("app.profile.service.parse_resume", lambda text, client=None: _fake_result())

    def bad_embed(text):
        req = httpx.Request("POST", "https://api.voyageai.com/v1/embeddings")
        raise httpx.HTTPStatusError("401", request=req, response=httpx.Response(401, request=req))

    monkeypatch.setattr("app.profile.service.embed_text", bad_embed)
    resp = client.post("/api/resume", files={"file": ("resume.txt", RESUME_TEXT.encode(), "text/plain")})
    assert resp.status_code == 502
    assert "VOYAGE_API_KEY" in resp.json()["detail"]
