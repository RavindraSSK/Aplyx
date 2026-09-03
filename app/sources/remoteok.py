"""RemoteOK public JSON feed (no key; requires attribution + link back)."""
from datetime import datetime, timezone

from app.discovery.base import strip_html
from app.sources.base import RawJob, SourceAdapter, register

API = "https://remoteok.com/api"


@register
class RemoteOK(SourceAdapter):
    name = "remoteok"
    kind = "aggregator"
    rate_limit_seconds = 5.0

    def fetch(self, slug=None, company=None, since=None, query=None) -> list[RawJob]:
        data = self._get_json(API, params={"tag": query} if query else None)
        out = []
        for j in data:
            if not isinstance(j, dict) or "id" not in j or "position" not in j:
                continue  # first element is a legal notice
            epoch = j.get("epoch")
            out.append(RawJob(
                external_id=str(j["id"]),
                source=self.name,
                source_name="RemoteOK",
                company=j.get("company", ""),
                title=j.get("position", ""),
                location=j.get("location", "") or "Remote",
                remote=True,
                description=strip_html(j.get("description", "")),
                url=j.get("url", ""),
                posted_at=datetime.fromtimestamp(int(epoch), tz=timezone.utc) if epoch else None,
                salary_min=float(j["salary_min"]) if j.get("salary_min") else None,
                salary_max=float(j["salary_max"]) if j.get("salary_max") else None,
                salary_currency="USD" if j.get("salary_min") else None,
                salary_period="year" if j.get("salary_min") else None,
            ))
        return out
