"""Lever public postings API (no key)."""
from datetime import datetime, timezone

from app.discovery.base import strip_html
from app.sources.base import RawJob, SourceAdapter, register

API = "https://api.lever.co/v0/postings/{slug}?mode=json"
COMMITMENT = {"full-time": "full_time", "part-time": "part_time", "intern": "internship",
              "internship": "internship", "contract": "contract", "contractor": "contract"}


@register
class Lever(SourceAdapter):
    name = "lever"
    kind = "ats"

    def fetch(self, slug=None, company=None, since=None, query=None) -> list[RawJob]:
        data = self._get_json(API.format(slug=slug))
        out = []
        for item in data:
            cats = item.get("categories") or {}
            workplace = (item.get("workplaceType") or "").lower()
            commitment = (cats.get("commitment") or "").lower()
            out.append(RawJob(
                external_id=str(item["id"]),
                source=self.name,
                source_name=f"Lever board: {slug}",
                company=company or slug,
                title=item.get("text", ""),
                location=cats.get("location", "") or "",
                remote=True if workplace == "remote" else None,
                description=strip_html(item.get("descriptionPlain") or item.get("description", "")),
                url=item.get("hostedUrl", ""),
                posted_at=datetime.fromtimestamp(item["createdAt"] / 1000, tz=timezone.utc) if item.get("createdAt") else None,
                employment_type=next((v for k, v in COMMITMENT.items() if k in commitment), None),
            ))
        return out
