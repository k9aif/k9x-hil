"""HIL_PROFILE: public is the default; anything but "internal" is public."""

import importlib

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

