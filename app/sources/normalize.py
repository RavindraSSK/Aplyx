"""RawJob -> Job column dict. Dedupe key = normalized (company, title, location)
so the same role arriving from an ATS board and an aggregator collapses."""
import hashlib
import re

from app.discovery.base import looks_remote, strip_html
from app.sources.base import RawJob

_SUFFIX_RE = re.compile(r"\b(inc|llc|corp|corporation|co|ltd|limited|plc|technologies|technology|labs)\b\.?", re.I)
_NONWORD_RE = re.compile(r"[^a-z0-9 ]+")
_SPACE_RE = re.compile(r"\s+")


def normalize_company(name: str) -> str:
    s = _SUFFIX_RE.sub(" ", (name or "").lower())
    s = _NONWORD_RE.sub(" ", s)
    return _SPACE_RE.sub(" ", s).strip()


def normalize_text(s: str) -> str:
    s = _NONWORD_RE.sub(" ", (s or "").lower())
    return _SPACE_RE.sub(" ", s).strip()


def normalize_location(loc: str) -> str:
    loc = (loc or "").lower()
    loc = loc.replace("united states", "us").replace("usa", "us")
    return normalize_text(loc)


def dedupe_key(company: str, title: str, location: str) -> str:
    raw = "|".join([normalize_company(company), normalize_text(title), normalize_location(location)])
    return hashlib.sha1(raw.encode()).hexdigest()


def to_job_columns(raw: RawJob) -> dict:
    description = strip_html(raw.description) if "<" in (raw.description or "") else (raw.description or "")
    remote = raw.remote if raw.remote is not None else looks_remote(raw.location, raw.title)
    return {
        "external_id": raw.external_id,
        "source": raw.source,
        "source_name": raw.source_name,
        "company": raw.company,
        "title": raw.title.strip(),
        "location": (raw.location or "").strip(),
        "remote": bool(remote),
        "description": description,
        "url": raw.url,
        "posted_at": raw.posted_at,
        "employment_type": raw.employment_type,
        "salary_min": raw.salary_min,
        "salary_max": raw.salary_max,
        "salary_currency": raw.salary_currency,
        "salary_period": raw.salary_period,
        "application_deadline": raw.application_deadline,
        "dedupe_key": dedupe_key(raw.company, raw.title, raw.location),
    }
