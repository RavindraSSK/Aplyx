import json
import os
from pathlib import Path

os.environ.setdefault("AGGREGATORS_ENABLED", "")  # never hit real aggregator APIs in tests
os.environ.setdefault("INGEST_BATCH_SIZE", "8")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import AuthProvider
from app.db.models import Base, User
from app.db.session import get_db
from app.db.tenancy import current_user_id
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def user(db):
    u = User(email="test@example.com", display_name="Test")
    db.add(u)
    db.commit()
    token = current_user_id.set(u.id)
    try:
        yield u
    finally:
        current_user_id.reset(token)


class StaticAuthProvider(AuthProvider):
    """Test double: every request is `user_id`."""

    def __init__(self, user_id: int):
        self.user_id = user_id

    def authenticate(self, request):
        return self.user_id

    def challenge_headers(self):
        return {}


@pytest.fixture
def client(db, user, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr("app.main.get_auth_provider", lambda: StaticAuthProvider(user.id))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
