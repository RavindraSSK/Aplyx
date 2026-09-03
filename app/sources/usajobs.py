"""USAJOBS search API (free; needs USAJOBS_API_KEY + USAJOBS_EMAIL as User-Agent).
Federal roles carry real application deadlines and grade levels."""
from datetime import datetime

from app.discovery.base import strip_html
from app.config import get_settings
from app.sources.base import RawJob, SourceAdapter, register

API = "https://data.usajobs.gov/api/search"
SCHEDULE = {"Full-time": "full_time", "Part-time": "part_time", "Intermittent": "temp"}


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


@register
class USAJobs(SourceAdapter):
    name = "usajobs"
    kind = "aggregator"
    required_settings = ("usajobs_api_key", "usajobs_email")
    rate_limit_seconds = 0.5

    def fetch(self, slug=None, company=None, since=None, query=None) -> list[RawJob]:
        s = get_settings()
        data = self._get_json(API, params={"Keyword": query or "", "ResultsPerPage": 100, "DatePosted": 30},
                              headers={"Authorization-Key": s.usajobs_api_key, "User-Agent": s.usajobs_email,
                                       "Host": "data.usajobs.gov"})
        out = []
        for item in (data.get("SearchResult") or {}).get("SearchResultItems", []):
            d = item.get("MatchedObjectDescriptor") or {}
            details = d.get("UserArea", {}).get("Details", {})
            pay = (d.get("PositionRemuneration") or [{}])[0]
            schedule = (d.get("PositionSchedule") or [{}])[0].get("Name", "")
            locs = "; ".join(l.get("LocationName", "") for l in d.get("PositionLocation", [])[:3])
            grade = ", ".join(f"{d.get('JobGrade', [{}])[0].get('Code', '')}-{g}" for g in [d.get("LowGrade", "")] if g)
            desc_parts = [details.get("JobSummary", ""), details.get("MajorDuties", ""), details.get("Requirements", "")]
            desc = strip_html(" ".join(p if isinstance(p, str) else " ".join(p) for p in desc_parts if p))
            if grade:
                desc = f"Grade: {grade}. " + desc
            out.append(RawJob(
                external_id=str(d.get("PositionID") or item.get("MatchedObjectId")),
                source=self.name,
                source_name="USAJOBS (federal)",
                company=d.get("OrganizationName") or d.get("DepartmentName") or "US Government",
                title=d.get("PositionTitle", ""),
                location=locs,
                remote=(details.get("TeleworkEligible") is True and "remote" in (details.get("RemoteIndicator", "") or "").lower()) or None,
                description=desc,
                url=d.get("PositionURI", ""),
                posted_at=_dt(d.get("PublicationStartDate")),
                application_deadline=_dt(d.get("ApplicationCloseDate")),
                employment_type=SCHEDULE.get(schedule),
                salary_min=float(pay["MinimumRange"]) if pay.get("MinimumRange") else None,
                salary_max=float(pay["MaximumRange"]) if pay.get("MaximumRange") else None,
                salary_currency="USD" if pay.get("MinimumRange") else None,
                salary_period={"Per Year": "year", "Per Hour": "hour"}.get(pay.get("Description", "")),
            ))
        return out
