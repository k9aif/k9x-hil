"""Intake never loses a task (1.4.1): an offset is committed only after its message is
stored, skipped as a duplicate, or dead-lettered.

Before 1.4.1 the consumer auto-committed offsets on a timer and _ingest_message swallowed
every exception, so a task that failed to store (database down) was skipped for good, and a
failed dead-letter publish lost the message as well. In-memory SQLite; Kafka is faked.
"""

import asyncio
import json
import types
from unittest.mock import patch

import pytest
from sqlalchemy.exc import DataError, OperationalError

from backend import kafka_consumer
from backend.models import Application, Project, Queue, Task, TaskAction
from tests.test_decision_authorization import _session

TOPIC = "workflow.hil.das.milestone-a"


def _db_with_queue():
    db = _session()
    p = Project(name="P"); db.add(p); db.commit()
    a = Application(project_id=p.id, name="DAS"); db.add(a); db.commit()
    db.add(Queue(application_id=a.id, name="MS A", topic=TOPIC)); db.commit()
    return db


def _msg(value, topic=TOPIC):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    return types.SimpleNamespace(topic=topic, value=raw)


class _Consumer:
    def __init__(self, msgs):
        self.msgs, self.commits = msgs, 0

    def __aiter__(self):
        async def gen():
            for m in self.msgs:
                yield m
        return gen()

    async def commit(self):
        self.commits += 1


def _run(coro):
    return asyncio.run(coro)


def _patched(db):
    return (patch.object(kafka_consumer, "SessionLocal", lambda: db),
            patch.object(db, "close", lambda: None))


def test_a_stored_task_and_its_created_action_commit_together():
    db = _db_with_queue()
    p1, p2 = _patched(db)
    with p1, p2:
        assert kafka_consumer._ingest_message(TOPIC, {"title": "t", "correlation_id": "c1"}) == "created"
        assert kafka_consumer._ingest_message(TOPIC, {"title": "t", "correlation_id": "c1"}) == "duplicate"
    t = db.query(Task).filter(Task.correlation_id == "c1").one()
    assert db.query(TaskAction).filter(TaskAction.task_id == t.id, TaskAction.action == "created").count() == 1


def test_a_database_failure_is_raised_not_swallowed():
    db = _db_with_queue()
    p1, p2 = _patched(db)
    boom = OperationalError("INSERT", {}, Exception("connection refused"))
    with p1, p2, patch.object(db, "commit", side_effect=boom):
        with pytest.raises(OperationalError):
            kafka_consumer._ingest_message(TOPIC, {"title": "t", "correlation_id": "c2"})


def test_the_offset_is_not_committed_when_a_task_cannot_be_stored():
    db = _db_with_queue()
    consumer = _Consumer([_msg({"title": "a", "correlation_id": "ok-1"}),
                          _msg({"title": "b", "correlation_id": "lost-2"})])
    real_commit = db.commit
    calls = {"n": 0}

    def commit_then_fail():
        calls["n"] += 1
        if calls["n"] > 1:
            raise OperationalError("INSERT", {}, Exception("database down"))
        real_commit()

    p1, p2 = _patched(db)
    with p1, p2, patch.object(db, "commit", side_effect=commit_then_fail):
        with pytest.raises(OperationalError):
            _run(kafka_consumer._consume(consumer))
    assert consumer.commits == 1  # only the stored message; the second is delivered again


def test_a_failed_dead_letter_publish_is_not_committed():
    consumer = _Consumer([_msg(b"not json")])

    async def broken_producer():
        raise ConnectionError("broker down")

    with patch.object(kafka_consumer, "_get_dlq_producer", broken_producer):
        with pytest.raises(ConnectionError):
            _run(kafka_consumer._consume(consumer))
    assert consumer.commits == 0


def test_a_message_the_database_rejects_is_dead_lettered_and_committed():
    db = _db_with_queue()
    sent = []

    async def dlq(topic, raw, reason):
        sent.append((topic, reason))

    consumer = _Consumer([_msg({"title": "t", "correlation_id": "bad"})])
    p1, p2 = _patched(db)
    with p1, p2, patch.object(db, "commit", side_effect=DataError("INSERT", {}, Exception("too long"))), \
            patch.object(kafka_consumer, "_publish_to_dlq", dlq):
        _run(kafka_consumer._consume(consumer))
    assert sent and "rejected by the database" in sent[0][1] and consumer.commits == 1


def test_a_topic_without_a_queue_is_dead_lettered_not_dropped():
    db = _session()
    sent = []

    async def dlq(topic, raw, reason):
        sent.append(reason)

    p1, p2 = _patched(db)
    with p1, p2, patch.object(kafka_consumer, "_publish_to_dlq", dlq):
        _run(kafka_consumer._handle(_msg({"title": "t"}, topic="workflow.hil.unknown")))
    assert sent == ["no Queue registered for this topic"]
