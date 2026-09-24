# SPDX-License-Identifier: Apache-2.0
"""
Publishes a task's terminal decision back to its reply_to topic, via a
transactional outbox (G-14).

Closes the gap k9-aif-framework's own HIL round trip (RequiresHIL ->
BaseHILOrchestrator -> K9EventRouter.listen_for_hil_replies(), see that
repo's CLAUDE.md HIL section) depends on: a paused orchestrator flow can
only resume once something actually publishes to the topic it's waiting
on. Confirmed directly by reading apply_task_action() (before this
module existed) and grep'ing this whole backend for any Kafka producer
touching it: none existed.

G-14: the first cut of this module (log-and-drop on a Kafka failure) had
a real gap of its own -- if Kafka was down at the exact moment of
decision, the decision was safe in Postgres but nothing ever retried the
notification, and the paused flow stayed paused forever with no signal
anywhere that it happened. `backend.models.HilReplyOutbox` (written in
the same transaction as the Task status change, see task_actions.py) plus
outbox_sweep.py's periodic retry closes that -- the rule this module
existed to establish in the first place (a publish failure never rolls
back or blocks the human's decision) is unchanged, just no longer the
end of the story for that failed publish.

Synchronous (kafka-python), not the AIOKafkaProducer kafka_consumer.py's
DLQ path uses, deliberately -- apply_task_action() and outbox_sweep.py
are both plain sync code; bridging to an async producer risks the
"asyncio.run() inside an already-running event loop raises" trap
k9-aif-framework's own CLAUDE.md warns about for the identical reason.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.models import HilReplyOutbox

log = logging.getLogger("k9x-hil.hil_reply")

_producer = None  # lazily started; see _get_producer()


def _get_producer():
    """Lazily start (once) and return the shared, synchronous KafkaProducer
    used to publish HIL decisions. Same lazy-singleton shape as
    kafka_consumer.py's _get_dlq_producer(), sync instead of async."""
    global _producer
    if _producer is None:
        from kafka import KafkaProducer
        broker = os.getenv("KAFKA_BROKER", "localhost:9092")
        _producer = KafkaProducer(
            bootstrap_servers=[broker],
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    return _producer


def build_reply_event(
    correlation_id: str,
    action: str,
    actor: str,
    status: str,
    comment: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The wire schema K9EventRouter's reply-side consumes. Do not change
    without coordinating -- the ent-app-kit integration plan's decision
    mapping depends on this exact shape:
    {correlation_id, action, actor, status, comment, result, decided_at}."""
    return {
        "correlation_id": correlation_id,
        "action": action,
        "actor": actor,
        "status": status,
        "comment": comment,
        "result": result,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }


def enqueue_hil_reply(
    db,
    task_id: int,
    reply_to: Optional[str],
    correlation_id: Optional[str],
    action: str,
    actor: str,
    status: str,
    comment: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> Optional[HilReplyOutbox]:
    """Write the outbox row for a terminal decision. Caller (apply_task_action)
    must add this to the same session/transaction as the Task status
    change and commit them together -- that's what makes this a real
    transactional outbox rather than a best-effort side call.

    Returns None (no-op) when reply_to or correlation_id is missing -- a
    task created outside the Kafka-driven HIL flow (manually entered, or
    from a source that never set these) has nothing waiting on a Kafka
    reply, and that must never fail the status transition itself.
    """
    if not reply_to or not correlation_id:
        log.debug(
            "[hil_reply] no reply_to/correlation_id on this task -- "
            "no outbox row (action=%s)", action,
        )
        return None

    event = build_reply_event(correlation_id, action, actor, status, comment, result)
    row = HilReplyOutbox(
        task_id=task_id, correlation_id=correlation_id, reply_to=reply_to,
        event=event, status="pending",
    )
    db.add(row)
    return row


def attempt_publish(db, row: HilReplyOutbox) -> bool:
    """Try to send one outbox row. Always commits the attempt bookkeeping
    (attempts, last_attempt_at, and status on success) regardless of
    outcome -- a failure here must never raise and must never roll back
    anything, including its own attempt count, or the backoff schedule
    in outbox_sweep.py has nothing to compute from next pass. Returns
    True on success."""
    row.attempts += 1
    row.last_attempt_at = datetime.now(timezone.utc)
    try:
        producer = _get_producer()
        producer.send(row.reply_to, value=row.event)
        producer.flush()
        row.status = "published"
        row.published_at = row.last_attempt_at
        db.commit()
        log.info(
            "[hil_reply] published correlation_id=%s action=%s -> %s (attempt %d)",
            row.correlation_id, row.event.get("action"), row.reply_to, row.attempts,
        )
        return True
    except Exception:
        db.commit()  # persist the failed attempt's bookkeeping -- row stays "pending"
        log.exception(
            "[hil_reply] publish attempt %d failed correlation_id=%s -> %s -- "
            "decision remains recorded in Postgres; outbox_sweep will retry",
            row.attempts, row.correlation_id, row.reply_to,
        )
        return False
