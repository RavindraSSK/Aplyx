"""Workday CxS public JSON endpoint (no key), per tenant.

ats_slug format: "<tenant>.<wdN>/<site>" e.g. "nvidia.wd5/NVIDIAExternalCareerSite".
Listing is one POST per page; descriptions need one GET per posting, capped."""
from datetime import datetime, timezone, timedelta
import re

from app.discovery.base import strip_html
from app.sources.base import RawJob, SourceAdapter, register

MAX_DETAILS = 40
PAGE = 20


def parse_slug(slug: str) -> tuple[str, str, str]:
    m = re.fullmatch(r"([\w-]+)\.(wd\d+)/([\w-]+)", slug or "")
    if not m:
        raise ValueError("workday slug must look like 'tenant.wd5/ExternalSite'")
    return m.group(1), m.group(2), m.group(3)


def _posted(text: str) -> datetime | None:
    """Workday gives 'Posted Today' / 'Posted 3 Days Ago' / 'Posted 30+ Days Ago'."""
    t = (text or "").lower()
    now = datetime.now(timezone.utc)
    if "today" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", t)
    return now - timedelta(days=int(m.group(1))) if m else None


@register
class Workday(SourceAdapter):
    name = "workday"
    kind = "ats"
    rate_limit_seconds = 0.3

    def fetch(self, slug=None, company=None, since=None, query=None) -> list[RawJob]:
        tenant, wd, site = parse_slug(slug)
        base = f"https://{tenant}.{wd}.myworkdayjobs.com"
        list_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
        out, offset, details = [], 0, 0
        while True:
            data = self._post_json(list_url, {"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": query or ""})
            items = data.get("jobPostings", [])
            for item in items:
                path = item.get("externalPath", "")
                description = ""
                if details < MAX_DETAILS and path:
                    try:
                        d = self._get_json(f"{base}/wday/cxs/{tenant}/{site}{path}")
                        info = d.get("jobPostingInfo") or {}
                        description = strip_html(info.get("jobDescription", ""))
                        details += 1
                    except Exception:
                        pass
                ext_id = (item.get("bulletFields") or [path])[0] or path
                out.append(RawJob(
                    external_id=str(ext_id),
                    source=self.name,
                    source_name=f"Workday: {tenant}/{site}",
                    company=company or tenant,
                    title=item.get("title", ""),
                    location=item.get("locationsText", "") or "",
                    description=description,
                    url=f"{base}/en-US/{site}{path}",
                    posted_at=_posted(item.get("postedOn", "")),
                ))
            offset += len(items)
            if not items or offset >= int(data.get("total", 0)) or offset >= 400:
                break
        return out
