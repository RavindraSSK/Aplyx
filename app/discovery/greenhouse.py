"""Greenhouse public board API fetcher."""
from datetime import datetime

from app.discovery.base import BaseFetcher, NormalizedJob, looks_remote, strip_html

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


class GreenhouseFetcher(BaseFetcher):
    source = "greenhouse"

    def fetch(self, slug: str, company: str) -> list[NormalizedJob]:
        data = self._get_json(API_URL.format(slug=slug))
        jobs = []
        for item in data.get("jobs", []):
            location = (item.get("location") or {}).get("name", "") or ""
            description = strip_html(item.get("content", ""))
            posted_at = None
            if item.get("updated_at"):
                posted_at = datetime.fromisoformat(item["updated_at"])
            jobs.append(
                NormalizedJob(
                    external_id=str(item["id"]),
                    source=self.source,
                    company=company,
                    title=item.get("title", ""),
                    location=location,
                    remote=looks_remote(location, item.get("title", "")),
                    description=description,
                    url=item.get("absolute_url", ""),
                    posted_at=posted_at,
                )
            )
        return jobs
