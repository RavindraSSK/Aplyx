from types import SimpleNamespace

from app.db.models import Application, ApplicationStatus, Job
from app.tailoring.service import tailor_job
from app.tailoring.tailor import tailor_resume, unified_diff

ORIGINAL = "# Resume\n\n- Built APIs in Python\n- Managed AWS infra\n"
TAILORED = "# Resume\n\n- Managed AWS infra\n- Built APIs in Python with FastAPI\n"


class FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=TAILORED)])


class FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream()


def test_unified_diff_shows_changes():
    diff = unified_diff(ORIGINAL, TAILORED)
    assert "--- resume.md" in diff
    assert "+- Built APIs in Python with FastAPI" in diff


def test_tailor_resume_calls_claude_with_strict_prompt():
    client = FakeClient()
    result = tailor_resume(ORIGINAL, "Backend Engineer", "FastAPI role", client=client)
    assert result.content_md.strip() == TAILORED.strip()
    assert result.diff  # non-empty diff vs original
    [call] = client.calls
    assert "NEVER invent" in call["system"]
    assert "Backend Engineer" in call["messages"][0]["content"]
    assert ORIGINAL.strip() in call["messages"][0]["content"]


def test_tailor_job_persists_and_advances_status(db, user):
    job = Job(
        external_id="1", source="greenhouse", company="Acme",
        title="Backend Engineer", location="NY", remote=False,
        description="FastAPI role", url="https://x.example/1",
    )
    db.add(job)
    db.flush()
    db.add(Application(job_id=job.id, user_id=user.id, status=ApplicationStatus.matched))
    db.commit()

    record = tailor_job(db, job, resume_text=ORIGINAL, client=FakeClient(), user_id=user.id)
    assert record.user_id == user.id
    assert record.id is not None
    assert record.content_md.strip() == TAILORED.strip()
    assert record.diff
    db.refresh(job)
    assert job.application.status == ApplicationStatus.tailored
    assert job.application.resume_version_id == record.id
