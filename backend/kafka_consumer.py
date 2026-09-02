import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from backend.database import SessionLocal
from backend.models import Queue, Task, TaskAction

log = logging.getLogger("k9x-hil.kafka_consumer")

_dlq_producer = None  # lazily started; see _get_dlq_producer()


async def _get_dlq_producer():
    """Lazily start (once) and return the shared AIOKafkaProducer used to
    publish dead-lettered messages. Previously, dead-letter routing was
    disclosed in the paper as implemented ("routed to per-topic
    dead-letter queues following the convention {topic}.dlq") but no
    such routing existed anywhere in this file -- a malformed message
    was either silently dropped (unregistered topic) or, for bad JSON
    specifically, propagated all the way out of the `async for` loop
    and killed the entire consumer's connection (see run_consumer()'s
    reconnect-loop comment below), not isolated to the one bad message.
    This implements the routing the disclosure described."""
    global _dlq_producer
    if _dlq_producer is None:
        from aiokafka import AIOKafkaProducer
        broker = os.getenv("KAFKA_BROKER", "localhost:9092")
        _dlq_producer = AIOKafkaProducer(bootstrap_servers=[broker])
        await _dlq_producer.start()
    return _dlq_producer


async def _publish_to_dlq(topic: str, raw_value: bytes, reason: str) -> None:
    """Publish a malformed/invalid inbound message to {topic}.dlq,
    preserving the original raw bytes (undecoded, so even non-UTF-8 or
    non-JSON payloads survive intact) plus enough metadata to diagnose
    why it was dead-lettered without needing the original producer."""
    dlq_topic = f"{topic}.dlq"
    envelope = {
        "original_topic": topic,
        "reason": reason,
        "dead_lettered_at": datetime.now(timezone.utc).isoformat(),
        "raw_value_b64": base64.b64encode(raw_value).decode("ascii"),
    }
    try:
        producer = await _get_dlq_producer()
        await producer.send_and_wait(dlq_topic, json.dumps(envelope).encode("utf-8"))
        log.warning("[kafka_consumer] dead-lettered malformed message from topic=%s to %s (reason=%s)",
                    topic, dlq_topic, reason)
    except Exception:
        log.exception("[kafka_consumer] failed to publish to dead-letter topic=%s", dlq_topic)


def _ingest_message(topic: str, message: dict) -> None:
    """Create a Task from an inbound HIL task-creation message.

    The producing system (any Kafka-writing service, per K9X HIL's
    framework-agnostic design) owns the message contract; this only
    maps it onto the Queue the topic belongs to. Messages on a topic
    with no registered Queue are logged and dropped — a Queue must be
    seeded/created for the topic first.
    """
    db = SessionLocal()
    try:
        queue = db.query(Queue).filter(Queue.topic == topic).first()
        if not queue:
            log.warning("[kafka_consumer] no Queue registered for topic=%s; dropping message", topic)
            return

        correlation_id = message.get("correlation_id")
        if correlation_id:
            existing = db.query(Task).filter(
                Task.correlation_id == correlation_id,
                Task.source_topic == topic,
            ).first()
            if existing:
                log.info("[kafka_consumer] duplicate correlation_id=%s on topic=%s; skipping", correlation_id, topic)
                return

        ttl_hours = message.get("ttl_hours", queue.ttl_hours)
        due_date = (
            datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            if ttl_hours else None
        )

        task = Task(
            queue_id=queue.id,
            title=message.get("title", f"Task on {topic}"),
            description=message.get("description"),
            source_orchestrator=message.get("source_orchestrator"),
            source_topic=topic,
            reply_to=message.get("reply_to"),
            correlation_id=correlation_id,
            status="pending",
            priority=message.get("priority", "medium"),
            assigned_to=message.get("assigned_to", "demo@k9x.ai"),
            payload=message.get("payload"),
            artifacts=message.get("artifacts"),
            jira_ticket=message.get("jira_ticket"),
            pii=message.get("pii", queue.pii),
            pii_fields=message.get("pii_fields"),
            ttl_hours=ttl_hours,
            ttl_action=message.get("ttl_action", queue.ttl_action),
            due_date=due_date,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        db.add(TaskAction(task_id=task.id, action="created", actor="system",
                           comment=f"Ingested from Kafka topic={topic}"))
        db.commit()
        log.info("[kafka_consumer] created task id=%s queue=%s topic=%s corr=%s",
                  task.id, queue.name, topic, correlation_id)
    except Exception:
        log.exception("[kafka_consumer] failed to ingest message on topic=%s", topic)
        db.rollback()
    finally:
        db.close()


async def run_consumer() -> None:
    """Background task: subscribe to every registered Queue's topic and
    create a Task for each inbound message. Started once at app startup.

    Topics are read from the Queue table at startup only — a newly
    created Queue requires an app restart to be picked up. Acceptable
    for this POC; a production version would re-subscribe on change.
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        log.error("[kafka_consumer] aiokafka not installed — run: pip install aiokafka")
        return

    broker = os.getenv("KAFKA_BROKER", "localhost:9092")

    db = SessionLocal()
    try:
        topics = [q.topic for q in db.query(Queue).all()]
    finally:
        db.close()

    if not topics:
        log.warning("[kafka_consumer] no Queues registered; consumer not starting")
        return

    # Real incident, 2026-08-31: a burst of tasks ingested fine, then nothing
    # for 5+ hours despite DAS publishing repeatedly and confirmed present on
    # the topic (checked directly with rpk). Root cause: the `async for msg
    # in consumer` loop below has no exception handling of its own -- only
    # the per-message body did. A dropped broker connection or any other
    # error from the iterator itself propagated straight out of this
    # function, silently killing the fire-and-forget asyncio.create_task()
    # in main.py with no crash, no visible error, just permanent silence.
    # Now retries the whole connect-and-consume cycle indefinitely instead
    # of dying once.
    backoff_s = 2
    while True:
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=[broker],
            group_id="k9x-hil-ingest",
            # "earliest", not "latest" -- a restart-timing gap where a
            # message publishes while this consumer is reconnecting
            # previously meant that message was gone forever ("latest" only
            # looks forward from wherever it happens to reconnect). Safe to
            # replay from the start on a cold/fresh group because
            # _ingest_message() below already dedupes by
            # correlation_id+source_topic; on a warm restart this resumes
            # from the last committed offset exactly as before, since
            # auto_offset_reset only applies when no valid offset exists yet.
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            # No value_deserializer: parsing happens per-message below so a
            # single malformed message is dead-lettered and skipped, rather
            # than raising out of aiokafka's own deserialization step
            # straight through this loop and killing the whole connection
            # (see run_consumer()'s docstring incident above -- that failure
            # mode is exactly what a deserializer-level exception would
            # cause; a per-message decode is what makes it isolated).
        )

        try:
            await consumer.start()
            log.info("[kafka_consumer] listening | broker=%s | topics=%s", broker, topics)
            backoff_s = 2  # reset once a connection actually succeeds
            async for msg in consumer:
                try:
                    try:
                        value = json.loads(msg.value.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        await _publish_to_dlq(msg.topic, msg.value, f"invalid JSON: {exc}")
                        continue
                    if not isinstance(value, dict):
                        await _publish_to_dlq(
                            msg.topic, msg.value,
                            f"message body is not a JSON object (got {type(value).__name__})",
                        )
                        continue
                    _ingest_message(msg.topic, value)
                except Exception:
                    log.exception("[kafka_consumer] error handling message on topic=%s", msg.topic)
        except Exception:
            log.exception(
                "[kafka_consumer] consumer loop failed (broker=%s) -- reconnecting in %ds",
                broker, backoff_s,
            )
        finally:
            try:
                await consumer.stop()
            except Exception:
                log.exception("[kafka_consumer] error stopping consumer during cleanup")

        await asyncio.sleep(backoff_s)
        backoff_s = min(backoff_s * 2, 60)
