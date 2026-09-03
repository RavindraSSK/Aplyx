"""Load config/vertical/<v>/companies.yaml into the companies table.
Idempotent: matches on slug; never touches tier_override / active / verified
or fetch bookkeeping, so re-seeding cannot undo the user's edits."""
import re
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company
from app.vertical.loader import vertical_dir

REQUIRED = ("name", "ats", "ats_slug", "category", "tier_seed", "headcount_band")
ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workday"}
BANDS = {"<500", "500-10k", "10k+"}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_seed(path: str | None = None) -> list[dict]:
    p = Path(path) if path else vertical_dir() / "companies.yaml"
    data = yaml.safe_load(p.read_text()) or {}
    rows = data.get("companies", [])
    seen = set()
    for row in rows:
        missing = [k for k in REQUIRED if k not in row]
        if missing:
            raise ValueError(f"company {row.get('name')!r} missing {missing}")
        if row["ats"] not in ATS:
            raise ValueError(f"company {row['name']!r}: unknown ats {row['ats']!r}")
        if row["tier_seed"] not in (1, 2, 3):
            raise ValueError(f"company {row['name']!r}: tier_seed must be 1/2/3")
        if row["headcount_band"] not in BANDS:
            raise ValueError(f"company {row['name']!r}: headcount_band must be one of {sorted(BANDS)}")
        row["slug"] = row.get("slug") or slugify(row["name"])
        if row["slug"] in seen:
            raise ValueError(f"duplicate company slug {row['slug']!r}")
        seen.add(row["slug"])
    return rows


def seed_companies(db: Session, path: str | None = None) -> dict:
    created = updated = 0
    for row in load_seed(path):
        company = db.scalar(select(Company).where(Company.slug == row["slug"]))
        fields = dict(
            name=row["name"], ats_provider=row["ats"], ats_slug=str(row["ats_slug"]),
            category=row["category"], tier_seed=int(row["tier_seed"]),
            headcount_band=row["headcount_band"], is_public=bool(row.get("public", False)),
            domain=row.get("domain", "") or "", hq_location=row.get("hq", "") or "",
            careers_url=row.get("careers_url", "") or "",
        )
        if company is None:
            db.add(Company(slug=row["slug"], **fields))
            created += 1
        else:
            for k, v in fields.items():
                setattr(company, k, v)
            updated += 1
    db.commit()
    return {"created": created, "updated": updated}
