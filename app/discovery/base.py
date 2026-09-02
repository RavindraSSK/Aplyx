"""Base fetcher: every ATS fetcher normalizes postings to NormalizedJob."""
import html
import re
from abc import ABC, abstractmethod
from datetime import datetime

import httpx
from pydantic import BaseModel

from app.config import get_settings

REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """ATS descriptions arrive as (often entity-escaped) HTML; reduce to plain text."""
    text = html.unescape(text or "")
    text = TAG_RE.sub(" ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def looks_remote(*fields: str) -> bool:
    return any(REMOTE_RE.search(f or "") for f in fields)


class NormalizedJob(BaseModel):
    external_id: str
    source: str
    company: str
    title: str
    location: str = ""
    remote: bool = False
    description: str = ""
    url: str
    posted_at: datetime | None = None


class BaseFetcher(ABC):
    source: str

    def __init__(self, client: httpx.Client | None = None):
        self._client = client

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=get_settings().http_timeout_seconds,
                headers={"User-Agent": "jobagent/0.1"},
                follow_redirects=True,
            )
        return self._client

    @abstractmethod
    def fetch(self, slug: str, company: str) -> list[NormalizedJob]:
        """Fetch and normalize all open postings for a board slug."""

    def _get_json(self, url: str):
        resp = self.client.get(url)
        resp.raise_for_status()
        return resp.json()
