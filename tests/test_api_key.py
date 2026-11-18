#!/usr/bin/env python3
"""k9x-hil 1.5.0 -- API key for a server-to-server caller (the openai.k9x.ai demo's backend).

Property: X-API-Key authenticates only when it matches HIL_API_KEY, and then acts as exactly one named user
(HIL_API_KEY_USER), whose role still governs decisions. A wrong key is refused; with no key configured, a key
is ignored and the normal sign-in token is still required.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth import create_access_token, get_current_user  # noqa: E402
from backend.models import Base, User  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _attach(conn, _):
        conn.execute("ATTACH DATABASE ':memory:' AS k9hil")

    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(User(name="OpenAI Demo", email="openai-demo@k9x.ai", role="manager", password_hash="x", is_active=True))
    s.add(User(name="Other", email="other@k9x.ai", role="admin", password_hash="x", is_active=True))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("HIL_API_KEY", "k-123")
    monkeypatch.setenv("HIL_API_KEY_USER", "openai-demo@k9x.ai")


def test_matching_key_acts_as_the_named_user(db, key):
    user = get_current_user(authorization=None, x_api_key="k-123", db=db)
    assert user.email == "openai-demo@k9x.ai" and user.role == "manager"


def test_wrong_key_is_refused(db, key):
    with pytest.raises(HTTPException) as exc:
        get_current_user(authorization=None, x_api_key="nope", db=db)
    assert exc.value.status_code == 401


def test_no_key_configured_means_a_key_is_ignored(db, monkeypatch):
    monkeypatch.delenv("HIL_API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:                       # still needs a sign-in token
        get_current_user(authorization=None, x_api_key="k-123", db=db)
    assert exc.value.status_code == 401


def test_key_user_missing_is_refused(db, key, monkeypatch):
    monkeypatch.setenv("HIL_API_KEY_USER", "ghost@k9x.ai")
    with pytest.raises(HTTPException):
        get_current_user(authorization=None, x_api_key="k-123", db=db)


def test_sign_in_tokens_still_work(db, key):
    other = db.query(User).filter(User.email == "other@k9x.ai").first()
    user = get_current_user(authorization="Bearer " + create_access_token(other), x_api_key=None, db=db)
    assert user.email == "other@k9x.ai"
