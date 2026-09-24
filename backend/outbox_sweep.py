# SPDX-License-Identifier: Apache-2.0
"""
G-14: retries publishing pending HilReplyOutbox rows -- decisions whose
immediate publish attempt (in task_actions.apply_task_action(), via
hil_reply.attempt_publish()) failed, most likely because Kafka was
unreachable at the exact moment of decision. The decision itself is
already safe in Postgres either way; this sweep is what turns "safe but
stuck" back into "the paused orchestrator flow actually resumes."

Same background-asyncio-task shape as ttl_sweep.py (started in main.py).
Runs more frequently (60s vs. ttl_sweep's 300s) -- once Kafka recovers,
a paused flow should resume within a minute, not wait up to five.

Exponential backoff per row (2**attempts minutes, capped at 30) so a
sustained Kafka outage doesn't turn this into a tight retry loop hammering
a broker that's still down -- same posture as any outbox-pattern retry
sweep, not specific to this codebase.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from backend.database import SessionLocal
from backend.hil_reply import attempt_publish
from backend.models import HilReplyOutbox

log = logging.getLogger("k9x-hil.outbox_sweep")

OUTBOX_SWEEP_INTERVAL_SECONDS = 60
MAX_BACKOFF_MINUTES = 30


def _backoff_elapsed(row: HilReplyOutbox, now: datetime) -> bool:
    """True once enough time has passed since the last attempt to retry
    this row again. attempts starts at 0 (never tried) -- always ready."""
    if row.attempts == 0 or row.last_attempt_at is None:
        return True
    wait_minutes = min(2 ** row.attempts, MAX_BACKOFF_MINUTES)
    last_attempt = row.last_attempt_at
    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=timezone.utc)
    return (now - last_attempt) >= timedelta(minutes=wait_minutes)


def _sweep_once() -> int:
    """Run one sweep pass. Returns the number of rows successfully
    republished."""
    db = SessionLocal()
    republished = 0
    try:
        now = datetime.now(timezone.utc)
        pending = (
            db.query(HilReplyOutbox)
            .filter(HilReplyOutbox.status == "pending")
            .all()
        )
        for row in pending:
            if not _backoff_elapsed(row, now):
                continue
            if attempt_publish(db, row):
                republished += 1
    finally:
        db.close()
    return republished


async def run_outbox_sweep() -> None:
    """Background task: periodically retry undelivered HIL replies.

    Runs indefinitely once started (see main.py's startup event). A
    failure in one pass is logged and the loop continues on the next
    interval rather than dying silently -- same lesson already applied
    to the Kafka consumer loop and ttl_sweep.
    """
    while True:
        try:
            republished = _sweep_once()
            if republished:
                log.info("[outbox_sweep] republished %d reply/replies", republished)
        except Exception:
            log.exception("[outbox_sweep] sweep pass failed; will retry next interval")
        await asyncio.sleep(OUTBOX_SWEEP_INTERVAL_SECONDS)
