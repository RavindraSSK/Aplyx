"""SmartRecruiters public postings API (no key). Descriptions need one extra
call per posting, so they are fetched only for postings not seen before
(the ingest layer passes `since`/known ids via `query`-less calls; we cap here)."""
from datetime import datetime

from app.discovery.base import strip_html
from app.sources.base import RawJob, SourceAdapter, register

LIST_API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}"
DETAIL_API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}"
MAX_DETAILS = 60  # per fetch, keeps runs bounded on serverless


@register
class SmartRecruiters(SourceAdapter):
    name = "smartrecruiters"
    kind = "ats"
    rate_limit_seconds = 0.2

    def fetch(self, slug=None, company=None, since=None, query=None) -> list[RawJob]:
        out, offset, details = [], 0, 0
        while True:
            data = self._get_json(LIST_API.format(slug=slug, offset=offset))
            items = data.get("content", [])
            for item in items:
                loc = item.get("location") or {}
                location = ", ".join(p for p in [loc.get("city"), loc.get("region"), loc.get("country")] if p)
                description = ""
                if details < MAX_DETAILS:
                    try:
                        d = self._get_json(DETAIL_API.format(slug=slug, id=item["id"]))
                        sections = (d.get("jobAd") or {}).get("sections") or {}
                        description = strip_html(" ".join(
                            (sections.get(k) or {}).get("text", "") for k in
                            ("companyDescription", "jobDescription", "qualifications", "additionalInformation")))
                        details += 1
                    except Exception:
                        pass
                released = item.get("releasedDate")
                out.append(RawJob(
                    external_id=str(item["id"]),
                    source=self.name,
                    source_name=f"SmartRecruiters: {slug}",
                    company=company or (item.get("company") or {}).get("name") or slug,
                    title=item.get("name", ""),
                    location=location,
                    remote=bool(loc.get("remote")) or None,
                    description=description,
                    url=f"https://jobs.smartrecruiters.com/{slug}/{item['id']}",
                    posted_at=datetime.fromisoformat(released.replace("Z", "+00:00")) if released else None,
                    employment_type={"Full-time": "full_time", "Part-time": "part_time", "Intern": "internship",
                                     "Contract": "contract", "Temporary": "temp"}.get(
                        (item.get("typeOfEmployment") or {}).get("label", "")),
                ))
            offset += len(items)
            if not items or offset >= int(data.get("totalFound", 0)):
                break
        return out
