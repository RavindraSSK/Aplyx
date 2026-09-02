"""Phase 2: Playwright form-fillers. Phase 1 ships interfaces only.

HUMAN-IN-THE-LOOP CONTRACT: an ApplyBot may pre-fill a form, but submission
requires an explicit approve step — nothing is ever sent automatically.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ApplicationPayload:
    """Everything a form-filler needs: contact info + the approved resume."""
    full_name: str
    email: str
    phone: str
    resume_path: str  # rendered PDF/markdown of the approved tailored resume
    linkedin_url: str = ""
    answers: dict[str, str] | None = None  # question text -> approved answer


@dataclass
class ApplyResult:
    filled: bool
    submitted: bool  # only ever True after an explicit human approve step
    screenshot_path: str = ""
    error: str = ""


class BaseApplyBot(ABC):
    """One bot per ATS. `fill` stops at the review screen; `submit` is separate
    and must only be called after the human has approved the filled form."""

    source: str

    @abstractmethod
    def fill(self, job_url: str, payload: ApplicationPayload) -> ApplyResult:
        """Open the application form and fill it WITHOUT submitting."""

    @abstractmethod
    def submit(self, job_url: str) -> ApplyResult:
        """Submit a previously filled + human-approved form."""
