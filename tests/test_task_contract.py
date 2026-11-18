"""k9x-hil 1.6.0 -- HIL owns its task contract (k9x.hil.task/v1).

Property: every task has one structure, whoever produced it. A message that names the contract must conform, or it is
dead-lettered with the reasons and no task is stored; a legacy message (no "contract": DAS, the Continuum, K9-AIF
before 1.30.0) is converted to the contract and stored exactly as before. Artifacts are a list of objects (S3 and web
links, many per task); each s3:// artifact is served with its own media type (a PDF as a PDF), inline only when it
can't run script. The published schema file is the one HIL enforces.
"""

import asyncio
import json
import types
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend import kafka_consumer, routes, task_contract
from backend.models import Application, Project, Queue, Task
from tests.test_decision_authorization import _session

TOPIC = "hil.requests.openai-ap-payments"

V1 = {
    "contract": "k9x.hil.task/v1", "task_type": "invoice-approval",
    "title": "Approve payment of INV-1042 ($48,500)", "description": "Over $15,000 (AP-07)",
    "correlation_id": "c-1", "reply_to": "hil.replies.openai-ap-payments", "source_orchestrator": "APOrchestrator",
    "priority": "high", "required_role": "manager", "decision_authority": "Accounts payable manager",
    "ttl_hours": 24, "ttl_action": "reject", "pii": False,
    "payload": {"vendor": "Acme Supplies", "amount": 48500},
    "artifacts": [
        {"uri": "s3://openai-ap-invoices/INV-1042.pdf", "title": "Invoice INV-1042", "media_type": "application/pdf",
         "role": "primary"},
        {"uri": "https://openai.k9x.ai/#ap", "title": "The run on openai.k9x.ai", "role": "supporting"},
    ],
}


def _db():
    db = _session()
    p = Project(name="Demo"); db.add(p); db.commit()
    a = Application(project_id=p.id, name="OpenAI Demo Application"); db.add(a); db.commit()
    db.add(Queue(application_id=a.id, name="Invoice Approvals", topic=TOPIC)); db.commit()
    return db


def _ingest(db, message):
    with patch.object(kafka_consumer, "SessionLocal", lambda: db), patch.object(db, "close", lambda: None):
        return kafka_consumer._ingest_message(TOPIC, message)


def test_published_schema_file_is_the_enforced_schema():
    assert json.loads(task_contract.SCHEMA_FILE.read_text()) == task_contract.SCHEMA


def test_contract_endpoint_serves_the_schema():
    assert routes.task_contract()["properties"]["contract"]["const"] == "k9x.hil.task/v1"


def test_a_conforming_message_becomes_a_task_with_every_field():
    db = _db()
    assert _ingest(db, V1) == "created"
    t = db.query(Task).one()
    assert (t.contract, t.task_type, t.required_role, t.decision_authority) == \
        ("k9x.hil.task/v1", "invoice-approval", "manager", "Accounts payable manager")
    assert [a["uri"] for a in t.artifacts] == [a["uri"] for a in V1["artifacts"]]
    assert t.artifacts[0]["media_type"] == "application/pdf" and t.artifacts[1]["role"] == "supporting"


@pytest.mark.parametrize("change, field", [
    ({"artifacts": [{"uri": "ftp://x/y"}]}, "artifacts/0/uri"),
    ({"artifacts": ["s3://bucket/key"]}, "artifacts/0"),          # v1 artifacts are objects
    ({"surprise": 1}, "(message)"),                                # unknown field
    ({"priority": "urgent"}, "priority"),
    ({"required_role": "boss"}, "required_role"),
    ({"correlation_id": ""}, "correlation_id"),
])
def test_a_message_naming_the_contract_that_does_not_conform_is_refused(change, field):
    db = _db()
    with pytest.raises(task_contract.ContractViolation) as exc:
        _ingest(db, {**V1, **change})
    assert any(e.startswith(field) for e in exc.value.errors), exc.value.errors
    assert db.query(Task).count() == 0


def test_a_nonconforming_message_is_dead_lettered_with_the_reason():
    db = _db()
    sent = []

    async def dlq(topic, raw, reason):
        sent.append(reason)

    msg = types.SimpleNamespace(topic=TOPIC, value=json.dumps({**V1, "priority": "urgent"}).encode())
    with patch.object(kafka_consumer, "SessionLocal", lambda: db), patch.object(db, "close", lambda: None), \
            patch.object(kafka_consumer, "_publish_to_dlq", dlq):
        asyncio.run(kafka_consumer._handle(msg))
    assert sent and "does not conform to k9x.hil.task/v1" in sent[0] and "priority" in sent[0]
    assert db.query(Task).count() == 0


@pytest.mark.parametrize("legacy", [
    # DAS gate task (src/k9_dow/gates/hil_gateway.py): s3:// strings, its own extra fields
    {"title": "MDD review", "correlation_id": "JOB-1", "reply_to": "r", "priority": "high",
     "artifacts": ["s3://das-artifacts/JOB-1/mdd.md", ""], "decision_authority": "MDA", "required_role": "manager",
     "payload": {"gate_id": "MDD"}, "ttl_hours": 168, "ttl_action": "reject"},
    # Continuum: a web link as a string
    {"title": "SBB review", "correlation_id": "SBB-7-review", "artifacts": ["https://continuum.k9x.ai/#sbbs"],
     "require_comment": True},
    # K9-AIF BaseHILOrchestrator before 1.30.0: no artifacts, and a value outside the contract
    {"title": "PaymentAgent wants to run pay_invoice", "correlation_id": "c-9", "priority": "normal",
     "payload": {"tool_calls": []}, "reason": "x"},
])
def test_legacy_messages_are_accepted_and_converted(legacy):
    db = _db()
    assert _ingest(db, legacy) == "created"
    t = db.query(Task).one()
    assert t.contract == "legacy" and t.title == legacy["title"]
    assert all(isinstance(a, dict) and a["uri"] for a in t.artifacts)
    assert [a["uri"] for a in t.artifacts] == [a for a in legacy.get("artifacts", []) if a]


def test_old_string_artifacts_already_stored_are_shown_as_objects():
    assert task_contract.normalize_artifacts(["s3://b/k/doc.pdf", {"name": "n", "url": "https://x", "pii": True}]) == [
        {"uri": "s3://b/k/doc.pdf", "title": "doc.pdf"}, {"uri": "https://x", "title": "n", "pii": True}]


# ── serving artifacts ───────────────────────────────────────────────────────

class _Body:
    def __init__(self, data):
        self.data = data

    def read(self, n=-1):
        return self.data


def _task_with(db, artifacts):
    t = Task(queue_id=db.query(Queue).one().id, title="t", artifacts=artifacts)
    db.add(t); db.commit()
    return t.id


def _serve(db, task_id, index, data=b"%PDF-1.7 ...", content_type="application/pdf"):
    s3 = types.SimpleNamespace(get_object=lambda Bucket, Key: {"Body": _Body(data), "ContentLength": len(data),
                                                              "ContentType": content_type})
    with patch.object(routes, "_s3_client", lambda: s3):
        return routes.get_task_artifact(task_id, index, db=db, _=None)


def test_a_pdf_artifact_is_served_inline_as_a_pdf():
    db = _db()
    tid = _task_with(db, V1["artifacts"])
    r = _serve(db, tid, 0)
    assert r.media_type == "application/pdf" and r.headers["content-disposition"].startswith("inline")
    assert "content-security-policy" not in r.headers


def test_each_s3_artifact_is_served_not_only_the_first():
    db = _db()
    tid = _task_with(db, ["s3://b/a.txt", "s3://b/b.png"])
    assert _serve(db, tid, 1, b"\x89PNG", "image/png").media_type == "image/png"


def test_an_html_artifact_is_a_sandboxed_download_never_inline():
    db = _db()
    tid = _task_with(db, ["s3://b/page.html"])
    r = _serve(db, tid, 0, b"<script>alert(1)</script>", "text/html")
    assert r.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in r.headers["content-security-policy"]


def test_web_links_and_missing_artifacts_are_not_served():
    db = _db()
    tid = _task_with(db, V1["artifacts"])
    with pytest.raises(HTTPException) as web:
        _serve(db, tid, 1)
    with pytest.raises(HTTPException) as missing:
        _serve(db, tid, 5)
    assert (web.value.status_code, missing.value.status_code) == (400, 404)
