from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import Application, Company, Job
from app.ingest import service
from app.ingest.seed import load_seed, seed_companies
from app.sources.base import RawJob
from app.sources.greenhouse import Greenhouse
from tests.conftest import load_fixture


def raw(company="Acme", title="ML Engineer", location="Austin, TX", url=None, source="greenhouse", kind_name=None):
    return RawJob(external_id=url or title, source=source, source_name=kind_name or f"{source} board",
                  company=company, title=title, location=location, description="desc",
                  url=url or f"https://{source}.example/{title.replace(' ', '-').lower()}")


# ── seed ─────────────────────────────────────────────────────────────────────

def test_seed_file_is_valid_and_broad():
    rows = load_seed()
    assert len(rows) >= 250
    assert {r["tier_seed"] for r in rows} == {1, 2, 3}
    assert {r["ats"] for r in rows} == {"greenhouse", "lever", "ashby", "smartrecruiters", "workday"}
    assert len({r["slug"] for r in rows}) == len(rows)


def test_seed_is_idempotent_and_keeps_user_edits(db):
    r1 = seed_companies(db)
    assert r1["created"] >= 250 and r1["updated"] == 0
    c = db.scalar(select(Company).where(Company.slug == "anthropic"))
    c.tier_override, c.active, c.verified = 2, False, True
    db.commit()
    r2 = seed_companies(db)
    assert r2["created"] == 0 and r2["updated"] == r1["created"]
    db.refresh(c)
    assert (c.tier_override, c.active, c.verified) == (2, False, True)


# ── upsert / dedupe / close ──────────────────────────────────────────────────

def test_upsert_creates_updates_and_closes(db, user):
    company = Company(name="Acme", slug="acme", ats_provider="greenhouse", ats_slug="acme")
    db.add(company)
    db.commit()
    c = service.upsert_raw_jobs(db, [raw(url="https://g/1"), raw(title="Data Scientist", url="https://g/2")],
                                user_id=user.id, company=company)
    assert (c["created"], c["updated"]) == (2, 0)
    jobs = db.scalars(select(Job)).all()
    assert all(j.status == "open" and j.first_seen_at and j.company_id == company.id for j in jobs)
    assert db.scalar(select(Application).where(Application.job_id == jobs[0].id)).user_id == user.id

    c2 = service.upsert_raw_jobs(db, [raw(url="https://g/1", title="ML Engineer II")], user_id=user.id, company=company)
    assert (c2["created"], c2["updated"]) == (0, 1)
    closed = service.close_missing(db, company, c2["seen_urls"])
    db.commit()
    assert closed == 1
    j2 = db.scalar(select(Job).where(Job.url == "https://g/2"))
    assert j2.status == "closed" and j2.closed_at is not None
    assert db.scalar(select(Job).where(Job.url == "https://g/1")).title == "ML Engineer II"

    # reappearing job is reopened
    service.upsert_raw_jobs(db, [raw(url="https://g/2", title="Data Scientist")], user_id=user.id, company=company)
    db.commit()
    db.refresh(j2)
    assert j2.status == "open" and j2.closed_at is None


def test_cross_source_dedupe_ats_wins(db, user):
    agg = raw(company="Acme Inc.", title="ML Engineer", location="Austin TX", url="https://adzuna/1",
              source="adzuna", kind_name="Adzuna")
    c = service.upsert_raw_jobs(db, [agg], user_id=user.id, source_kind="aggregator")
    assert c["created"] == 1
    agg_job = db.scalar(select(Job).where(Job.url == "https://adzuna/1"))

    # same posting again from another aggregator -> counted duplicate, not stored
    agg2 = raw(company="ACME", title="ML Engineer", location="Austin, TX", url="https://remotive/1",
               source="remotive", kind_name="Remotive")
    c2 = service.upsert_raw_jobs(db, [agg2], user_id=user.id, source_kind="aggregator")
    assert (c2["created"], c2["duplicates"]) == (0, 1)

    # the ATS copy replaces the aggregator row and inherits the application
    company = Company(name="Acme", slug="acme", ats_provider="greenhouse", ats_slug="acme")
    db.add(company)
    db.commit()
    c3 = service.upsert_raw_jobs(db, [raw(url="https://greenhouse/1")], user_id=user.id, company=company)
    assert c3["created"] == 1
    db.commit()
    db.refresh(agg_job)
    ats_job = db.scalar(select(Job).where(Job.url == "https://greenhouse/1"))
    assert agg_job.status == "duplicate" and agg_job.duplicate_of == ats_job.id
    assert db.scalar(select(Application).where(Application.job_id == ats_job.id)) is not None
    assert db.scalar(select(Job).where(Job.status == "open", Job.dedupe_key == ats_job.dedupe_key)).id == ats_job.id


def test_aggregator_jobs_link_to_seeded_company(db, user):
    db.add(Company(name="Anthropic", slug="anthropic", ats_provider="greenhouse", ats_slug="anthropic"))
    db.commit()
    service.upsert_raw_jobs(db, [raw(company="Anthropic, Inc.", url="https://agg/1", source="remotive")],
                            user_id=user.id, source_kind="aggregator")
    job = db.scalar(select(Job).where(Job.url == "https://agg/1"))
    assert job.company_id == db.scalar(select(Company.id).where(Company.slug == "anthropic"))


def test_expire_stale_aggregator_jobs(db, user):
    service.upsert_raw_jobs(db, [raw(url="https://agg/old", source="remotive")], user_id=user.id, source_kind="aggregator")
    job = db.scalar(select(Job).where(Job.url == "https://agg/old"))
    job.last_seen_at = service.utcnow() - timedelta(days=60)
    db.commit()
    assert service.expire_stale_aggregator_jobs(db) == 1
    db.refresh(job)
    assert job.status == "closed"


# ── company ingestion + runs ─────────────────────────────────────────────────

@pytest.fixture
def three_companies(db):
    for slug in ("acme", "gone", "broken"):
        db.add(Company(name=slug.title(), slug=slug, ats_provider="greenhouse", ats_slug=slug, tier_seed=3))
    db.commit()
    return db.scalars(select(Company).order_by(Company.id)).all()


def _fake_boards(monkeypatch):
    import httpx

    def fake(self, url, **k):
        if "/acme/" in url:
            return load_fixture("greenhouse.json")
        code = 404 if "/gone/" in url else 500
        req = httpx.Request("GET", url)
        raise httpx.HTTPStatusError(str(code), request=req, response=httpx.Response(code, request=req))

    monkeypatch.setattr(Greenhouse, "_get_json", fake)


def test_ingest_company_records_status(db, user, three_companies, monkeypatch):
    _fake_boards(monkeypatch)
    acme, gone, broken = three_companies
    e = service.ingest_company(db, acme, user_id=user.id)
    assert e["status"] == "ok" and e["count"] == 2 and acme.verified is True and acme.last_fetch_status == "ok"
    e = service.ingest_company(db, gone, user_id=user.id)
    assert e["status"] == "not_found" and gone.last_fetch_status == "not_found" and gone.verified is False
    e = service.ingest_company(db, broken, user_id=user.id)
    assert e["status"] == "error" and "HTTP 500" in broken.last_fetch_error


def test_run_progresses_in_slices_and_finishes(db, user, three_companies, monkeypatch):
    _fake_boards(monkeypatch)
    run = service.start_run(db, user_id=user.id)
    assert run.total_companies == 3 and run.status == "running"
    run = service.process_slice(db, run, user_id=user.id, batch_size=2)
    assert run.processed_companies == 2 and run.status == "running"
    run = service.process_slice(db, run, user_id=user.id, batch_size=2)
    assert run.processed_companies == 3 and run.status == "running"  # companies done; finalize next
    run = service.process_slice(db, run, user_id=user.id, batch_size=2)
    assert run.status == "done" and run.finished_at is not None
    assert run.created == 2
    s = service.run_summary(run)
    assert len(s["errors"]) == 2 and any("gone" in e for e in s["errors"])
    # a second run re-fetches everything (last_fetch_at < new started_at)
    run2 = service.run_discovery(db, user_id=user.id, time_budget_seconds=10, batch_size=10)
    assert run2.id != run.id and run2.status == "done" and run2.updated == 2


def test_aggregator_without_keys_is_skipped_not_crashed(db, user, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr("app.ingest.service.get_settings",
                        lambda: get_settings().model_copy(update={"aggregators_enabled": "adzuna"}))
    run = service.run_discovery(db, user_id=user.id, time_budget_seconds=10)
    assert run.status == "done"
    [entry] = [e for e in run.sources if e["target"] == "*"]
    assert entry["source"] == "adzuna" and entry["status"] == "skipped" and "ADZUNA" in entry["error"].upper()


# ── API ──────────────────────────────────────────────────────────────────────

def test_discover_and_runs_api(client, db, three_companies, monkeypatch):
    _fake_boards(monkeypatch)
    first = client.post("/api/discover").json()
    assert first["status"] in ("running", "done") and first["processed_companies"] >= 1
    while first["status"] == "running":
        first = client.post("/api/discover").json()
    assert first["created"] == 2 and len(first["errors"]) == 2
    runs = client.get("/api/runs").json()
    assert runs[0]["id"] == first["id"]
    assert client.get(f"/api/runs/{first['id']}").json()["status"] == "done"
    assert client.get("/api/runs/999").status_code == 404


def test_companies_api(client, db, monkeypatch):
    assert client.post("/api/companies/seed").json()["created"] >= 250
    rows = client.get("/api/companies").json()
    assert any(r["slug"] == "anthropic" and r["tier_seed"] == 1 for r in rows)

    monkeypatch.setattr("app.api.ingest_routes.detect", lambda url: ("lever", "examplecorp"))
    added = client.post("/api/companies", json={"careers_url": "https://example.com/jobs",
                                                  "name": "Example Corp", "tier_seed": 2}).json()
    assert added["ats_provider"] == "lever" and added["ats_slug"] == "examplecorp" and added["tier_seed"] == 2

    monkeypatch.setattr("app.api.ingest_routes.detect", lambda url: None)
    assert client.post("/api/companies", json={"careers_url": "https://nope.example"}).status_code == 422

    patched = client.patch(f"/api/companies/{added['id']}", json={"active": False, "tier_override": 1}).json()
    assert patched["active"] is False and patched["tier_override"] == 1
    assert client.get("/api/companies", params={"status": "never"}).json()
