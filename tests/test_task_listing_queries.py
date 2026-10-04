#!/usr/bin/env python3
"""GET /tasks issues a fixed number of queries, not one per task.

The resource-footprint experiment (experiments/resource_footprint.py) found
the listing loading each task's queue separately (N+1). list_tasks() now
loads the page's queues and their applications in one query. This counts
the SELECTs for 3 and for 30 tasks and checks they are the same.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.models import Application, Base, Project, Queue, Task
from backend.routes import list_tasks

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL:", msg)


def _db(n_tasks):
    engine = create_engine("sqlite:///:memory:")
    engine = engine.execution_options(schema_translate_map={"k9hil": None})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    p = Project(name="P"); db.add(p); db.flush()
    a = Application(project_id=p.id, name="DAS"); db.add(a); db.flush()
    qs = [Queue(application_id=a.id, name=f"Q{i}", topic=f"t{i}") for i in range(3)]
    db.add_all(qs); db.flush()
    db.add_all([Task(queue_id=qs[i % 3].id, title=f"T{i}") for i in range(n_tasks)])
    db.commit()
    db.expunge_all()
    return engine, db


def _selects(n_tasks):
    engine, db = _db(n_tasks)
    count = [0]
    event.listen(engine, "before_cursor_execute",
                 lambda *a, **k: count.__setitem__(0, count[0] + (a[2].lstrip().upper().startswith("SELECT"))))
    rows = list_tasks(status=None, assigned_to=None, application_id=None, queue_id=None, db=db, _=None)
    check(len(rows) == n_tasks, f"expected {n_tasks} rows, got {len(rows)}")
    check(all(r["queue_name"] and r["application_name"] == "DAS" for r in rows), "queue/application names missing")
    return count[0]


def test_listing_query_count_does_not_grow_with_tasks():
    small, large = _selects(3), _selects(30)
    check(small == large, f"SELECT count grows with tasks: {small} for 3, {large} for 30")
    check(large <= 3, f"expected at most 3 SELECTs, got {large}")


if __name__ == "__main__":
    test_listing_query_count_does_not_grow_with_tasks()
    print("OK" if not failures else f"{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)
