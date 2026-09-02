"""
Failure-injection experiment for dead-letter routing.

This is not a re-test of an existing mechanism -- testing it surfaced
that dead-letter routing DID NOT EXIST anywhere in kafka_consumer.py.
The paper's Sec. V-D disclosed it as "implemented but not
failure-tested" ("routed to per-topic dead-letter queues following the
convention {topic}.dlq"); in fact, a malformed message either got
silently dropped (unregistered topic) or, for invalid JSON specifically,
propagated an exception out of aiokafka's own value_deserializer,
through the `async for msg in consumer` loop, and killed the entire
consumer's broker connection -- not isolated to the one bad message.
Dead-letter routing is implemented in this same change (kafka_consumer.py:
_publish_to_dlq(), _get_dlq_producer(), and the per-message try/except
that replaces the old deserializer) and verified here against a real,
running Kafka-compatible broker (Redpanda) -- no mocks.

Two failure classes tested:
  (a) invalid JSON bytes on the ingest topic
  (b) valid JSON that is not an object (e.g. a bare JSON array) --
      _ingest_message() calls message.get(...) throughout and would
      crash on this shape if it weren't caught first

For each: publish the bad message to a real topic that run_consumer()
is actually subscribed to, let the real consumer loop process it, then
confirm (1) no Task was created for it, and (2) the corresponding
{topic}.dlq topic received a message whose envelope preserves the
original raw bytes (base64) and a diagnosable reason -- enough to
reconstruct and debug the original payload without needing the
original producer.

Usage:
    Requires a real Kafka-compatible broker on KAFKA_BROKER
    (default localhost:9092) and a disposable local PostgreSQL
    instance, same as cas_guard_verification.py.

    POSTGRES_HOST=localhost POSTGRES_PORT=15432 POSTGRES_DB=k9x \
        POSTGRES_USER=postgres POSTGRES_PASSWORD=verify \
        python3 experiments/dead_letter_routing.py
"""
import asyncio
import base64
import json

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from backend.database import Base, SessionLocal, engine
from backend.models import Project, Application, Queue, Task
import backend.kafka_consumer as kafka_consumer_module
from backend.kafka_consumer import run_consumer

TOPIC = "dlq.experiment.topic"
DLQ_TOPIC = f"{TOPIC}.dlq"
BROKER = "localhost:9092"


async def main():
    Base.metadata.create_all(bind=engine, checkfirst=True)

    # ---- seed a real Queue for this topic so run_consumer() subscribes to it ----
    db = SessionLocal()
    proj = Project(name="DLQ-Experiment-Project")
    db.add(proj); db.commit(); db.refresh(proj)
    app = Application(project_id=proj.id, name="DLQ-Experiment-App")
    db.add(app); db.commit(); db.refresh(app)
    queue = Queue(application_id=app.id, name="DLQ-Experiment-Queue", topic=TOPIC)
    db.add(queue); db.commit(); db.refresh(queue)
    db.close()
    print(f"Seeded Queue for topic={TOPIC!r}\n")

    # ---- start the real, unmodified consumer as a background task ----
    consumer_task = asyncio.create_task(run_consumer())
    await asyncio.sleep(2)  # let it connect and subscribe

    # ---- publish the two malformed payloads to the real ingest topic ----
    producer = AIOKafkaProducer(bootstrap_servers=[BROKER])
    await producer.start()
    try:
        bad_json_bytes = b'{"title": "broken", "payload": {bad json here'
        await producer.send_and_wait(TOPIC, bad_json_bytes)
        print(f"Published invalid-JSON message to {TOPIC}")

        not_an_object_bytes = json.dumps(["this", "is", "an", "array", "not", "an", "object"]).encode("utf-8")
        await producer.send_and_wait(TOPIC, not_an_object_bytes)
        print(f"Published non-object-JSON message to {TOPIC}")

        # A real, valid message published *after* the two malformed ones --
        # proves the consumer's connection survived both dead-letter events
        # rather than merely inferring it from the fact that message 2 was
        # also processed (which a reconnect within the sleep window could
        # coincidentally still satisfy).
        valid_bytes = json.dumps({
            "title": "valid message after two malformed ones",
            "correlation_id": "dlq-experiment-valid-1",
        }).encode("utf-8")
        await producer.send_and_wait(TOPIC, valid_bytes)
        print(f"Published a valid message to {TOPIC} (should become a real Task)")
    finally:
        await producer.stop()

    await asyncio.sleep(3)  # let the real consumer loop process all three

    # ---- consume from the real {topic}.dlq to see what landed there ----
    dlq_consumer = AIOKafkaConsumer(
        DLQ_TOPIC, bootstrap_servers=[BROKER],
        group_id="dlq-experiment-reader", auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await dlq_consumer.start()
    dlq_messages = []
    try:
        async for msg in dlq_consumer:
            dlq_messages.append(json.loads(msg.value.decode("utf-8")))
            if len(dlq_messages) >= 2:
                break
    finally:
        await asyncio.wait_for(dlq_consumer.stop(), timeout=5)

    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    if kafka_consumer_module._dlq_producer is not None:
        await kafka_consumer_module._dlq_producer.stop()

    print(f"\nMessages landed on {DLQ_TOPIC}:")
    for m in dlq_messages:
        decoded_raw = base64.b64decode(m["raw_value_b64"])
        print(f"  reason={m['reason']!r}")
        print(f"  original_topic={m['original_topic']!r}")
        print(f"  recovered original bytes: {decoded_raw!r}")

    # ---- confirm exactly the valid message became a Task, and no Task
    # ---- exists for either malformed one ----
    db = SessionLocal()
    tasks = db.query(Task).filter(Task.queue_id == queue.id).all()
    db.close()

    # ---- assertions ----
    assert len(dlq_messages) == 2, f"expected 2 dead-lettered messages, got {len(dlq_messages)}"
    assert len(tasks) == 1, (
        f"expected exactly 1 Task (the valid message sent after the two "
        f"malformed ones, proving the consumer's connection survived both "
        f"dead-letter events), got {len(tasks)}"
    )
    assert tasks[0].correlation_id == "dlq-experiment-valid-1"

    reasons = {m["reason"] for m in dlq_messages}
    assert any("invalid JSON" in r for r in reasons), f"no dead-letter entry cites invalid JSON: {reasons}"
    assert any("not a JSON object" in r for r in reasons), f"no dead-letter entry cites the non-object shape: {reasons}"

    recovered = [base64.b64decode(m["raw_value_b64"]) for m in dlq_messages]
    assert bad_json_bytes in recovered, "the invalid-JSON message's original bytes were not recoverable from its dead-letter envelope"
    assert not_an_object_bytes in recovered, "the non-object message's original bytes were not recoverable from its dead-letter envelope"

    print(f"\nPASS: both malformed messages were dead-lettered to {DLQ_TOPIC} "
          f"(not silently dropped, not processed as tasks), each with its full "
          f"original payload recoverable from the envelope, and the consumer's "
          f"connection survived both -- confirmed by the valid message sent "
          f"immediately after both becoming a real Task (id={tasks[0].id}).")


if __name__ == "__main__":
    asyncio.run(main())
