# SPDX-License-Identifier: Apache-2.0
"""
Publishes a task's terminal decision back to its reply_to topic.

Closes the gap k9-aif-framework's own HIL round trip (RequiresHIL ->
BaseHILOrchestrator -> K9EventRouter.listen_for_hil_replies(), see that
repo's CLAUDE.md HIL section) depends on: a paused orchestrator flow can
only resume once something actually publishes to the topic it's waiting
on. Until this module existed, apply_task_action() only ever wrote to
Postgres -- reply_to and correlation_id were captured on the Task row and
never used again after ingest. Confirmed directly by reading
apply_task_action() and grep'ing this whole backend for any Kafka
producer touching it: none existed.

Synchronous (kafka-python), not the AIOKafkaProducer kafka_consumer.py's
DLQ path uses, deliberately -- apply_task_action() is a plain sync
function shared by the sync HTTP route (routes.perform_action) and the
sync TTL-sweep path (ttl_sweep.sweep_expired_tasks). Bridging to an async
producer from there risks the "asyncio.run() inside an already-running
event loop raises" trap k9-aif-framework's own CLAUDE.md warns about for
the identical reason. A plain blocking producer sidesteps that entirely.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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


def publish_hil_reply(
    reply_to: Optional[str],
    correlation_id: Optional[str],
    action: str,
    actor: str,
    status: str,
    comment: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Publish a task's decision to its reply_to topic.

    No-op (logged, not raised) when reply_to or correlation_id is missing
    -- a task created outside the Kafka-driven HIL flow (manually entered,
    or from a source that never set these) has nothing waiting on a
    Kafka reply, and that must never fail the actual status transition
    that already committed to Postgres.
    """
    if not reply_to or not correlation_id:
        log.debug(
            "[hil_reply] no reply_to/correlation_id on this task -- "
            "skipping publish (action=%s)", action,
        )
        return

    event = {
        "correlation_id": correlation_id,
        "action": action,
        "actor": actor,
        "status": status,
        "comment": comment,
        "result": result,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        producer = _get_producer()
        producer.send(reply_to, value=event)
        producer.flush()
        log.info(
            "[hil_reply] published decision correlation_id=%s action=%s -> %s",
            correlation_id, action, reply_to,
        )
    except Exception:
        # Never let a Kafka outage undo or block a decision that already
        # committed to Postgres -- the human's action is durable either
        # way; only the async notification failed. Same "log, don't
        # raise" posture as kafka_consumer.py's own _publish_to_dlq().
        log.exception(
            "[hil_reply] failed to publish correlation_id=%s to %s -- "
            "decision is still recorded in Postgres, only the Kafka "
            "notification was lost", correlation_id, reply_to,
        )
