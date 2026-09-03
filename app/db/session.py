"""Engine / session factory. SQLite fallback for local dev, Postgres in docker."""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def init_db() -> None:
    """Create tables if they don't exist (dev convenience; alembic for real migrations)."""
    Base.metadata.create_all(get_engine())


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


_migrated = False


def ensure_schema() -> str:
    """Bring the database to the latest Alembic revision (idempotent, once per
    process). Used when AUTO_MIGRATE is on (default on Vercel). Falls back to
    create_all for brand-new SQLite dev databases."""
    global _migrated
    if _migrated:
        return "already"
    import logging
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    try:
        command.upgrade(cfg, "head")
        _migrated = True
        return "upgraded"
    except Exception:  # never take the app down over a migration race; log and continue
        logging.getLogger(__name__).exception("auto-migration failed")
        return "failed"
