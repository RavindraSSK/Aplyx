"""Greenhouse apply bot — Phase 1 stub. No automation is implemented yet."""
from app.apply.base import ApplicationPayload, ApplyResult, BaseApplyBot


class GreenhouseApplyBot(BaseApplyBot):
    source = "greenhouse"

    def fill(self, job_url: str, payload: ApplicationPayload) -> ApplyResult:
        # TODO(phase-2): launch Playwright, navigate to job_url + "#app",
        #   fill first/last name, email, phone from payload,
        #   upload resume file to input[type=file],
        #   answer standard dropdowns (work auth, sponsorship) from payload.answers,
        #   screenshot the filled form for human review, DO NOT click submit.
        raise NotImplementedError("Greenhouse auto-fill lands in Phase 2")

    def submit(self, job_url: str) -> ApplyResult:
        # TODO(phase-2): only callable after explicit human approval of the
        #   filled-form screenshot; click submit and capture confirmation.
        raise NotImplementedError("Greenhouse auto-submit lands in Phase 2")
