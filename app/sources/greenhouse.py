"""Greenhouse public board API (no key)."""
from datetime import datetime

from app.discovery.base import strip_html
from app.sources.base import RawJob, SourceAdapter, register

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


@register
class Greenhouse(SourceAdapter):
    name = "greenhouse"
    kind = "ats"

    def fetch(self, slug=None, company=None, since=None, query=None) -> list[RawJob]:
        data = self._get_json(API.format(slug=slug))
        out = []
        for item in data.get("jobs", []):
            posted = item.get("first_published") or item.get("updated_at")
            out.append(RawJob(
                external_id=str(item["id"]),
                source=self.name,
                source_name=f"Greenhouse board: {slug}",
                company=company or slug,
                title=item.get("title", ""),
                location=((item.get("location") or {}).get("name") or ""),
                description=strip_html(item.get("content", "")),
                url=item.get("absolute_url", ""),
                posted_at=datetime.fromisoformat(posted) if posted else None,
            ))
        return out
