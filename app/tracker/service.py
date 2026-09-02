"""Application status tracking with a sane transition graph."""
from sqlalchemy.orm import Session

from app.db.models import Application, ApplicationStatus

# Allowed forward transitions; rejected is reachable from anywhere.
TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.discovered: {ApplicationStatus.matched, ApplicationStatus.rejected},
    ApplicationStatus.matched: {ApplicationStatus.tailored, ApplicationStatus.rejected},
    ApplicationStatus.tailored: {ApplicationStatus.ready_to_apply, ApplicationStatus.rejected},
    ApplicationStatus.ready_to_apply: {ApplicationStatus.applied, ApplicationStatus.rejected},
    ApplicationStatus.applied: {ApplicationStatus.interview, ApplicationStatus.rejected},
    ApplicationStatus.interview: {ApplicationStatus.rejected},
    ApplicationStatus.rejected: set(),
}


class InvalidTransition(ValueError):
    pass


def update_status(
    db: Session,
    application: Application,
    new_status: ApplicationStatus,
    notes: str | None = None,
) -> Application:
    if new_status not in TRANSITIONS[application.status]:
        raise InvalidTransition(
            f"cannot move application {application.id} from "
            f"'{application.status.value}' to '{new_status.value}'"
        )
    application.status = new_status
    if notes is not None:
        application.notes = notes
    db.commit()
    return application
