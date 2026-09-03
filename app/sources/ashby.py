"""Ashby public job-board API (no key)."""
from datetime import datetime

from app.discovery.base import strip_html
from app.sources.base import RawJob, SourceAdapter, register

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
EMPLOYMENT = {"FullTime": "full_time", "PartTime": "part_time", "Intern": "internship",
              "Contract": "contract", "Temporary": "temp"}


@register
class Ashby(SourceAdapter):
    name = "ashby"
    kind = "ats"

    def fetch(self, slug=None, company=None, since=None, query=None) -> list[RawJob]:
        data = self._get_json(API.format(slug=slug))
        out = []
        for item in data.get("jobs", []):
            comp = (item.get("compensation") or {}).get("compensationTierSummary") or {}
            published = item.get("publishedAt")
            out.append(RawJob(
                external_id=str(item["id"]),
                source=self.name,
                source_name=f"Ashby board: {slug}",
                company=company or slug,
                title=item.get("title", ""),
                location=item.get("location", "") or "",
                remote=bool(item.get("isRemote")) or None,
                description=strip_html(item.get("descriptionHtml") or item.get("descriptionPlain", "")),
                url=item.get("jobUrl") or item.get("applyUrl", ""),
                posted_at=datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
                employment_type=EMPLOYMENT.get(item.get("employmentType") or ""),
            ))
        return out
