"""
K9X HIL's task contract (1.6.0): the one structure every HIL task has, whoever produces it.

HIL owns this contract. A producer (any K9-AIF application through BaseHILOrchestrator, DAS, the Continuum,
K9X Sentinel, ...) sends a JSON message that conforms to it; HIL publishes it (GET /api/contract/task, and
contract/k9x.hil.task.v1.schema.json in this repository) and checks every incoming message against it.

  * A message that names the contract ("contract": "k9x.hil.task/v1") is checked strictly: anything that does not
    conform is dead-lettered to <topic>.dlq with the reasons, never stored as a broken task.
  * A message without "contract" is a legacy message (producers written before 1.6.0). It is converted to the
    contract (plain-string artifacts become artifact objects, unknown fields are dropped) and stored as before;
    whatever does not conform is logged, never rejected, so existing producers keep working unchanged.

Every task is shown in one standard view built from the contract's fields. What a task is about (an invoice, a
DAS gate, a security finding) lives in ``payload``; ``task_type`` names that kind.
"""

from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator

log = logging.getLogger("k9x-hil.task_contract")

CONTRACT = "k9x.hil.task/v1"
LEGACY = "legacy"
SCHEMA_FILE = Path(__file__).resolve().parent.parent / "contract" / "k9x.hil.task.v1.schema.json"

_ARTIFACT = {
    "type": "object",
    "description": "A document or link the reviewer needs. s3:// objects are fetched by HIL itself (S3/MinIO); "
                   "https:// links open in the browser.",
    "required": ["uri"],
    "additionalProperties": False,
    "properties": {
        "uri": {"type": "string", "maxLength": 2000, "pattern": r"^(s3://[^/\s]+/\S+|https?://\S+)$"},
        "title": {"type": "string", "minLength": 1, "maxLength": 300},
        "media_type": {"type": "string", "maxLength": 100, "pattern": r"^[a-z]+/[a-z0-9.+-]+$"},
        "role": {"enum": ["primary", "supporting"],
                 "description": "primary: the document the decision is about; supporting: context"},
        "pii": {"type": "boolean"},
    },
}

_NULLABLE_STR = lambda n: {"type": ["string", "null"], "maxLength": n}  # noqa: E731

SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://hil.k9x.ai/api/contract/task",
    "title": "K9X HIL task (k9x.hil.task/v1)",
    "description": "The message a producer publishes on a HIL queue topic to create one task.",
    "type": "object",
    "required": ["contract", "title", "correlation_id"],
    "additionalProperties": False,
    "properties": {
        "contract": {"const": CONTRACT},
        "task_type": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9._-]{0,99}$",
                      "description": "what kind of task: e.g. invoice-approval, das-gate, security-finding"},
        "title": {"type": "string", "minLength": 1, "maxLength": 500},
        "description": {"type": ["string", "null"], "maxLength": 20000},
        "correlation_id": {"type": "string", "minLength": 1, "maxLength": 255,
                           "description": "the producer's id for this decision; the reply carries it back"},
        "reply_to": _NULLABLE_STR(255),
        "source_orchestrator": _NULLABLE_STR(255),
        "source_topic": _NULLABLE_STR(255),
        "priority": {"enum": ["low", "medium", "high", "critical"]},
        "assigned_to": _NULLABLE_STR(255),
        "required_role": {"enum": ["worker", "manager", "admin", None],
                          "description": "lowest HIL role allowed to approve or reject"},
        "decision_authority": _NULLABLE_STR(255),
        "require_comment": {"type": "boolean", "description": "approval needs a written justification"},
        "ttl_hours": {"type": ["integer", "null"], "minimum": 1, "maximum": 8760},
        "ttl_action": {"enum": ["reject", "expire", "escalate", None]},
        "pii": {"type": "boolean"},
        "pii_fields": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 100},
        "jira_ticket": _NULLABLE_STR(500),
        "payload": {"type": ["object", "null"], "description": "what the reviewer reads; its fields depend on task_type"},
        "artifacts": {"type": "array", "items": _ARTIFACT, "maxItems": 50},
    },
}

_VALIDATOR = Draft202012Validator(SCHEMA)
_FIELDS = set(SCHEMA["properties"])


class ContractViolation(ValueError):
    """A message that names the contract and does not conform to it."""

    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def errors_of(message: Dict[str, Any]) -> List[str]:
    """Every way ``message`` fails the contract, as 'field: problem' lines (empty when it conforms)."""
    out = []
    for err in sorted(_VALIDATOR.iter_errors(message), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(message)"
        out.append(f"{where}: {err.message}")
    return out


def normalize_artifact(item: Any) -> Optional[Dict[str, Any]]:
    """One artifact in the contract's shape, from the contract's shape or a legacy one: a plain URI string
    ("s3://bucket/key", "https://...") or {name, url, pii}."""
    if isinstance(item, str):
        uri = item.strip()
        return {"uri": uri, "title": _title_of(uri)} if uri else None
    if isinstance(item, dict):
        uri = str(item.get("uri") or item.get("url") or item.get("name") or "").strip()
        if not uri:
            return None
        out: Dict[str, Any] = {"uri": uri, "title": str(item.get("title") or item.get("name") or _title_of(uri))[:300]}
        for key in ("media_type", "role"):
            if item.get(key):
                out[key] = item[key]
        if "pii" in item:
            out["pii"] = bool(item["pii"])
        return out
    return None


def normalize_artifacts(items: Any) -> List[Dict[str, Any]]:
    return [a for a in (normalize_artifact(i) for i in (items or [])) if a]


def media_type_of(artifact: Dict[str, Any], fallback: Optional[str] = None) -> str:
    """The artifact's media type: as the producer stated it, else what object storage reports, else its name's."""
    if artifact.get("media_type"):
        return artifact["media_type"]
    if fallback and fallback != "binary/octet-stream":
        return fallback.split(";")[0].strip()
    guessed, _ = mimetypes.guess_type(artifact.get("uri", ""))
    return guessed or "application/octet-stream"


def _title_of(uri: str) -> str:
    tail = uri.rstrip("/").rsplit("/", 1)[-1]
    return (tail or uri)[:300]


def accept(message: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """The message as stored, and which contract it came under (CONTRACT or LEGACY).

    Names the contract -> must conform (ContractViolation otherwise). No contract -> converted to the contract's
    shape; what still doesn't conform is logged and the message is accepted as before (1.6.0 compatibility)."""
    if "contract" in message:
        errors = errors_of(message)
        if errors:
            raise ContractViolation(errors)
        task = dict(message)
        task["artifacts"] = normalize_artifacts(task.get("artifacts"))
        return task, CONTRACT

    dropped = sorted(k for k in message if k not in _FIELDS)
    task = {k: v for k, v in message.items() if k in _FIELDS}
    task["artifacts"] = normalize_artifacts(message.get("artifacts"))
    check = {**task, "contract": CONTRACT}
    check.setdefault("title", message.get("title") or "untitled")
    check.setdefault("correlation_id", message.get("correlation_id") or "missing")
    problems = errors_of(check)
    if dropped or problems:
        log.warning("[task_contract] legacy message (no 'contract'): accepted; dropped fields %s; "
                    "would not conform to %s: %s", dropped, CONTRACT, problems)
    return task, LEGACY


def write_schema_file() -> Path:
    """The published copy in the repository (kept identical by tests/test_task_contract.py)."""
    SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_FILE.write_text(json.dumps(SCHEMA, indent=2) + "\n", encoding="utf-8")
    return SCHEMA_FILE


if __name__ == "__main__":
    print(write_schema_file())
