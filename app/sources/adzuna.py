"""Adzuna search API (free tier; needs ADZUNA_APP_ID + ADZUNA_APP_KEY)."""
from datetime import datetime

from app.discovery.base import strip_html
from app.config import get_settings
from app.sources.base import RawJob, SourceAdapter, register

API = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"
CONTRACT = {"permanent": None, "contract": "contract"}
TIME = {"full_time": "full_time", "part_time": "part_time"}


@register
class Adzuna(SourceAdapter):
    name = "adzuna"
    kind = "aggregator"
    required_settings = ("adzuna_app_id", "adzuna_app_key")
    rate_limit_seconds = 1.0
    max_pages = 2

    def fetch(self, slug=None, company=None, since=None, query=None) -> list[RawJob]:
        s = get_settings()
        out = []
        for page in range(1, self.max_pages + 1):
            data = self._get_json(API.format(page=page), params={
                "app_id": s.adzuna_app_id, "app_key": s.adzuna_app_key,
                "results_per_page": 50, "what": query or "", "max_days_old": 30,
                "content-type": "application/json",
            })
            results = data.get("results", [])
            for r in results:
                created = r.get("created")
                emp = TIME.get(r.get("contract_time") or "") or CONTRACT.get(r.get("contract_type") or "")
                out.append(RawJob(
                    external_id=str(r["id"]),
                    source=self.name,
                    source_name="Adzuna",
                    company=(r.get("company") or {}).get("display_name") or "",
                    title=r.get("title", ""),
                    location=(r.get("location") or {}).get("display_name") or "",
                    description=strip_html(r.get("description", "")),
                    url=r.get("redirect_url", ""),
                    posted_at=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
                    employment_type=emp,
                    salary_min=r.get("salary_min"),
                    salary_max=r.get("salary_max"),
                    salary_currency="USD" if r.get("salary_min") or r.get("salary_max") else None,
                    salary_period="year" if r.get("salary_min") or r.get("salary_max") else None,
                ))
            if len(results) < 50:
                break
        return out
