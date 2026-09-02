"""
Failure-injection experiment: proves the compare-and-swap guard added to
perform_action() (backend/task_actions.py) actually closes the race
originally demonstrated in experiments/cas_race_condition.py.

Same race, same injection technique, same real code path (this calls
the real perform_action() directly, not a reimplementation) -- only
difference is what's asserted at the end. Where cas_race_condition.py
showed both concurrent decisions committing silently with the last
write winning, this asserts the fixed behavior: exactly one commit
succeeds, the other receives an explicit TaskConflictError (surfaced by
perform_action() as HTTPException(409)), and the final status is
deterministic (matches whichever decision actually won the race, not
an unpredictable interleaving).

Usage: same disposable-Postgres setup as cas_race_condition.py.
    POSTGRES_HOST=localhost POSTGRES_PORT=5432 POSTGRES_DB=k9x \
        POSTGRES_USER=postgres POSTGRES_PASSWORD=<yours> \
        python experiments/cas_guard_verification.py
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
proj = Project(name="CAS-Guard-Verification-Project")
db.add(proj); db.commit(); db.refresh(proj)
app = Application(project_id=proj.id, name="CAS-Guard-Verification-App")
db.add(app); db.commit(); db.refresh(app)
queue = Queue(application_id=app.id, name="CAS-Guard-Verification-Queue", topic="cas.guard.topic")
db.add(queue); db.commit(); db.refresh(queue)
task = Task(queue_id=queue.id, title="CAS guard verification task", status="pending")
db.add(task); db.commit(); db.refresh(task)
task_id = task.id
db.close()
print(f"Seeded task_id={task_id}, initial status=pending\n")

_fake_actor = User(id=0, name="experiment", email="experiment@local", role="reviewer")
outcomes = {}  # name -> ("ok", status) | ("conflict", status_code, detail)


def call_real_perform_action(name: str, action: str, delay_before_write_s: float):
    """Calls the real perform_action() with an injected delay between its
    read (expected_status = task.status) and its guarded write (the
    UPDATE ... WHERE status = :expected_status), by monkeypatching
    datetime.now() -- task_actions.py calls it exactly once, immediately
    after capturing expected_status and before building the UPDATE. The
    function body executed is completely unmodified."""
    session = SessionLocal()
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
        req = TaskActionReq(action=action, actor=f"reviewer-{name}", comment=f"guard verification: {name}")
        try:
            response = perform_action(task_id=task_id, req=req, db=session, _=_fake_actor)
            outcomes[name] = ("ok", response["status"])
        except HTTPException as exc:
            outcomes[name] = ("conflict", exc.status_code, exc.detail)
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

print("perform_action() outcome seen by each caller:")
for name, outcome in outcomes.items():
    print(f"  {name}: {outcome}")

db = SessionLocal()
final_task = db.query(Task).filter(Task.id == task_id).first()
actions = db.query(TaskAction).filter(TaskAction.task_id == task_id).order_by(TaskAction.id).all()
print(f"\nFinal Task.status in the database: {final_task.status!r}")
print(f"TaskAction rows recorded ({len(actions)} -- only the winning decision is recorded,"
      f" the loser's action never committed):")
for a in actions:
    print(f"  - action={a.action!r} actor={a.actor!r}")
db.close()

# ---- assertions: prove the race is actually closed ----
ok_results = [(n, o) for n, o in outcomes.items() if o[0] == "ok"]
conflict_results = [(n, o) for n, o in outcomes.items() if o[0] == "conflict"]

assert len(ok_results) == 1, f"expected exactly 1 successful commit, got {len(ok_results)}: {ok_results}"
assert len(conflict_results) == 1, f"expected exactly 1 conflict, got {len(conflict_results)}: {conflict_results}"

winner_name, (_, winner_status) = ok_results[0]
loser_name, (_, status_code, detail) = conflict_results[0]

assert status_code == 409, f"expected HTTP 409 for the losing caller, got {status_code}"
assert final_task.status == winner_status, (
    f"final DB status {final_task.status!r} does not match the winning caller's "
    f"reported status {winner_status!r} -- status is not deterministic"
)
assert len(actions) == 1, f"expected exactly 1 TaskAction row (only the winner's), got {len(actions)}"
assert actions[0].actor == f"reviewer-{winner_name}", (
    f"the recorded TaskAction actor ({actions[0].actor!r}) does not match the "
    f"winning caller ({winner_name!r})"
)

print(f"\nPASS: exactly one commit succeeded ({winner_name} -> {winner_status!r}), "
      f"the other ({loser_name}) received an explicit 409 conflict, and the final "
      f"status is deterministic and matches the winner.")
