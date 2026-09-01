"""
Demonstrates the TTL sweep actually firing: creates a task already
past its due_date, runs one real sweep pass (_sweep_once(), the exact
function the background loop calls every interval), and shows the
task's status changed and the audit trail recorded who did it.

Usage: same disposable-Postgres setup as cas_race_condition.py.
"""
from datetime import datetime, timedelta, timezone

from backend.database import Base, SessionLocal, engine
from backend.models import Project, Application, Queue, Task, TaskAction
from backend.ttl_sweep import _sweep_once

Base.metadata.create_all(bind=engine, checkfirst=True)

db = SessionLocal()
proj = Project(name="TTL-Sweep-Demo-Project")
db.add(proj); db.commit(); db.refresh(proj)
app = Application(project_id=proj.id, name="TTL-Sweep-Demo-App")
db.add(app); db.commit(); db.refresh(app)
queue = Queue(application_id=app.id, name="TTL-Sweep-Demo-Queue",
              topic="ttl.sweep.demo.topic", ttl_hours=168, ttl_action="reject")
db.add(queue); db.commit(); db.refresh(queue)

# A task whose due_date is already 1 hour in the past -- exactly what
# "no human acted within the TTL window" looks like in the database.
past_due = datetime.now(timezone.utc) - timedelta(hours=1)
task = Task(queue_id=queue.id, title="Task nobody reviewed in time",
            status="pending", ttl_hours=168, ttl_action="reject", due_date=past_due)
db.add(task); db.commit(); db.refresh(task)
task_id = task.id
db.close()

print(f"Created task_id={task_id}, due_date={past_due.isoformat()} (already expired), status=pending")

actioned = _sweep_once()
print(f"\nSweep pass actioned {actioned} task(s).")

db = SessionLocal()
final_task = db.query(Task).filter(Task.id == task_id).first()
actions = db.query(TaskAction).filter(TaskAction.task_id == task_id).all()
print(f"\nFinal Task.status: {final_task.status!r}")
for a in actions:
    print(f"  TaskAction: action={a.action!r} actor={a.actor!r} comment={a.comment!r}")
db.close()

assert final_task.status == "rejected", f"expected 'rejected', got {final_task.status!r}"
print("\nPASS: TTL sweep correctly auto-rejected the expired task.")
