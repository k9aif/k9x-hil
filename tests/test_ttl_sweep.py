#!/usr/bin/env python3
"""k9x-hil -- G-15: proves an escalated task past its (c001d3b-extended)
due_date is actually expired by the sweep, instead of sitting open
forever -- ttl_sweep.py previously only ever looked at status == "pending".

Run directly:

    python3 tests/test_ttl_sweep.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, HilReplyOutbox, Task
from backend.ttl_sweep import _sweep_once as _ttl_sweep_once

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


_orig_session_local = None


def _patch_ttl_sweep_db(monkey_session_maker):
    """ttl_sweep._sweep_once() opens its own SessionLocal() internally
    rather than taking a db argument (matches apply_task_action()'s own
    callers) -- point backend.database.SessionLocal at this test's
    in-memory engine's sessionmaker for the duration of the call."""
    return patch("backend.ttl_sweep.SessionLocal", monkey_session_maker)


def test_escalated_task_past_due_date_is_expired_and_published():
    db = _make_session()
    engine = db.bind
    SessionMaker = sessionmaker(bind=engine)

    past_due = datetime.now(timezone.utc) - timedelta(hours=1)
    task = Task(
        title="Review ALT-4001", status="escalated", ttl_action="expire",
        due_date=past_due, reply_to="hil.replies.x", correlation_id="corr-ttl-1",
    )
    db.add(task)
    db.commit()
    task_id = task.id

    with _patch_ttl_sweep_db(SessionMaker), \
         patch("backend.hil_reply._get_producer") as mock_get_producer:
        mock_producer = mock_get_producer.return_value
        mock_producer.send.return_value = None
        mock_producer.flush.return_value = None
        actioned = _ttl_sweep_once()

    check("sweep actioned the escalated task", actioned == 1, actioned)

    # The sweep wrote via its own session (a different Python session
    # object than this test's `db`, even though bound to the same
    # engine) -- this session's identity-mapped `task` is stale until
    # expired, same class of bug already fixed once in test_outbox.py.
    db.expire_all()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    check("status is now expired", refreshed.status == "expired", refreshed.status)

    outbox_row = db.query(HilReplyOutbox).filter_by(correlation_id="corr-ttl-1").first()
    check("a reply was published for the auto-expired escalation",
          outbox_row is not None and outbox_row.status == "published",
          outbox_row.status if outbox_row else "no row")


def test_escalated_task_not_yet_due_is_left_alone():
    db = _make_session()
    engine = db.bind
    SessionMaker = sessionmaker(bind=engine)

    future_due = datetime.now(timezone.utc) + timedelta(days=3)
    task = Task(title="Review ALT-4002", status="escalated", ttl_action="expire",
                due_date=future_due)
    db.add(task)
    db.commit()
    task_id = task.id

    with _patch_ttl_sweep_db(SessionMaker):
        actioned = _ttl_sweep_once()

    check("sweep does not touch an escalated task before its due date", actioned == 0, actioned)
    db.expire_all()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    check("status unchanged", refreshed.status == "escalated", refreshed.status)


def test_in_progress_task_past_due_date_still_left_alone():
    """Regression guard: G-15 widens the sweep to escalated, not to every
    status -- in_progress must still be presumed actively engaged."""
    db = _make_session()
    engine = db.bind
    SessionMaker = sessionmaker(bind=engine)

    past_due = datetime.now(timezone.utc) - timedelta(hours=1)
    task = Task(title="Review ALT-4003", status="in_progress", ttl_action="expire",
                due_date=past_due)
    db.add(task)
    db.commit()
    task_id = task.id

    with _patch_ttl_sweep_db(SessionMaker):
        actioned = _ttl_sweep_once()

    check("sweep does not touch an in_progress task", actioned == 0, actioned)
    db.expire_all()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    check("status unchanged", refreshed.status == "in_progress", refreshed.status)


def main() -> int:
    for fn in (
        test_escalated_task_past_due_date_is_expired_and_published,
        test_escalated_task_not_yet_due_is_left_alone,
        test_in_progress_task_past_due_date_still_left_alone,
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
