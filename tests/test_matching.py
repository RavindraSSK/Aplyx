from sqlalchemy import select

from app.db.models import Application, ApplicationStatus, Job, User
from app.matching.embeddings import similarity
from app.matching.rules import apply_rules
from app.matching.scorer import score_job
from app.matching.service import run_matching

RULES = {
    "required_title_keywords": ["engineer", "developer"],
    "excluded_keywords": ["senior staff", "10+ years", "clearance"],
    "locations": ["san francisco", "new york"],
    "must_mention_sponsorship": False,
}

RESUME = "Python engineer. FastAPI, SQLAlchemy, PostgreSQL, Docker, AWS."


def test_similarity_bounds_and_signal():
    close = similarity(RESUME, "We need a Python engineer with FastAPI and PostgreSQL.")
    far = similarity(RESUME, "Retail store manager for weekend shifts, cash register.")
    assert 0.0 <= far < close <= 1.0


def test_rules_excluded_keyword_fails():
    r = apply_rules("Software Engineer", "requires TS/SCI clearance", "New York", False, RULES)
    assert not r.passed
    assert any("clearance" in reason for reason in r.reasons)


def test_rules_required_title_keyword():
    r = apply_rules("Account Executive", "sell software", "New York", False, RULES)
    assert not r.passed
    ok = apply_rules("Backend Developer", "build software", "New York", False, RULES)
    assert ok.passed and ok.bonus > 0


def test_rules_location_gate_and_remote_bypass():
    onsite_bad = apply_rules("Engineer", "code", "Chicago, IL", False, RULES)
    assert not onsite_bad.passed
    remote_ok = apply_rules("Engineer", "code", "Chicago, IL", True, RULES)
    assert remote_ok.passed


def test_rules_sponsorship_required():
    rules = dict(RULES, must_mention_sponsorship=True)
    missing = apply_rules("Engineer", "great python job", "New York", False, rules)
    assert not missing.passed
    present = apply_rules("Engineer", "we offer visa sponsorship", "New York", False, rules)
    assert present.passed


def test_score_job_range_and_reasons():
    good = score_job(RESUME, "Python Engineer", "FastAPI PostgreSQL Docker AWS python engineer", "New York", False, RULES)
    assert 0 < good.score <= 100
    assert any("similarity" in r for r in good.reasons)

    blocked = score_job(RESUME, "Python Engineer", "requires clearance", "New York", False, RULES)
    assert blocked.score == 0
    assert any("excluded keyword" in r for r in blocked.reasons)


def _seed_job(db, **kw):
    defaults = dict(
        external_id="1", source="greenhouse", company="Acme",
        title="Python Engineer", location="New York", remote=False,
        description="FastAPI and PostgreSQL services", url="https://x.example/1",
    )
    defaults.update(kw)
    job = Job(**defaults)
    db.add(job)
    db.flush()
    db.add(Application(job_id=job.id, user_id=db.scalar(select(User.id)), status=ApplicationStatus.discovered))
    db.commit()
    return job


def test_run_matching_scores_and_advances_status(db, user):
    job = _seed_job(db)
    result = run_matching(db, resume_text=RESUME, targets={"matching": RULES})
    assert result["scored"] == 1 and result["resume_source"] == "explicit"
    db.refresh(job)
    assert job.score is not None and job.score > 0
    assert job.score_reasons
    assert job.application.status == ApplicationStatus.matched


def test_run_matching_skips_scored_unless_rescore_all(db, user):
    job = _seed_job(db)
    job.score = 55.0
    db.commit()
    assert run_matching(db, resume_text=RESUME, targets={"matching": RULES})["scored"] == 0
    assert run_matching(
        db, resume_text=RESUME, targets={"matching": RULES}, rescore_all=True
    )["scored"] == 1


def test_run_matching_uses_uploaded_profile_when_present(db, user, monkeypatch):
    from app.profile.service import ingest_resume
    from tests.test_profile import FakeClient

    ingest_resume(db, user, b"Jane Doe\nSkills: Python, PyTorch, FastAPI, PostgreSQL", "r.txt", client=FakeClient())
    job = _seed_job(db, title="Machine Learning Engineer", description="PyTorch FastAPI PostgreSQL python")
    monkeypatch.setattr("app.matching.service.load_resume", lambda *a: (_ for _ in ()).throw(AssertionError("must not read resume.md")))
    result = run_matching(db, targets={"matching": {}}, user_id=user.id)
    assert result["resume_source"] == "profile"
    db.refresh(job)
    assert job.score > 0


def test_run_matching_falls_back_to_resume_file_without_profile(db, user, monkeypatch):
    _seed_job(db)
    monkeypatch.setattr("app.matching.service.load_resume", lambda *a: RESUME)
    result = run_matching(db, targets={"matching": RULES}, user_id=user.id)
    assert result["resume_source"] == "resume.md"


def test_empty_required_keywords_use_vertical_role_families():
    from app.matching.service import effective_rules

    rules = effective_rules({"required_title_keywords": []})
    assert "machine learning engineer" in rules["required_title_keywords"]
    assert "data scientist" in rules["required_title_keywords"]
    # explicit lists are kept as-is
    assert effective_rules({"required_title_keywords": ["x"]})["required_title_keywords"] == ["x"]


def test_long_keyword_list_gets_short_reason():
    from app.matching.service import effective_rules

    rules = effective_rules({})
    r = apply_rules("Account Executive", "sell", "NY", False, rules)
    assert not r.passed
    assert "target-role titles" in r.reasons[0]
