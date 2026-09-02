"""Application settings loaded from environment / .env via pydantic-settings."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    database_url: str = "sqlite:///./jobagent.db"
    claude_model: str = "claude-sonnet-4-6"
    resume_path: str = "data/resume.md"
    targets_path: str = "data/targets.yaml"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    http_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
