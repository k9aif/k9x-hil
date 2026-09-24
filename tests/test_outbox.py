#!/usr/bin/env python3
"""k9x-hil -- G-14: proves the transactional outbox actually recovers a
reply after a Kafka failure, instead of losing it silently.

Real in-memory SQLite session against the actual Task/HilReplyOutbox
models; only the Kafka producer is faked (no broker available here),
matching test_task_actions.py's own established convention.

Run directly:

    python3 tests/test_outbox.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, HilReplyOutbox, Task
from backend.outbox_sweep import _backoff_elapsed, _sweep_once
from backend.task_actions import apply_task_action

failures = []


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)
        failures.append(name)


def _make_session():
    for table in Base.metadata.tables.values():
        table.schema = None
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class _FlakyProducer:
    """Fails send() the first N calls, then succeeds -- simulates a Kafka
    outage that later recovers, without needing a real broker."""

    def __init__(self, fail_times: int = 1):
        self.fail_times = fail_times
        self.calls = 0

    def send(self, topic, value):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("simulated Kafka outage")
        return None

    def flush(self):
        pass


def test_publish_failure_leaves_outbox_row_pending_not_lost():
    """The core G-14 case: Kafka down at decision time -- decision commits
    to Postgres regardless, and the reply isn't silently dropped, it's
    durably queued."""
    db = _make_session()
    task = Task(title="Review ALT-3001", status="pending",
                reply_to="hil.replies.x", correlation_id="corr-out-1")
    db.add(task)
    db.commit()

    with patch("backend.hil_reply._get_producer", return_value=_FlakyProducer(fail_times=99)):
        status = apply_task_action(db, task, "complete", "reviewer@bank.example")

    check("status still transitions despite Kafka being down", status == "completed", status)

    row = db.query(HilReplyOutbox).filter_by(correlation_id="corr-out-1").first()
    check("outbox row exists", row is not None)
    if row:
        check("outbox row is pending, not lost", row.status == "pending", row.status)
        check("one attempt recorded", row.attempts == 1, row.attempts)
        check("event payload frozen with correct action", row.event["action"] == "complete", row.event)


def test_publish_failure_followed_by_recovery_republishes_exactly_once():
    """A publish failure followed by recovery republishes exactly once --
    the sweep marks it published on the first successful pass and a
    second pass must not touch it again (filter is status == pending)."""
    db = _make_session()
    task = Task(title="Review ALT-3002", status="pending",
                reply_to="hil.replies.x", correlation_id="corr-out-2")
    db.add(task)
    db.commit()

    # Decision made while Kafka is down.
    with patch("backend.hil_reply._get_producer", return_value=_FlakyProducer(fail_times=99)):
        apply_task_action(db, task, "reject", "reviewer@bank.example")

    row = db.query(HilReplyOutbox).filter_by(correlation_id="corr-out-2").first()
    check("row pending after the initial failed attempt", row.status == "pending")
    # Force the backoff window open regardless of real elapsed time.
    row.last_attempt_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    # outbox_sweep._sweep_once() opens its own SessionLocal() internally
    # (same shape as ttl_sweep._sweep_once()) -- point it at this test's
    # in-memory engine for the duration of the call, or it reaches for
    # the real configured Postgres instead.
    SessionMaker = sessionmaker(bind=db.bind)

    # Kafka has now recovered -- sweep should succeed this time.
    with patch("backend.outbox_sweep.SessionLocal", SessionMaker), \
         patch("backend.hil_reply._get_producer", return_value=_FlakyProducer(fail_times=0)):
        republished = _sweep_once()
    check("sweep republished exactly one row", republished == 1, republished)

    db.expire_all()  # this session's own identity-mapped `row` is stale
                      # after a *different* session (the sweep's) wrote it
    row = db.query(HilReplyOutbox).filter_by(correlation_id="corr-out-2").first()
    check("row now published", row.status == "published", row.status)
    check("two attempts total (initial failure + sweep success)", row.attempts == 2, row.attempts)

    # A second sweep pass must not touch an already-published row again.
    with patch("backend.outbox_sweep.SessionLocal", SessionMaker), \
         patch("backend.hil_reply._get_producer", return_value=_FlakyProducer(fail_times=0)):
        republished_again = _sweep_once()
    check("a second sweep pass republishes nothing more", republished_again == 0, republished_again)


def test_backoff_skips_a_row_attempted_too_recently():
    row = HilReplyOutbox(
        task_id=1, correlation_id="c", reply_to="t", event={}, status="pending",
        attempts=1, last_attempt_at=datetime.now(timezone.utc),
    )
    check("backoff not yet elapsed right after a first failed attempt",
          not _backoff_elapsed(row, datetime.now(timezone.utc)))


def test_backoff_allows_retry_once_window_elapses():
    row = HilReplyOutbox(
        task_id=1, correlation_id="c", reply_to="t", event={}, status="pending",
        attempts=1, last_attempt_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    # attempts=1 -> 2**1 = 2 minute backoff, 10 minutes have passed.
    check("backoff elapsed after enough time has passed",
          _backoff_elapsed(row, datetime.now(timezone.utc)))


def test_never_attempted_row_has_no_backoff():
    row = HilReplyOutbox(
        task_id=1, correlation_id="c", reply_to="t", event={}, status="pending",
        attempts=0, last_attempt_at=None,
    )
    check("a never-attempted row is always immediately eligible",
          _backoff_elapsed(row, datetime.now(timezone.utc)))


def main() -> int:
    for fn in (
        test_publish_failure_leaves_outbox_row_pending_not_lost,
        test_publish_failure_followed_by_recovery_republishes_exactly_once,
        test_backoff_skips_a_row_attempted_too_recently,
        test_backoff_allows_retry_once_window_elapses,
        test_never_attempted_row_has_no_backoff,
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
