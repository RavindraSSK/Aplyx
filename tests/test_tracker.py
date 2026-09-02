import pytest

from app.db.models import Application, ApplicationStatus, Job
from app.tracker.service import InvalidTransition, update_status


@pytest.fixture
def application(db):
    job = Job(
        external_id="1", source="lever", company="Globex",
        title="Dev", location="NY", remote=False,
        description="", url="https://x.example/1",
    )
    db.add(job)
    db.flush()
    app_row = Application(job_id=job.id, status=ApplicationStatus.discovered)
    db.add(app_row)
    db.commit()
    return app_row


def test_full_happy_path(db, application):
    for status in [
        ApplicationStatus.matched,
        ApplicationStatus.tailored,
        ApplicationStatus.ready_to_apply,
        ApplicationStatus.applied,
        ApplicationStatus.interview,
    ]:
        update_status(db, application, status)
    assert application.status == ApplicationStatus.interview


def test_rejected_reachable_from_anywhere(db, application):
    update_status(db, application, ApplicationStatus.rejected, notes="not a fit")
    assert application.status == ApplicationStatus.rejected
    assert application.notes == "not a fit"


def test_invalid_transition_raises(db, application):
    with pytest.raises(InvalidTransition):
        update_status(db, application, ApplicationStatus.applied)  # discovered -> applied
    with pytest.raises(InvalidTransition):
        update_status(db, application, ApplicationStatus.discovered)  # no-op/backwards
