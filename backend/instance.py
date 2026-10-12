"""A dedicated K9X HIL instance for one project (HIL_INSTANCE).

The public hil.k9x.ai serves every example application; the internal one serves
K9X Sentinel. HIL_INSTANCE=<name> runs a third kind: one HIL for one project or
application, described by instances/<name>.yaml (or an absolute path):

    id, branding (name, subtitle, accent, about, logo_text),
    demo_login (bool: show and seed the demo/demo login),
    projects -> applications -> queues (name, description, topic, ttl_hours, ttl_action),
    jobs: a Jobs view grouping the instance's tasks by correlation_id (the calling
          system's job id), one column and one tab per listed stage queue.

Its own POSTGRES_SCHEMA, consumer group, port and JWT secret come from its .env
(ubuntu_instance/build-run.sh). The branding in the file is the default; an
instance admin can change it in Administration -> Branding (stored in the schema).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

BRANDING_KEYS = ("name", "subtitle", "accent", "about", "logo_text")
BRANDING_LIMITS = {"name": 60, "subtitle": 120, "accent": 7, "about": 1200, "logo_text": 12}


class InstanceError(ValueError):
    pass


def instance_name() -> str:
    return os.getenv("HIL_INSTANCE", "").strip()


def _path(name: str) -> Path:
    p = Path(name)
    if p.suffix in (".yaml", ".yml") and p.is_absolute():
        return p
    if not _ID.match(name):
        raise InstanceError(f"HIL_INSTANCE={name!r}: use a short name (instances/<name>.yaml) or an absolute .yaml path")
    return _ROOT / "instances" / f"{name}.yaml"


def clean_branding(raw: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in BRANDING_KEYS:
        if key not in raw or raw[key] is None:
            continue
        val = str(raw[key]).strip()[:BRANDING_LIMITS[key]]
        if key == "accent" and val and not _COLOUR.match(val):
            raise InstanceError("branding.accent must be a colour like #2563eb")
        out[key] = val
    return out


def validate(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not _ID.match(str(cfg.get("id", ""))):
        raise InstanceError("instance id: lowercase letters, digits, - or _")
    cfg["branding"] = clean_branding(cfg.get("branding") or {})
    cfg.setdefault("demo_login", False)
    topics: List[str] = []
    for p in cfg.get("projects") or []:
        if not p.get("name"):
            raise InstanceError("every project needs a name")
        for a in p.get("applications") or []:
            if not a.get("name"):
                raise InstanceError(f"project {p['name']}: every application needs a name")
            for q in a.get("queues") or []:
                if not q.get("name") or not q.get("topic"):
                    raise InstanceError(f"application {a['name']}: every queue needs a name and a topic")
                topics.append(q["topic"])
    if not topics:
        raise InstanceError("an instance needs at least one queue")
    if len(topics) != len(set(topics)):
        raise InstanceError("queue topics must be unique")
    jobs = cfg.get("jobs") or {}
    for st in jobs.get("stages") or []:
        if st.get("topic") not in topics:
            raise InstanceError(f"jobs stage {st.get('label')!r}: topic {st.get('topic')!r} is not one of the instance's queues")
    return cfg


@lru_cache(maxsize=1)
def load_instance() -> Optional[Dict[str, Any]]:
    name = instance_name()
    if not name:
        return None
    path = _path(name)
    if not path.exists():
        raise InstanceError(f"HIL_INSTANCE={name!r}: {path} not found")
    with open(path, encoding="utf-8") as f:
        return validate(yaml.safe_load(f) or {})


def instance_topics() -> List[str]:
    cfg = load_instance() or {}
    return [q["topic"] for p in cfg.get("projects") or [] for a in p.get("applications") or []
            for q in a.get("queues") or []]
