"""Careers URL -> (ats_provider, ats_slug). Pattern-matches known ATS hosts;
for a company's own careers page, fetches it once (real User-Agent, honors
robots.txt) and looks for an embedded ATS link."""
import re
from urllib.parse import urlparse
from urllib import robotparser

import httpx

from app.config import get_settings
from app.sources.base import USER_AGENT

PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"boards\.greenhouse\.io/embed/job_board\?for=([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([\w-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("workday", re.compile(r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", re.I)),
]


def detect_from_url(url: str) -> tuple[str, str] | None:
    for provider, pat in PATTERNS:
        m = pat.search(url or "")
        if not m:
            continue
        if provider == "workday":
            return provider, f"{m.group(1)}.{m.group(2)}/{m.group(3)}"
        return provider, m.group(1)
    return None


def _allowed_by_robots(url: str, client: httpx.Client) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        resp = client.get(robots_url, timeout=10)
        if resp.status_code >= 400:
            return True
        rp.parse(resp.text.splitlines())
    except Exception:
        return True
    return rp.can_fetch(USER_AGENT.split()[0], url)


def detect(url: str, client: httpx.Client | None = None) -> tuple[str, str] | None:
    """Direct pattern match first; otherwise fetch the page and scan its HTML."""
    hit = detect_from_url(url)
    if hit:
        return hit
    s = get_settings()
    client = client or httpx.Client(timeout=s.http_timeout_seconds, follow_redirects=True,
                                    headers={"User-Agent": USER_AGENT.format(email=s.owner_email)})
    if not _allowed_by_robots(url, client):
        return None
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except Exception:
        return None
    hit = detect_from_url(str(resp.url))  # redirects into an ATS host
    if hit:
        return hit
    for provider, pat in PATTERNS:
        m = pat.search(resp.text)
        if m:
            if provider == "workday":
                return provider, f"{m.group(1)}.{m.group(2)}/{m.group(3)}"
            return provider, m.group(1)
    return None
