#!/usr/bin/env python3
"""k9x-hil 1.3.0 -- who may decide a task.

The real route function + in-memory SQLite against the actual models; only the
Kafka producer is replaced. Proves: (1) a decision by a user whose role is
below the task's required_role is refused with 403 and changes nothing;
(2) a user with the role decides, and the decision and its reply record the
authenticated user (not the actor the client sent), their role, and the
decision authority; (3) claim/start need no role; (4) a task without
required_role keeps the old behaviour; (5) the consumer takes required_role
from the message, else from the queue.

Run directly (python3 tests/test_decision_authorization.py) or with pytest.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base, Task, TaskAction, User, Queue, Application, Project, HilReplyOutbox
from backend.routes import TaskActionReq, perform_action

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)
        failures.append(name)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _attach(conn, _):  # models live in a schema; SQLite needs it attached
        conn.execute("ATTACH DATABASE ':memory:' AS k9hil")

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code, self.text = status_code, text


def _post(db, user, task_id, body):
    """The /api/tasks/{id}/action route, called as FastAPI would call it."""
    try:
        out = perform_action(task_id, TaskActionReq(**body), db=db, user=user)
        return _Resp(200, str(out))
    except HTTPException as exc:
        return _Resp(exc.status_code, str(exc.detail))


def _task(db, required_role=None, authority=None):
    t = Task(title="Milestone A", status="pending", reply_to="workflow.hil.das.milestone-a.reply",
             correlation_id=f"JOB-1-ms-a-{required_role}", required_role=required_role,
             decision_authority=authority)
    db.add(t)
    db.commit()
    return t


def _users(db):
    worker = User(name="W", email="worker@k9x.ai", role="worker")
    manager = User(name="M", email="mda@k9x.ai", role="manager")
    db.add_all([worker, manager])
    db.commit()
    return worker, manager


def test_decision_needs_the_required_role():
    db = _session()
    worker, manager = _users(db)
    t = _task(db, "manager", "Milestone Decision Authority")
    with patch("backend.task_actions.attempt_publish", lambda db, row: True):
        r = _post(db, worker, t.id, {"action": "complete", "actor": "mda@k9x.ai"})
        check("worker deciding a manager task -> 403", r.status_code == 403, r.text)
        db.refresh(t)
        check("refused decision changes nothing", t.status == "pending", t.status)
        check("no reply queued for a refused decision", db.query(HilReplyOutbox).count() == 0)

        r = _post(db, worker, t.id, {"action": "claim"})
        check("claim needs no role", r.status_code == 200, r.text)

        r = _post(db, manager, t.id, {"action": "complete", "actor": "someone-else@k9x.ai"})
        check("manager decides", r.status_code == 200, r.text)
    db.refresh(t)
    check("task completed", t.status == "completed", t.status)
    last = db.query(TaskAction).filter(TaskAction.task_id == t.id).order_by(TaskAction.id.desc()).first()
    check("recorded actor is the authenticated user, not the client's", last.actor == "mda@k9x.ai", last.actor)
    reply = db.query(HilReplyOutbox).one().event
    check("reply carries actor, role and authority",
          reply["actor"] == "mda@k9x.ai" and reply["actor_role"] == "manager"
          and reply["decision_authority"] == "Milestone Decision Authority", str(reply))


def test_task_without_required_role_keeps_old_behaviour():
    db = _session()
    worker, _ = _users(db)
    t = _task(db, None)
    with patch("backend.task_actions.attempt_publish", lambda db, row: True):
        r = _post(db, worker, t.id, {"action": "reject"})
    check("any authenticated user decides a task with no required_role", r.status_code == 200, r.text)


def test_consumer_takes_required_role_from_message_then_queue():
    from backend import kafka_consumer
    db = _session()
    p = Project(name="P"); db.add(p); db.commit()
    a = Application(project_id=p.id, name="DAS"); db.add(a); db.commit()
    q = Queue(application_id=a.id, name="MS A", topic="workflow.hil.das.milestone-a", required_role="manager")
    db.add(q); db.commit()
    with patch.object(kafka_consumer, "SessionLocal", lambda: db), patch.object(db, "close", lambda: None):
        kafka_consumer._ingest_message(q.topic, {"title": "t1", "correlation_id": "c1",
                                                 "decision_authority": "Milestone Decision Authority"})
        kafka_consumer._ingest_message(q.topic, {"title": "t2", "correlation_id": "c2", "required_role": "admin"})
    t1 = db.query(Task).filter(Task.correlation_id == "c1").one()
    t2 = db.query(Task).filter(Task.correlation_id == "c2").one()
    check("queue default applies", t1.required_role == "manager" and
          t1.decision_authority == "Milestone Decision Authority", f"{t1.required_role} {t1.decision_authority}")
    check("message overrides queue", t2.required_role == "admin", t2.required_role)


def main():
    for fn in (test_decision_needs_the_required_role, test_task_without_required_role_keeps_old_behaviour,
               test_consumer_takes_required_role_from_message_then_queue):
        print(fn.__name__)
        fn()
    if failures:
        print(f"{len(failures)} check(s) failed", file=sys.stderr)
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
