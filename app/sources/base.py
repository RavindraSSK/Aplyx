"""SourceAdapter interface. One module per source; the registry makes adding a
source ~50 lines. Adapters return RawJob; app/sources/normalize.py turns them
into Job rows. Adapters never touch the DB."""
from abc import ABC, abstractmethod
from datetime import datetime

import httpx
from pydantic import BaseModel

from app.config import get_settings

USER_AGENT = "jobagent/0.2 (+https://github.com/RavindraSSK/Aplyx; contact: {email})"


class RawJob(BaseModel):
    external_id: str
    source: str  # adapter name, e.g. "greenhouse", "adzuna"
    source_name: str  # human-readable provenance, e.g. "Greenhouse board: anthropic"
    company: str
    title: str
    location: str = ""
    remote: bool | None = None  # None -> infer from text
    description: str = ""  # plain text (HTML stripped by the adapter)
    url: str  # canonical posting URL the user can apply on
    posted_at: datetime | None = None
    employment_type: str | None = None  # source-provided only; never guessed
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    application_deadline: datetime | None = None


class SourceAdapter(ABC):
    name: str  # registry key; also Job.source
    kind: str  # "ats" (per-company board) or "aggregator" (query-based)
    required_settings: tuple[str, ...] = ()  # settings that must be non-empty
    rate_limit_seconds: float = 0.0  # polite delay between requests

    def __init__(self, client: httpx.Client | None = None):
        self._client = client

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            s = get_settings()
            self._client = httpx.Client(
                timeout=s.http_timeout_seconds,
                headers={"User-Agent": USER_AGENT.format(email=s.owner_email)},
                follow_redirects=True,
            )
        return self._client

    @classmethod
    def available(cls) -> bool:
        s = get_settings()
        return all(getattr(s, key, "") for key in cls.required_settings)

    @abstractmethod
    def fetch(self, slug: str | None = None, company: str | None = None,
              since: datetime | None = None, query: str | None = None) -> list[RawJob]:
        """ATS adapters: fetch a company's board (slug, company). Aggregators:
        fetch postings matching `query` (slug/company ignored)."""

    def _throttle(self):
        if self.rate_limit_seconds:
            import time

            time.sleep(self.rate_limit_seconds)

    def _get_json(self, url: str, **kwargs):
        self._throttle()
        resp = self.client.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post_json(self, url: str, payload: dict, **kwargs):
        self._throttle()
        resp = self.client.post(url, json=payload, **kwargs)
        resp.raise_for_status()
        return resp.json()


REGISTRY: dict[str, type[SourceAdapter]] = {}


def register(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    REGISTRY[cls.name] = cls
    return cls


def get_adapter(name: str) -> SourceAdapter:
    import app.sources.all  # noqa: F401  (populates the registry)

    if name not in REGISTRY:
        raise KeyError(f"unknown source '{name}'; known: {sorted(REGISTRY)}")
    return REGISTRY[name]()


def ats_adapters() -> dict[str, type[SourceAdapter]]:
    import app.sources.all  # noqa: F401

    return {k: v for k, v in REGISTRY.items() if v.kind == "ats"}


def aggregator_adapters() -> dict[str, type[SourceAdapter]]:
    import app.sources.all  # noqa: F401

    return {k: v for k, v in REGISTRY.items() if v.kind == "aggregator"}
