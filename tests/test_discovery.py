from datetime import timezone

from sqlalchemy import select

from app.db.models import Application, ApplicationStatus, Job
from app.discovery.ashby import AshbyFetcher
from app.discovery.base import strip_html
from app.discovery.greenhouse import GreenhouseFetcher
from app.discovery.lever import LeverFetcher
from app.discovery.service import run_discovery, upsert_job
from tests.conftest import load_fixture


def _patch_json(monkeypatch, fetcher_cls, fixture_name):
    monkeypatch.setattr(
        fetcher_cls, "_get_json", lambda self, url: load_fixture(fixture_name)
    )


def test_strip_html_unescapes_and_removes_tags():
    assert strip_html("&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;") == "Hello world"
    assert strip_html("<div>plain</div>") == "plain"


def test_greenhouse_normalization(monkeypatch):
    _patch_json(monkeypatch, GreenhouseFetcher, "greenhouse.json")
    jobs = GreenhouseFetcher().fetch("acme", "Acme")
    assert len(jobs) == 2
    j = jobs[0]
    assert j.source == "greenhouse"
    assert j.company == "Acme"
    assert j.title == "Software Engineer, Backend"
    assert j.location == "San Francisco, CA"
    assert j.remote is False
    assert "Python" in j.description and "<b>" not in j.description
    assert j.url.endswith("/4011001")
    assert j.posted_at is not None
    assert jobs[1].remote is True  # "Remote - US" location


def test_lever_normalization(monkeypatch):
    _patch_json(monkeypatch, LeverFetcher, "lever.json")
    jobs = LeverFetcher().fetch("globex", "Globex")
    assert len(jobs) == 2
    j = jobs[0]
    assert j.source == "lever"
    assert j.title == "Backend Developer"
    assert j.remote is True  # workplaceType: remote
    assert j.posted_at.tzinfo == timezone.utc
    assert "SQLAlchemy" in j.description
    assert jobs[1].remote is False


def test_ashby_normalization(monkeypatch):
    _patch_json(monkeypatch, AshbyFetcher, "ashby.json")
    jobs = AshbyFetcher().fetch("initech", "Initech")
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source == "ashby"
    assert j.title == "Full Stack Engineer"
    assert j.remote is False
    assert j.url == "https://jobs.ashbyhq.com/initech/f47ac10b-0001"
    assert "sponsorship" in j.description


def test_run_discovery_upserts_and_dedupes(db, monkeypatch):
    _patch_json(monkeypatch, GreenhouseFetcher, "greenhouse.json")
    _patch_json(monkeypatch, LeverFetcher, "lever.json")
    _patch_json(monkeypatch, AshbyFetcher, "ashby.json")
    targets = {
        "companies": [
            {"name": "Acme", "source": "greenhouse", "slug": "acme"},
            {"name": "Globex", "source": "lever", "slug": "globex"},
            {"name": "Initech", "source": "ashby", "slug": "initech"},
        ]
    }

    first = run_discovery(db, targets)
    assert first == {"created": 5, "updated": 0, "errors": []}
    assert db.scalar(select(Job).where(Job.title == "Backend Developer")) is not None
    # every new job gets a 'discovered' application
    apps = db.scalars(select(Application)).all()
    assert len(apps) == 5
    assert all(a.status == ApplicationStatus.discovered for a in apps)

    second = run_discovery(db, targets)
    assert second == {"created": 0, "updated": 5, "errors": []}
    assert len(db.scalars(select(Job)).all()) == 5


def test_run_discovery_survives_one_bad_board(db, monkeypatch):
    _patch_json(monkeypatch, GreenhouseFetcher, "greenhouse.json")

    def boom(self, url):
        raise RuntimeError("board down")

    monkeypatch.setattr(LeverFetcher, "_get_json", boom)
    targets = {
        "companies": [
            {"name": "Globex", "source": "lever", "slug": "globex"},
            {"name": "Acme", "source": "greenhouse", "slug": "acme"},
        ]
    }
    summary = run_discovery(db, targets)
    assert summary["created"] == 2
    assert len(summary["errors"]) == 1 and "Globex" in summary["errors"][0]


def test_upsert_updates_fields_in_place(db, monkeypatch):
    _patch_json(monkeypatch, GreenhouseFetcher, "greenhouse.json")
    [j1, _] = GreenhouseFetcher().fetch("acme", "Acme")
    job, created = upsert_job(db, j1)
    assert created is True
    j1.title = "Software Engineer II, Backend"
    job2, created2 = upsert_job(db, j1)
    assert created2 is False
    assert job2.id == job.id
    assert job2.title == "Software Engineer II, Backend"
