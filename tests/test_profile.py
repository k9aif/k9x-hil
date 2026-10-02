"""Public K9X HIL is read-only for every role; only the internal one decides."""

import asyncio
import importlib

import pytest
from fastapi import HTTPException

from backend import profile


def _reload(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("HIL_PROFILE", raising=False)
    else:
        monkeypatch.setenv("HIL_PROFILE", value)
    importlib.reload(profile)
    return profile


def test_public_is_the_default_and_read_only(monkeypatch):
    assert _reload(monkeypatch, None).READ_ONLY is True
    assert _reload(monkeypatch, "public").READ_ONLY is True
    assert _reload(monkeypatch, "anything-else").READ_ONLY is True   # fail closed
    assert _reload(monkeypatch, " Internal ").READ_ONLY is False
    _reload(monkeypatch, None)


def test_public_refuses_task_actions_even_for_admin(monkeypatch):
    from backend import routes
    monkeypatch.setattr(routes, "READ_ONLY", True)
    req = routes.TaskActionReq(action="complete", actor="admin@k9x.ai")
    with pytest.raises(HTTPException) as e:
        routes.perform_action(1, req, db=None, _=object())   # never touches the DB
    assert e.value.status_code == 403

