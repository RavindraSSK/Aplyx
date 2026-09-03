"""Remotive public remote-jobs API (no key; attribution requested)."""
from datetime import datetime

from app.discovery.base import strip_html
from app.sources.base import RawJob, SourceAdapter, register

API = "https://remotive.com/api/remote-jobs"
JOB_TYPE = {"full_time": "full_time", "part_time": "part_time", "contract": "contract", "internship": "internship"}


@register
class Remotive(SourceAdapter):
    name = "remotive"
    kind = "aggregator"
    rate_limit_seconds = 2.0

    def fetch(self, slug=None, company=None, since=None, query=None) -> list[RawJob]:
        data = self._get_json(API, params={"search": query or "", "limit": 100})
        out = []
        for j in data.get("jobs", []):
            pub = j.get("publication_date")
            out.append(RawJob(
                external_id=str(j["id"]),
                source=self.name,
                source_name="Remotive",
                company=j.get("company_name", ""),
                title=j.get("title", ""),
                location=j.get("candidate_required_location", "") or "Remote",
                remote=True,
                description=strip_html(j.get("description", "")),
                url=j.get("url", ""),
                posted_at=datetime.fromisoformat(pub) if pub else None,
                employment_type=JOB_TYPE.get(j.get("job_type") or ""),
                salary_min=None, salary_max=None,
            ))
        return out
