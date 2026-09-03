"""Multi-tenant plumbing: the current user id travels in a contextvar and is
pushed into every PostgreSQL transaction as `app.user_id`, which the row-level
security policies (migration 0002) read. A missing value fails CLOSED on
Postgres: RLS returns zero rows for per-user tables."""
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event, text
from sqlalchemy.orm import Session

current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)

PER_USER_TABLES = ("applications", "tailored_resumes", "resume_files", "candidate_profiles", "llm_usage")


@contextmanager
def as_user(user_id: int | None):
    token = current_user_id.set(user_id)
    try:
        yield
    finally:
        current_user_id.reset(token)


@event.listens_for(Session, "after_begin")
def _set_rls_user(session, transaction, connection):
    if connection.dialect.name != "postgresql":
        return
    uid = current_user_id.get()
    # set_config(..., is_local=true) scopes the value to this transaction.
    connection.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": "" if uid is None else str(uid)},
    )
