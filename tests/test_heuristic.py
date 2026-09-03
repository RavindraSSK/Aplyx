from types import SimpleNamespace

import httpx
import pytest
import anthropic

from app.profile.heuristic import HEURISTIC_MODEL, heuristic_parse
from app.profile.service import ingest_resume, parse_with_fallback

RESUME = """Ravi Kumar
ravi.kumar@example.com | +1 (617) 555-0134 | linkedin.com/in/ravikumar | github.com/ravik
Boston, MA

EDUCATION
M.S. in Artificial Intelligence, Northeastern University, Dec 2026
B.Tech in Computer Science, VIT University, 2023

EXPERIENCE
Machine Learning Intern - Acme Robotics (Jun 2025 - Aug 2025)
- Built a perception pipeline in PyTorch and OpenCV deployed on Kubernetes.
Research Assistant - Northeastern University (2024 - present)

SKILLS
Python, PyTorch, Hugging Face, LLMs, SQL, Docker, AWS, Tableau
"""


def test_heuristic_extracts_contact_education_skills_titles():
    p = heuristic_parse(RESUME)
    assert p.name == "Ravi Kumar"
    assert p.email == "ravi.kumar@example.com"
    assert p.phone and "617" in p.phone
    assert p.linkedin_url and "linkedin.com/in/ravikumar" in p.linkedin_url
    assert p.github_url and "github.com/ravik" in p.github_url
    assert p.locations == ["Boston, MA"]

    assert len(p.education) == 2
    ms = p.education[0]
    assert ms.degree.upper().startswith("M.S")
    assert ms.field == "Artificial Intelligence"
    assert ms.school == "Northeastern University"
    assert ms.graduation_date == "2026-12"
    assert p.education[1].graduation_date == "2023"

    assert "Machine Learning Intern" in p.titles_held
    assert "Research Assistant" in p.titles_held
    for s in ("Python", "PyTorch", "Hugging Face", "LLMs", "SQL", "Docker", "AWS", "Tableau", "OpenCV", "Kubernetes"):
        assert s in p.skills, s

    # never guessed:
    assert p.years_of_experience is None
    assert p.needs_sponsorship is None
    assert p.seniority_band is None
    assert p.inferred_target_titles == []


def test_fallback_used_when_no_api_key(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr("app.profile.service.get_settings",
                        lambda: get_settings().model_copy(update={"anthropic_api_key": ""}))
    result = parse_with_fallback(RESUME)
    assert result.model == HEURISTIC_MODEL
    assert result.profile.email == "ravi.kumar@example.com"


def _auth_error():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.AuthenticationError("API key is invalid.", response=httpx.Response(401, request=req), body=None)


def test_fallback_used_when_api_rejects_key(db, user, monkeypatch):
    class Rejecting:
        messages = SimpleNamespace(parse=lambda **kw: (_ for _ in ()).throw(_auth_error()))

    profile = ingest_resume(db, user, RESUME.encode(), "r.txt", "text/plain", client=Rejecting())
    assert profile.parser_model == HEURISTIC_MODEL
    assert profile.prompt_version == "heuristic-parse-1.0"
    assert profile.effective["email"] == "ravi.kumar@example.com"
    assert "pytorch" in profile.effective["skills"]  # taxonomy-normalized


def test_non_credit_bad_request_still_raises():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.BadRequestError("max_tokens too large", response=httpx.Response(400, request=req), body=None)

    class Bad:
        messages = SimpleNamespace(parse=lambda **kw: (_ for _ in ()).throw(err))

    with pytest.raises(anthropic.BadRequestError):
        parse_with_fallback(RESUME, client=Bad())


def test_name_skips_spaced_section_headers_and_bare_degree_mentions():
    text = """S U M M A R Y
Ravindra Medicharla
ravi@example.com | (314) 555-0000
M.S. in AI student passionate about ML.
E D U C A T I O N
M.S. in Artificial Intelligence, Saint Louis University, Jan 2025
B.Tech in Computer Science, All India University, 2018
"""
    p = heuristic_parse(text)
    assert p.name == "Ravindra Medicharla"
    assert [(e.degree.rstrip(".").upper(), e.school) for e in p.education] == [
        ("M.S", "Saint Louis University"), ("B.TECH", "All India University"),
    ]
