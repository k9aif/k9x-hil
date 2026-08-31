import json
import logging
import os

from backend.database import SessionLocal
from backend.models import Queue, Task, TaskAction

log = logging.getLogger("k9x-hil.kafka_consumer")


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
            ttl_hours=message.get("ttl_hours", queue.ttl_hours),
            ttl_action=message.get("ttl_action", queue.ttl_action),
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

    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=[broker],
        group_id="k9x-hil-ingest",
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )

    try:
        await consumer.start()
    except Exception:
        log.exception("[kafka_consumer] failed to connect to broker=%s; consumer not running", broker)
        return

    log.info("[kafka_consumer] listening | broker=%s | topics=%s", broker, topics)
    try:
        async for msg in consumer:
            try:
                _ingest_message(msg.topic, msg.value)
            except Exception:
                log.exception("[kafka_consumer] error handling message on topic=%s", msg.topic)
    finally:
        await consumer.stop()
        log.info("[kafka_consumer] stopped")
