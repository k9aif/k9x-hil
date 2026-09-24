#!/usr/bin/env python3
"""k9x-hil -- proves apply_task_action() actually publishes a terminal
decision to reply_to, closing the gap k9-aif-framework's HIL round trip
depends on (see backend/hil_reply.py's own docstring for the full context).

Real in-memory SQLite session against the actual Task/TaskAction models,
not a hand-mocked db double -- only the Kafka producer is replaced (no
broker available in this environment), matching db_test.py's own
"run directly, no test framework needed" convention already established
in this repo rather than introducing pytest as a new dependency for one
file.

Run directly:

    python3 tests/test_task_actions.py

Exits 0 if every check passes, non-zero (with a printed reason) otherwise.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, Task
from backend.task_actions import apply_task_action, TaskConflictError

failures = []


def _aware(dt):
    """SQLite strips tzinfo on round-trip (confirmed empirically running
    this file) -- same normalization apply_task_action() itself already
    does defensively before comparing due_date in production code."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)
        failures.append(name)


def _make_session():
    # SQLite can't create schema-qualified tables the way the real
    # Postgres models declare (__table_args__ = {"schema": "k9hil"}) --
    # strip the schema for this in-memory run only, same class of
    # adaptation any SQLite-backed test of Postgres-schema'd models needs.
    for table in Base.metadata.tables.values():
        table.schema = None
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_complete_publishes_to_reply_to():
    db = _make_session()
    task = Task(
        title="Review ALT-1001", status="pending",
        reply_to="hil.replies.fraudorchestrator", correlation_id="corr-123",
    )
    db.add(task)
    db.commit()

    with patch("backend.task_actions.enqueue_hil_reply") as mock_enqueue, \
         patch("backend.task_actions.attempt_publish"):
        status = apply_task_action(db, task, "complete", "reviewer@bank.example",
                                    comment="approved", result={"decision": "approve"})

    check("status transitions to completed", status == "completed", status)
    check("enqueue_hil_reply called once", mock_enqueue.call_count == 1,
          f"called {mock_enqueue.call_count} times")
    if mock_enqueue.call_count == 1:
        kwargs = mock_enqueue.call_args.kwargs
        check("correct correlation_id", kwargs["correlation_id"] == "corr-123", kwargs)
        check("correct reply_to", kwargs["reply_to"] == "hil.replies.fraudorchestrator", kwargs)
        check("correct action", kwargs["action"] == "complete", kwargs)
        check("correct actor", kwargs["actor"] == "reviewer@bank.example", kwargs)


def test_claim_does_not_publish():
    """claim/start aren't decisions -- nothing for a waiting orchestrator
    to resume on yet."""
    db = _make_session()
    task = Task(title="Review ALT-1002", status="pending",
                reply_to="hil.replies.x", correlation_id="corr-456")
    db.add(task)
    db.commit()

    with patch("backend.task_actions.enqueue_hil_reply") as mock_enqueue:
        apply_task_action(db, task, "claim", "reviewer@bank.example")

    check("claim does not enqueue a reply", mock_enqueue.call_count == 0,
          f"called {mock_enqueue.call_count} times")


def test_escalate_does_not_publish():
    """escalate stays in-flight -- the eventual complete/reject/expire on
    this same task is what publishes, not the escalation itself."""
    db = _make_session()
    task = Task(title="Review ALT-1003", status="pending",
                reply_to="hil.replies.x", correlation_id="corr-789")
    db.add(task)
    db.commit()

    with patch("backend.task_actions.enqueue_hil_reply") as mock_enqueue:
        apply_task_action(db, task, "escalate", "reviewer@bank.example")

    check("escalate does not enqueue a reply", mock_enqueue.call_count == 0,
          f"called {mock_enqueue.call_count} times")


def test_escalate_extends_due_date_5_days_from_now_when_overdue():
    """The common escalation case -- a task past (or with no) due_date
    gets a full, real 5 days, not a few leftover hours."""
    db = _make_session()
    past_due = datetime.now(timezone.utc) - timedelta(days=2)
    task = Task(title="Review ALT-2001", status="pending",
                reply_to="hil.replies.x", correlation_id="corr-esc-1",
                due_date=past_due)
    db.add(task)
    db.commit()

    before = datetime.now(timezone.utc)
    apply_task_action(db, task, "escalate", "reviewer@bank.example")
    after = datetime.now(timezone.utc)

    db.refresh(task)
    due = _aware(task.due_date)
    check("due_date extended to ~now+5 days, not past_due+5 days",
          before + timedelta(days=5) <= due <= after + timedelta(days=5),
          f"due_date={due}")


def test_escalate_extends_from_existing_due_date_when_still_future():
    """A task escalated well before its original deadline gets 5 more
    days added to that deadline, not reset back down to now+5."""
    db = _make_session()
    future_due = datetime.now(timezone.utc) + timedelta(days=10)
    task = Task(title="Review ALT-2002", status="pending",
                reply_to="hil.replies.x", correlation_id="corr-esc-2",
                due_date=future_due)
    db.add(task)
    db.commit()

    apply_task_action(db, task, "escalate", "reviewer@bank.example")

    db.refresh(task)
    due = _aware(task.due_date)
    expected = future_due + timedelta(days=5)
    check("due_date extended from the existing future due_date",
          abs((due - expected).total_seconds()) < 5,
          f"due_date={due}, expected~={expected}")


def test_escalate_handles_timezone_naive_due_date_without_raising():
    """due_date may round-trip timezone-naive depending on the DB driver
    -- must not raise a naive/aware TypeError."""
    db = _make_session()
    naive_future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    task = Task(title="Review ALT-2003", status="pending", due_date=naive_future)
    db.add(task)
    db.commit()

    raised = False
    try:
        apply_task_action(db, task, "escalate", "reviewer@bank.example")
    except TypeError:
        raised = True
    check("no naive/aware TypeError on a naive due_date", not raised)


def test_missing_reply_to_does_not_raise():
    """A task with no reply_to/correlation_id (not created from the
    Kafka-driven HIL flow) must not break the status transition itself --
    enqueue_hil_reply's own no-op guard handles this, proven for real
    here (no mocking -- this goes through the actual enqueue/attempt
    path) rather than just assumed."""
    db = _make_session()
    task = Task(title="Manually entered review", status="pending")
    db.add(task)
    db.commit()

    status = apply_task_action(db, task, "complete", "reviewer@bank.example")
    check("completes without raising despite no reply_to", status == "completed", status)


def test_conflict_still_raises_and_never_publishes():
    """TaskConflictError (compare-and-swap loss) must still work exactly
    as before -- and must not have published anything on the way."""
    db = _make_session()
    task = Task(title="Review ALT-1004", status="pending",
                reply_to="hil.replies.x", correlation_id="corr-999")
    db.add(task)
    db.commit()

    # Simulate a *genuine* concurrent transition -- another connection
    # commits status="completed" independently, not this session's own
    # ORM object (mutating task.status directly would just get
    # autoflushed ahead of apply_task_action()'s own query, silently
    # defeating the compare-and-swap check this test exists to prove).
    with db.bind.connect() as conn:
        conn.execute(
            Task.__table__.update().where(Task.id == task.id).values(status="completed")
        )
        conn.commit()
    # Deliberately do NOT expire/reload `task` -- this session's own
    # in-memory belief must stay "pending" (stale), exactly reproducing
    # what a real concurrent caller's already-loaded Task object would
    # look like the moment before it tries to act on it.

    raised = False
    with patch("backend.task_actions.enqueue_hil_reply") as mock_enqueue:
        try:
            apply_task_action(db, task, "reject", "reviewer@bank.example")
        except TaskConflictError:
            raised = True
    check("TaskConflictError still raised on lost race", raised)
    check("no reply enqueued on a conflicted (non-applied) action",
          mock_enqueue.call_count == 0, f"called {mock_enqueue.call_count} times")


def main() -> int:
    for fn in (
        test_complete_publishes_to_reply_to,
        test_claim_does_not_publish,
        test_escalate_does_not_publish,
        test_escalate_extends_due_date_5_days_from_now_when_overdue,
        test_escalate_extends_from_existing_due_date_when_still_future,
        test_escalate_handles_timezone_naive_due_date_without_raising,
        test_missing_reply_to_does_not_raise,
        test_conflict_still_raises_and_never_publishes,
    ):
        print(f"{fn.__name__}:")
        fn()

    if failures:
        print(f"\n{len(failures)} check(s) failed: {failures}", file=sys.stderr)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
