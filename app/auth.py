"""Auth behind a swappable interface (Section 4.2).

Today: HTTP Basic with DASHBOARD_PASSWORD mapping to the single owner user.
Swapping to email/OAuth = implement another AuthProvider and change one line
in `get_auth_provider()`."""
import base64
import secrets
from abc import ABC, abstractmethod
from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db, get_session_factory
from app.db.tenancy import current_user_id


class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, request: Request) -> int | None:
        """Return the authenticated user's id, or None if the request is not authenticated."""

    @abstractmethod
    def challenge_headers(self) -> dict[str, str]:
        """Headers to send with a 401."""


def ensure_owner(db: Session) -> User:
    """Create the single owner user if missing (idempotent)."""
    email = get_settings().owner_email
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name="Owner")
        db.add(user)
        db.commit()
    return user


class BasicAuthProvider(AuthProvider):
    """Any username + DASHBOARD_PASSWORD -> owner user. If no password is
    configured (local dev) every request is the owner."""

    def __init__(self):
        self._owner_id: int | None = None

    def _owner(self) -> int:
        if self._owner_id is None:
            db = get_session_factory()()
            try:
                self._owner_id = ensure_owner(db).id
            finally:
                db.close()
        return self._owner_id

    def authenticate(self, request: Request) -> int | None:
        settings = get_settings()
        password = settings.dashboard_password
        header = request.headers.get("authorization", "")
        if settings.cron_secret and header.startswith("Bearer "):
            if secrets.compare_digest(header[7:], settings.cron_secret):
                return self._owner()  # Vercel cron -> owner
        if not password:
            return self._owner()
        supplied = ""
        if header.startswith("Basic "):
            try:
                supplied = base64.b64decode(header[6:]).decode().partition(":")[2]
            except Exception:
                supplied = ""
        if secrets.compare_digest(supplied, password):
            return self._owner()
        return None

    def challenge_headers(self) -> dict[str, str]:
        return {"WWW-Authenticate": 'Basic realm="jobagent"'}


@lru_cache
def get_auth_provider() -> AuthProvider:
    return BasicAuthProvider()


def current_user(db: Session = Depends(get_db)) -> User:
    """FastAPI dependency: the authenticated user (set by the auth middleware)."""
    uid = current_user_id.get()
    if uid is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=401, detail="unknown user")
    return user
