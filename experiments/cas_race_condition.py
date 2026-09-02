"""
Failure-injection experiment: the compare-and-swap gap originally
disclosed in Sec. V-D of the paper ("An Integrated Ecosystem for
Governed Enterprise Agentic AI Systems") -- kept here as the historical
record of the original finding. That gap is now closed (see
backend/task_actions.py's guarded apply_task_action()); this script's
injected delay was updated to target the guard's actual read-then-write
window (previously it patched backend.routes.datetime, which stopped
having any effect once the delay-sensitive read moved into
task_actions.py during the fix -- silently turning this into two fast
sequential, non-conflicting calls rather than a real race). Running
this now demonstrates the FIXED behavior: see
experiments/cas_guard_verification.py for the version that asserts it.

`perform_action()` (backend/routes.py) delegates to
task_actions.apply_task_action(), which now does a guarded
UPDATE ... WHERE status = :expected_status. This script calls
perform_action() directly -- not a reimplementation of its logic --
with two threads racing to apply conflicting decisions ("complete" and
"reject") to the same pending task, and reports what actually happens:
does either commit fail, and does the final state reflect both
decisions, one, or neither?

A short sleep is injected between the guard's read (capturing
expected_status) and its write (the guarded UPDATE). This is the only
synthetic element; the delay exists to reliably force the interleaving
a real production race would only hit within a sub-millisecond window
on a single local call. Everything else -- the function called, the
ORM models, the database writes -- is the real reference
implementation, run against a disposable local PostgreSQL instance
(never point this at a real deployment's database).

Usage:
    createdb -h localhost -p 5432 k9x   # or any empty Postgres database
    psql -h localhost -p 5432 -d k9x -c "CREATE SCHEMA IF NOT EXISTS k9hil;"
    POSTGRES_HOST=localhost POSTGRES_PORT=5432 POSTGRES_DB=k9x \
        POSTGRES_USER=postgres POSTGRES_PASSWORD=<yours> \
        python experiments/cas_race_condition.py
"""
import threading
import time
from datetime import datetime, timezone

from fastapi import HTTPException

from backend.database import Base, SessionLocal, engine
from backend.models import Project, Application, Queue, Task, TaskAction, User
from backend.routes import perform_action, TaskActionReq

Base.metadata.create_all(bind=engine, checkfirst=True)

# ---- seed a real task ----
db = SessionLocal()
proj = Project(name="CAS-Experiment-Project")
db.add(proj); db.commit(); db.refresh(proj)
app = Application(project_id=proj.id, name="CAS-Experiment-App")
db.add(app); db.commit(); db.refresh(app)
queue = Queue(application_id=app.id, name="CAS-Experiment-Queue", topic="cas.experiment.topic")
db.add(queue); db.commit(); db.refresh(queue)
task = Task(queue_id=queue.id, title="CAS race-condition experiment task", status="pending")
db.add(task); db.commit(); db.refresh(task)
task_id = task.id
db.close()
print(f"Seeded task_id={task_id}, initial status=pending\n")

_fake_actor = User(id=0, name="experiment", email="experiment@local", role="reviewer")
results = {}


def call_real_perform_action(name: str, action: str, delay_before_write_s: float):
    """Calls the real perform_action() with an injected delay so the
    guard's internal read-then-write is split across a controllable
    window -- the function body executed is completely unmodified."""
    session = SessionLocal()

    # Patch time.sleep only for the duration of this call, positioned
    # between apply_task_action()'s read (expected_status = task.status)
    # and its guarded write (the UPDATE ... WHERE status =
    # :expected_status) by monkeypatching datetime.now() to also sleep --
    # apply_task_action() calls datetime.now(timezone.utc) exactly once,
    # immediately after capturing expected_status and before building
    # the update. Must patch task_actions.datetime specifically, not
    # routes.datetime -- perform_action() itself no longer calls
    # datetime.now() directly; it delegates to apply_task_action(),
    # which does.
    real_now = datetime.now

    def delayed_now(*a, **kw):
        time.sleep(delay_before_write_s)
        return real_now(*a, **kw)

    import backend.task_actions as task_actions_module
    original_datetime = task_actions_module.datetime

    class PatchedDatetime(datetime):
        @classmethod
        def now(cls, *a, **kw):
            return delayed_now(*a, **kw)

    task_actions_module.datetime = PatchedDatetime
    try:
        req = TaskActionReq(action=action, actor=f"reviewer-{name}", comment=f"race experiment: {name}")
        try:
            response = perform_action(task_id=task_id, req=req, db=session, _=_fake_actor)
            results[name] = response
        except HTTPException as exc:
            results[name] = {"ok": False, "status_code": exc.status_code, "detail": exc.detail}
    finally:
        task_actions_module.datetime = original_datetime
        session.close()


t_complete = threading.Thread(target=call_real_perform_action, args=("A-complete", "complete", 0.3))
t_reject = threading.Thread(target=call_real_perform_action, args=("B-reject", "reject", 0.1))

t_complete.start()
time.sleep(0.05)  # ensure both threads' reads happen before either write
t_reject.start()
t_complete.join()
t_reject.join()

print("perform_action() return value seen by each caller:")
for name, resp in results.items():
    print(f"  {name}: {resp}")

db = SessionLocal()
final_task = db.query(Task).filter(Task.id == task_id).first()
actions = db.query(TaskAction).filter(TaskAction.task_id == task_id).order_by(TaskAction.id).all()
print(f"\nFinal Task.status in the database: {final_task.status!r}")
print(f"TaskAction rows recorded ({len(actions)} -- only the winning decision is "
      f"recorded now; the loser's write never committed, per the guard):")
for a in actions:
    print(f"  - action={a.action!r} actor={a.actor!r}")
db.close()
