from types import SimpleNamespace

from app.auth import BasicAuthProvider
from app.db.tenancy import as_user, current_user_id
from app.llm.metering import estimate_cost


def _req(auth_header: str | None):
    headers = {"authorization": auth_header} if auth_header else {}
    return SimpleNamespace(headers=headers)


def test_basic_provider_open_when_no_password(monkeypatch):
    from app.config import get_settings

    settings = get_settings().model_copy(update={"dashboard_password": ""})
    monkeypatch.setattr("app.auth.get_settings", lambda: settings)
    p = BasicAuthProvider()
    p._owner_id = 7
    assert p.authenticate(_req(None)) == 7


def test_basic_provider_checks_password(monkeypatch):
    import base64

    from app.config import get_settings

    settings = get_settings().model_copy(update={"dashboard_password": "hunter2"})
    monkeypatch.setattr("app.auth.get_settings", lambda: settings)
    p = BasicAuthProvider()
    p._owner_id = 7
    assert p.authenticate(_req(None)) is None
    assert p.authenticate(_req("Basic " + base64.b64encode(b"me:wrong").decode())) is None
    assert p.authenticate(_req("Basic " + base64.b64encode(b"me:hunter2").decode())) == 7
    assert "WWW-Authenticate" in p.challenge_headers()


def test_api_returns_401_when_provider_rejects(client, monkeypatch):
    from tests.conftest import StaticAuthProvider

    class Reject(StaticAuthProvider):
        def authenticate(self, request):
            return None

    monkeypatch.setattr("app.main.get_auth_provider", lambda: Reject(0))
    assert client.get("/jobs").status_code == 401


def test_as_user_context_scopes_tenant():
    assert current_user_id.get() is None
    with as_user(42):
        assert current_user_id.get() == 42
    assert current_user_id.get() is None


def test_estimate_cost_known_and_unknown_models():
    assert estimate_cost("claude-sonnet-4-6", 1_000_000, 0) == 3.0
    assert estimate_cost("claude-sonnet-4-6", 0, 1_000_000) == 15.0
    assert estimate_cost("mystery-model", 1000, 1000) == 0.0
