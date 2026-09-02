"""Lever public postings API fetcher."""
from datetime import datetime, timezone

from app.discovery.base import BaseFetcher, NormalizedJob, looks_remote, strip_html

API_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


class LeverFetcher(BaseFetcher):
    source = "lever"

    def fetch(self, slug: str, company: str) -> list[NormalizedJob]:
        data = self._get_json(API_URL.format(slug=slug))
        jobs = []
        for item in data:
            categories = item.get("categories") or {}
            location = categories.get("location", "") or ""
            workplace = item.get("workplaceType", "") or ""
            posted_at = None
            if item.get("createdAt"):
                posted_at = datetime.fromtimestamp(item["createdAt"] / 1000, tz=timezone.utc)
            jobs.append(
                NormalizedJob(
                    external_id=str(item["id"]),
                    source=self.source,
                    company=company,
                    title=item.get("text", ""),
                    location=location,
                    remote=workplace.lower() == "remote" or looks_remote(location),
                    description=strip_html(item.get("descriptionPlain") or item.get("description", "")),
                    url=item.get("hostedUrl", ""),
                    posted_at=posted_at,
                )
            )
        return jobs
