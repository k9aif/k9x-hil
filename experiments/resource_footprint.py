"""
Resource-footprint experiment: process/thread/memory at increasing
pending-task counts, and GET /api/tasks latency at each count.

Seeds a real user, mints a real JWT via create_access_token(), bulk-
inserts pending tasks directly (bypassing Kafka, which is orthogonal
to what this measures), and calls the real GET /api/tasks endpoint
over HTTP against an actually-running uvicorn process. Reports the
server process's memory and thread count (read via macOS `top` --
adapt read_proc_stats() for `ps`/`/proc` on Linux) at each task count.

Usage:
    # 1. Start a disposable local Postgres, create the k9hil schema
    #    (see cas_race_condition.py's docstring for the exact commands).
    # 2. In one terminal, start the real server against it:
    POSTGRES_HOST=localhost POSTGRES_PORT=5432 POSTGRES_DB=k9x \
        POSTGRES_USER=postgres POSTGRES_PASSWORD=<yours> \
        JWT_SECRET_KEY=<any-32+-char-string> \
        python -m uvicorn main:app --host 127.0.0.1 --port 18000
    # 3. In another terminal, with the same POSTGRES_*/JWT_SECRET_KEY
    #    env vars exported, run this script with that server's PID:
    python experiments/resource_footprint.py <uvicorn_pid>
"""
import os
import subprocess
import sys
import time

import requests
from backend.database import SessionLocal
from backend.models import Project, Application, Queue, Task, User
from backend.auth import create_access_token

SERVER_PID = sys.argv[1] if len(sys.argv) > 1 else None
BASE_URL = "http://127.0.0.1:18000"


def read_proc_stats(pid):
    out = subprocess.run(
        ["top", "-pid", str(pid), "-l", "1", "-stats", "pid,mem,threads"],
        capture_output=True, text=True,
    ).stdout
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] == str(pid):
            return {"mem": parts[1], "threads": parts[2]}
    return {"mem": "?", "threads": "?"}


db = SessionLocal()
proj = Project(name="Footprint-Experiment-Project")
db.add(proj); db.commit(); db.refresh(proj)
app = Application(project_id=proj.id, name="Footprint-Experiment-App")
db.add(app); db.commit(); db.refresh(app)
queue = Queue(application_id=app.id, name="Footprint-Experiment-Queue", topic="footprint.experiment.topic")
db.add(queue); db.commit(); db.refresh(queue)

user = User(name="Experiment User", email="experiment@local", role="admin", is_active=True)
db.add(user); db.commit(); db.refresh(user)
token = create_access_token(user)
queue_id = queue.id
db.close()

headers = {"Authorization": f"Bearer {token}"}

print(f"{'pending tasks':>14} | {'RSS':>8} | {'threads':>7} | {'/tasks latency (s)':>18} | {'/tasks HTTP':>11}")
print("-" * 72)

increments = (0, 100, 900, 4000)  # cumulative totals: 0, 100, 1000, 5000
cumulative = 0
for delta in increments:
    if delta > 0:
        db = SessionLocal()
        db.bulk_insert_mappings(Task, [
            {"queue_id": queue_id, "title": f"Footprint task {i}", "status": "pending"}
            for i in range(delta)
        ])
        db.commit()
        db.close()
    cumulative += delta

    time.sleep(0.5)  # let the process settle

    t0 = time.monotonic()
    resp = requests.get(f"{BASE_URL}/api/tasks", headers=headers, params={"status": "pending"}, timeout=30)
    elapsed = time.monotonic() - t0

    stats_after = read_proc_stats(SERVER_PID)
    print(f"{cumulative:>14} | {stats_after['mem']:>8} | {stats_after['threads']:>7} | {elapsed:>18.3f} | {resp.status_code:>11}")
