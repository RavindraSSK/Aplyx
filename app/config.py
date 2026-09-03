"""Application settings loaded from environment / .env via pydantic-settings."""
import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    database_url: str = "sqlite:///./jobagent.db"
    # When set, every route requires HTTP Basic auth with this password.
    # REQUIRED for any public deployment (Vercel etc.).
    dashboard_password: str = ""
    # Single-tenant owner identity used by the Basic-auth provider.
    owner_email: str = "owner@local"

    claude_model: str = "claude-sonnet-4-6"
    resume_path: str = "data/resume.md"
    targets_path: str = "data/targets.yaml"
    http_timeout_seconds: float = 30.0

    # Vertical (domain) configuration - data only, see config/vertical/<name>/
    vertical: str = "ai"
    vertical_config_dir: str = "config/vertical"

    # Run `alembic upgrade head` automatically on startup / first request.
    # Defaults to on when running on Vercel (no shell there to run it by hand).
    auto_migrate: bool = False

    # Ingestion (Milestone 1.2)
    ingest_batch_size: int = 8          # companies per POST /api/discover invocation (serverless-safe)
    ingest_stale_hours: int = 12        # re-fetch a company board after this many hours
    cron_secret: str = ""               # Vercel cron sends "Authorization: Bearer <CRON_SECRET>"
    # Aggregator API keys - a missing key means that source is skipped, never a crash
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    usajobs_api_key: str = ""
    usajobs_email: str = ""
    aggregators_enabled: str = "remotive,remoteok,adzuna,usajobs"  # comma-separated

    # Embeddings: auto | voyage | local | hashing  (see app/embeddings/provider.py)
    embedding_provider: str = "auto"
    voyage_api_key: str = ""
    voyage_model: str = "voyage-3-lite"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"  # local provider

    @model_validator(mode="after")
    def _serverless_sqlite_fallback(self):
        # Vercel's filesystem is read-only except /tmp; without a real
        # DATABASE_URL the default relative SQLite path would crash on boot.
        if os.environ.get("VERCEL") and self.database_url == "sqlite:///./jobagent.db":
            self.database_url = "sqlite:////tmp/jobagent.db"
        if os.environ.get("VERCEL") and "AUTO_MIGRATE" not in os.environ:
            self.auto_migrate = True
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
