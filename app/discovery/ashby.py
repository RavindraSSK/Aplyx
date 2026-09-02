"""Ashby public job-board API fetcher."""
from datetime import datetime

from app.discovery.base import BaseFetcher, NormalizedJob, looks_remote, strip_html

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false"


class AshbyFetcher(BaseFetcher):
    source = "ashby"

    def fetch(self, slug: str, company: str) -> list[NormalizedJob]:
        data = self._get_json(API_URL.format(slug=slug))
        jobs = []
        for item in data.get("jobs", []):
            location = item.get("location", "") or ""
            posted_at = None
            if item.get("publishedAt"):
                posted_at = datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00"))
            jobs.append(
                NormalizedJob(
                    external_id=str(item["id"]),
                    source=self.source,
                    company=company,
                    title=item.get("title", ""),
                    location=location,
                    remote=bool(item.get("isRemote")) or looks_remote(location),
                    description=strip_html(item.get("descriptionHtml") or item.get("descriptionPlain", "")),
                    url=item.get("jobUrl") or item.get("applyUrl", ""),
                    posted_at=posted_at,
                )
            )
        return jobs
