# SPDX-License-Identifier: Apache-2.0
"""
TTL enforcement: the piece that was missing. ttl_hours/ttl_action/
due_date were already stored on every task (see kafka_consumer.py and
backend/seed.py) and shown in the UI/API, but nothing ever read
due_date back and acted on it -- a task past its TTL stayed PENDING
forever. This is that missing sweep.

Runs as a background asyncio task (started in main.py, same pattern as
run_consumer()): every SWEEP_INTERVAL_SECONDS, find every task still
PENDING whose due_date has passed, and apply its own configured
ttl_action via the same apply_task_action() the human-driven
/tasks/{id}/action route uses -- so a TTL-driven rejection and a
human-driven rejection are indistinguishable in the audit trail except
for the actor field.

Only PENDING tasks are swept. A task already CLAIMED (assigned_to set,
still status=pending in this schema) or IN_PROGRESS is presumed to
have a human actively engaged and is left alone; TTL exists to catch
tasks nobody has touched, not to override an active review.
"""
import asyncio
import logging
from datetime import datetime, timezone

from backend.database import SessionLocal
from backend.models import Task
from backend.task_actions import apply_task_action

log = logging.getLogger("k9x-hil.ttl_sweep")

SWEEP_INTERVAL_SECONDS = 300


def _sweep_once() -> int:
    """Run one sweep pass. Returns the number of tasks actioned."""
    db = SessionLocal()
    actioned = 0
    try:
        now = datetime.now(timezone.utc)
        expired = (
            db.query(Task)
            .filter(Task.status == "pending")
            .filter(Task.due_date.isnot(None))
            .filter(Task.due_date < now)
            .all()
        )
        for task in expired:
            if not task.ttl_action:
                log.warning(
                    "[ttl_sweep] task id=%s past due_date=%s with no ttl_action configured; skipping",
                    task.id, task.due_date,
                )
                continue
            try:
                new_status = apply_task_action(
                    db, task, task.ttl_action, actor="system:ttl_sweep",
                    comment=f"TTL expired (due_date={task.due_date.isoformat()})",
                )
                log.info("[ttl_sweep] task id=%s auto-actioned action=%s -> status=%s",
                          task.id, task.ttl_action, new_status)
                actioned += 1
            except ValueError:
                log.exception(
                    "[ttl_sweep] task id=%s has invalid ttl_action=%r; skipping",
                    task.id, task.ttl_action,
                )
                db.rollback()
    finally:
        db.close()
    return actioned


async def run_ttl_sweep() -> None:
    """Background task: periodically sweep expired PENDING tasks.

    Runs indefinitely once started (see main.py's startup event). A
    failure in one pass is logged and the loop continues on the next
    interval rather than dying silently -- the same lesson learned the
    hard way with the Kafka consumer loop (see kafka_consumer.py).
    """
    while True:
        try:
            actioned = _sweep_once()
            if actioned:
                log.info("[ttl_sweep] swept %d expired task(s)", actioned)
        except Exception:
            log.exception("[ttl_sweep] sweep pass failed; will retry next interval")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
