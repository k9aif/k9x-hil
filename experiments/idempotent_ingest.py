"""
Failure-injection experiment: Kafka's at-least-once delivery guarantee
means a task-creation message can be delivered more than once to the
same consumer (broker redelivery after a slow or missed offset commit,
consumer restart before commit, etc.). Sec. V-D claims HIL's ingest
path is idempotent under this condition, deduplicating on
`correlation_id`. This script calls the real `_ingest_message()`
(backend/kafka_consumer.py) directly, twice, with an identical message,
and reports how many Task rows actually result.

Usage: same setup as cas_race_condition.py in this directory.
"""
from backend.database import Base, SessionLocal, engine
from backend.models import Project, Application, Queue, Task
from backend.kafka_consumer import _ingest_message

Base.metadata.create_all(bind=engine, checkfirst=True)

db = SessionLocal()
proj = Project(name="Idempotency-Experiment-Project")
db.add(proj); db.commit(); db.refresh(proj)
app = Application(project_id=proj.id, name="Idempotency-Experiment-App")
db.add(app); db.commit(); db.refresh(app)
queue = Queue(application_id=app.id, name="Idempotency-Experiment-Queue", topic="idempotency.experiment.topic")
db.add(queue); db.commit(); db.refresh(queue)
db.close()

msg = {
    "title": "Duplicate-delivery experiment task",
    "correlation_id": "idempotency-experiment-corr-id-001",
    "source_orchestrator": "ExperimentOrchestrator",
}

print("Delivering the identical message twice to the real ingest path"
      " (simulating Kafka at-least-once redelivery)...")
_ingest_message("idempotency.experiment.topic", msg)
_ingest_message("idempotency.experiment.topic", msg)

db = SessionLocal()
matches = db.query(Task).filter(Task.correlation_id == "idempotency-experiment-corr-id-001").all()
print(f"\nTask rows created for one correlation_id delivered twice: {len(matches)}")
for t in matches:
    print(f"  - id={t.id} title={t.title!r}")
db.close()

assert len(matches) == 1, "FAILED: duplicate delivery produced more than one Task row"
print("\nPASS: dedup-on-correlation_id held under simulated at-least-once redelivery.")
