"""HIL_PROFILE: public is the default; anything but "internal" is public."""

import importlib
import os

from backend import profile


def _reload(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("HIL_PROFILE", raising=False)
    else:
        monkeypatch.setenv("HIL_PROFILE", value)
    importlib.reload(profile)
    return profile


def test_profile_values(monkeypatch):
    assert _reload(monkeypatch, None).PROFILE == "public"
    assert _reload(monkeypatch, " Internal ").PROFILE == "internal"
    _reload(monkeypatch, None)



def test_meta_endpoint(monkeypatch):
    """/api/meta drives the sign-in page (demo logins, badge); it must not fail."""
    monkeypatch.setenv("JWT_SECRET_KEY", os.environ.get("JWT_SECRET_KEY", "test-only"))
    import main
    monkeypatch.setenv("HIL_BADGE", "Internal")
    assert main.meta()["badge"] == "Internal"
    monkeypatch.delenv("HIL_BADGE")
    assert main.meta()["badge"] == ""
    assert main.meta()["profile"] in ("public", "internal")
