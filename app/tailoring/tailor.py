"""Claude-based resume tailoring. Never invents facts; output = markdown + unified diff."""
import difflib
from dataclasses import dataclass

import anthropic

from app.config import get_settings

SYSTEM_PROMPT = """\
You are a resume-tailoring assistant. You will receive a candidate's master \
resume in markdown and a job description. Produce a tailored version of the \
resume for this job.

STRICT RULES — violating any of these makes the output unusable:
1. NEVER invent, exaggerate, or alter facts: no new employers, titles, dates, \
degrees, certifications, metrics, or technologies the candidate did not list.
2. You may ONLY: reorder bullets and sections to surface the most relevant \
experience first, reword existing bullets for clarity and impact, and weave in \
keywords from the job description WHERE the resume already demonstrates that \
skill or experience.
3. Keep the same overall markdown structure and roughly the same length.
4. Do not add a cover letter, commentary, or explanation.
5. Output ONLY the tailored resume as markdown — no code fences, no preamble.
"""


@dataclass
class TailorResult:
    content_md: str
    diff: str
    model: str


def unified_diff(original: str, tailored: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            tailored.splitlines(keepends=True),
            fromfile="resume.md",
            tofile="resume.tailored.md",
        )
    )


def tailor_resume(
    resume_md: str,
    job_title: str,
    job_description: str,
    client: anthropic.Anthropic | None = None,
) -> TailorResult:
    settings = get_settings()
    if client is None:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)

    user_message = (
        f"# Job: {job_title}\n\n"
        f"## Job description\n\n{job_description}\n\n"
        f"## Master resume\n\n{resume_md}"
    )
    with client.messages.stream(
        model=settings.claude_model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        response = stream.get_final_message()

    tailored = "".join(b.text for b in response.content if b.type == "text").strip() + "\n"
    return TailorResult(
        content_md=tailored,
        diff=unified_diff(resume_md, tailored),
        model=settings.claude_model,
    )
