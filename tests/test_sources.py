"""Adapters against recorded fixtures - no network."""
from datetime import timezone

from app.sources import adzuna, remoteok, remotive, smartrecruiters, usajobs, workday
from app.sources.ashby import Ashby
from app.sources.detect import detect, detect_from_url
from app.sources.greenhouse import Greenhouse
from app.sources.lever import Lever
from app.sources.normalize import dedupe_key, normalize_company, to_job_columns
from tests.conftest import load_fixture


def _json(monkeypatch, cls, mapping):
    """mapping: substring of url -> fixture name; both GET and POST."""
    def fake(self, url, *a, **k):
        for key, fixture in mapping.items():
            if key in url:
                return load_fixture(fixture)
        raise AssertionError(f"unexpected url {url}")
    monkeypatch.setattr(cls, "_get_json", fake)
    monkeypatch.setattr(cls, "_post_json", lambda self, url, payload, **k: fake(self, url))
    monkeypatch.setattr(cls, "rate_limit_seconds", 0)


def test_greenhouse_lever_ashby_via_new_adapters(monkeypatch):
    _json(monkeypatch, Greenhouse, {"greenhouse": "greenhouse.json"})
    _json(monkeypatch, Lever, {"lever": "lever.json"})
    _json(monkeypatch, Ashby, {"ashby": "ashby.json"})
    g = Greenhouse().fetch("acme", "Acme")
    assert g[0].source_name == "Greenhouse board: acme" and g[0].company == "Acme"
    l = Lever().fetch("globex", "Globex")
    assert l[0].remote is True and l[1].remote is None  # None -> inferred later
    a = Ashby().fetch("initech", "Initech")
    assert a[0].url.endswith("f47ac10b-0001")


def test_smartrecruiters_adapter(monkeypatch):
    _json(monkeypatch, smartrecruiters.SmartRecruiters,
          {"/postings/744": "smartrecruiters_detail.json", "/postings?": "smartrecruiters_list.json"})
    jobs = smartrecruiters.SmartRecruiters().fetch("BoschGroup", "Bosch")
    assert len(jobs) == 2
    j = jobs[0]
    assert j.title == "Machine Learning Engineer" and j.location == "Sunnyvale, CA, us"
    assert "Build ML models" in j.description and "<b>" not in j.description
    assert j.employment_type == "full_time" and jobs[1].employment_type == "internship"
    assert jobs[1].remote is True
    assert j.url == "https://jobs.smartrecruiters.com/BoschGroup/744000001"
    assert j.posted_at.tzinfo is not None


def test_workday_adapter(monkeypatch):
    _json(monkeypatch, workday.Workday, {"/job/": "workday_detail.json", "/jobs": "workday_list.json"})
    jobs = workday.Workday().fetch("nvidia.wd5/NVIDIAExternalCareerSite", "NVIDIA")
    assert len(jobs) == 2
    j = jobs[0]
    assert j.external_id == "JR1990001"
    assert j.url == ("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"
                     "/job/US-CA-Santa-Clara/Senior-Deep-Learning-Engineer_JR1990001")
    assert "GPUs" in j.description
    assert j.posted_at is not None and j.posted_at.tzinfo == timezone.utc
    assert workday.parse_slug("nvidia.wd5/NVIDIAExternalCareerSite") == ("nvidia", "wd5", "NVIDIAExternalCareerSite")


def test_adzuna_adapter(monkeypatch):
    _json(monkeypatch, adzuna.Adzuna, {"adzuna": "adzuna.json"})
    [j] = adzuna.Adzuna().fetch(query="machine learning engineer")
    assert j.company == "Acme" and j.salary_min == 120000 and j.salary_period == "year"
    assert j.employment_type == "full_time" and j.source_name == "Adzuna"


def test_usajobs_adapter(monkeypatch):
    _json(monkeypatch, usajobs.USAJobs, {"usajobs": "usajobs.json"})
    [j] = usajobs.USAJobs().fetch(query="data scientist")
    assert j.company == "National Institutes of Health"
    assert j.application_deadline is not None and j.application_deadline.month == 9
    assert j.salary_min == 99200.0 and j.employment_type == "full_time"
    assert "Grade: GS-12" in j.description and "citizenship" in j.description
    assert j.url == "https://www.usajobs.gov/job/800001"


def test_remotive_and_remoteok_adapters(monkeypatch):
    _json(monkeypatch, remotive.Remotive, {"remotive": "remotive.json"})
    _json(monkeypatch, remoteok.RemoteOK, {"remoteok": "remoteok.json"})
    [r] = remotive.Remotive().fetch(query="ml")
    assert r.remote is True and r.employment_type == "full_time" and "PyTorch" in r.description
    [o] = remoteok.RemoteOK().fetch()  # legal notice element skipped
    assert o.title == "Applied Scientist" and o.salary_max == 140000 and o.posted_at is not None


def test_missing_keys_mark_aggregators_unavailable():
    assert adzuna.Adzuna.available() is False
    assert usajobs.USAJobs.available() is False
    assert remotive.Remotive.available() is True  # no key needed


def test_normalize_and_dedupe_key():
    assert normalize_company("Acme, Inc.") == normalize_company("ACME Inc") == "acme"
    k1 = dedupe_key("Acme Inc.", "Machine Learning Engineer", "Austin, TX")
    k2 = dedupe_key("ACME", "Machine  Learning Engineer", "Austin TX")
    assert k1 == k2
    assert dedupe_key("Acme", "ML Engineer", "Austin, TX") != k1


def test_to_job_columns_infers_remote_and_strips_html():
    from app.sources.base import RawJob

    cols = to_job_columns(RawJob(external_id="1", source="x", source_name="X", company="A",
                                 title="Engineer", location="Remote - US", description="<p>hi</p>", url="https://u"))
    assert cols["remote"] is True and cols["description"] == "hi" and len(cols["dedupe_key"]) == 40


def test_detect_from_url_patterns():
    assert detect_from_url("https://boards.greenhouse.io/anthropic/jobs/123") == ("greenhouse", "anthropic")
    assert detect_from_url("https://job-boards.greenhouse.io/stripe") == ("greenhouse", "stripe")
    assert detect_from_url("https://jobs.lever.co/palantir/abc") == ("lever", "palantir")
    assert detect_from_url("https://jobs.ashbyhq.com/openai") == ("ashby", "openai")
    assert detect_from_url("https://jobs.smartrecruiters.com/BoschGroup/1") == ("smartrecruiters", "BoschGroup")
    assert detect_from_url("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/x") == \
        ("workday", "nvidia.wd5/NVIDIAExternalCareerSite")
    assert detect_from_url("https://example.com/careers") is None


def test_detect_scans_careers_page_html():
    import httpx

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text='<a href="https://boards.greenhouse.io/examplecorp">Open roles</a>')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert detect("https://example.com/careers", client=client) == ("greenhouse", "examplecorp")

    def blocked(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        return httpx.Response(200, text='<a href="https://jobs.lever.co/x">x</a>')

    assert detect("https://blocked.example/careers", client=httpx.Client(transport=httpx.MockTransport(blocked))) is None
