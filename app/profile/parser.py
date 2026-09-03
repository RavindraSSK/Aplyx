"""Resume -> structured profile via one Claude call with a strict JSON schema.

Rules baked into the prompt: extract, don't invent. Anything the resume doesn't
state is null / empty. The only inferred fields are `inferred_target_titles`
and `seniority_band`, and they are named as inferences.
"""
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.config import get_settings

# Bump when the prompt or schema changes so stored profiles record their lineage.
PROFILE_PROMPT_VERSION = "profile-parse-1.0"


class Education(BaseModel):
    degree: str | None = Field(None, description="e.g. 'M.S.', 'B.Tech', 'Ph.D.'")
    field: str | None = Field(None, description="field of study as written")
    school: str | None = None
    graduation_date: str | None = Field(None, description="YYYY-MM or YYYY as written; null if absent")
    gpa: str | None = None


class ParsedProfile(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    website_url: str | None = None
    summary: str | None = Field(None, description="the resume's own summary/objective, verbatim or lightly trimmed")
    education: list[Education] = Field(default_factory=list)
    years_of_experience: float | None = Field(
        None, description="total professional (non-academic) experience in years, computed from dated roles; null if not derivable"
    )
    work_authorization: str | None = Field(
        None, description="verbatim work-authorization / visa statement if present, else null"
    )
    needs_sponsorship: bool | None = Field(
        None, description="true/false ONLY if the resume states it; otherwise null"
    )
    skills: list[str] = Field(default_factory=list, description="skills exactly as listed on the resume")
    titles_held: list[str] = Field(default_factory=list, description="job/internship titles as written")
    inferred_target_titles: list[str] = Field(
        default_factory=list, description="INFERRED: 3-6 job titles this candidate is plausibly targeting"
    )
    seniority_band: Literal["intern", "new_grad", "junior", "mid", "senior", "staff_plus"] | None = Field(
        None, description="INFERRED from experience and education"
    )
    locations: list[str] = Field(default_factory=list, description="locations stated on the resume")
    remote_preference: Literal["remote", "hybrid", "onsite", "flexible"] | None = Field(
        None, description="ONLY if stated on the resume"
    )


SYSTEM_PROMPT = """\
You extract a structured candidate profile from resume text.

Rules:
1. Extract only what the resume states. Never invent employers, dates, degrees, \
skills, contact details, or authorization status. If something is absent, use null \
(or an empty list).
2. The ONLY fields you may infer are `inferred_target_titles` and `seniority_band`, \
and only from evidence in the resume (degree level, dated experience, titles held).
3. `years_of_experience`: sum the durations of dated professional roles (exclude \
coursework and academic degrees; include internships and research positions). \
If dates are missing, return null rather than guessing.
4. Keep skills as written on the resume (do not expand or normalize them).
5. Output must satisfy the schema exactly.
"""


class ParseResult(BaseModel):
    profile: ParsedProfile
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


def parse_resume(text: str, client: anthropic.Anthropic | None = None) -> ParseResult:
    settings = get_settings()
    if client is None:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)

    response = client.messages.parse(
        model=settings.claude_model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"<resume>\n{text}\n</resume>"}],
        output_format=ParsedProfile,
    )
    usage = getattr(response, "usage", None)
    return ParseResult(
        profile=response.parsed_output,
        model=settings.claude_model,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )
