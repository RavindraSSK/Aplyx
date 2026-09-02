from app.db.models import Application, ApplicationStatus, Job, TailoredResume


def _seed(db, url_suffix, score=None, title="Engineer"):
    job = Job(
        external_id=url_suffix, source="greenhouse", company="Acme",
        title=title, location="NY", remote=False,
        description="desc", url=f"https://x.example/{url_suffix}", score=score,
    )
    db.add(job)
    db.flush()
    app_row = Application(job_id=job.id, status=ApplicationStatus.discovered)
    db.add(app_row)
    db.commit()
    return job, app_row


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_basic_auth_when_password_set(client, monkeypatch):
    from app.config import get_settings

    settings = get_settings().model_copy(update={"dashboard_password": "hunter2"})
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    assert client.get("/jobs").status_code == 401
    ok = client.get("/jobs", auth=("me", "hunter2"))
    assert ok.status_code == 200
    bad = client.get("/jobs", auth=("me", "wrong"))
    assert bad.status_code == 401


def test_dashboard_served_at_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "jobagent" in resp.text


def test_jobs_include_application(client, db):
    _seed(db, "withapp", score=42.0)
    [job] = client.get("/jobs").json()
    assert job["application"]["status"] == "discovered"
    assert job["application"]["resume_version_id"] is None


def test_discover_run_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.run_discovery",
        lambda db: {"created": 3, "updated": 1, "errors": []},
    )
    resp = client.post("/discover/run")
    assert resp.status_code == 200
    assert resp.json() == {"created": 3, "updated": 1, "errors": []}


def test_list_jobs_with_min_score(client, db):
    _seed(db, "low", score=10.0)
    _seed(db, "high", score=90.0)
    _seed(db, "unscored")

    all_jobs = client.get("/jobs").json()
    assert len(all_jobs) == 3
    assert all_jobs[0]["score"] == 90.0  # sorted desc, nulls last

    filtered = client.get("/jobs", params={"min_score": 50}).json()
    assert len(filtered) == 1 and filtered[0]["score"] == 90.0


def test_tailor_endpoint_and_diff(client, db, monkeypatch):
    from app.tailoring.tailor import TailorResult

    job, _ = _seed(db, "t1")
    monkeypatch.setattr(
        "app.tailoring.service.tailor_resume",
        lambda resume, title, desc, client=None: TailorResult(
            content_md="# tailored\n", diff="--- a\n+++ b\n", model="claude-sonnet-4-6"
        ),
    )
    resp = client.post(f"/jobs/{job.id}/tailor")
    assert resp.status_code == 200
    body = resp.json()
    assert body["content_md"] == "# tailored\n"
    assert body["model"] == "claude-sonnet-4-6"

    diff_resp = client.get(f"/jobs/{job.id}/diff")
    assert diff_resp.status_code == 200
    assert diff_resp.text == "--- a\n+++ b\n"


def test_diff_404s(client, db):
    assert client.get("/jobs/999/diff").status_code == 404
    job, _ = _seed(db, "nodiff")
    assert client.get(f"/jobs/{job.id}/diff").status_code == 404


def test_patch_application_status(client, db):
    _, app_row = _seed(db, "s1")
    resp = client.patch(
        f"/applications/{app_row.id}/status",
        json={"status": "matched", "notes": "looks good"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "matched"
    assert resp.json()["notes"] == "looks good"

    bad = client.patch(
        f"/applications/{app_row.id}/status", json={"status": "interview"}
    )
    assert bad.status_code == 409

    missing = client.patch("/applications/999/status", json={"status": "matched"})
    assert missing.status_code == 404
