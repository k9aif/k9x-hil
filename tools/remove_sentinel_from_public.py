"""One-off: remove K9X Sentinel's data from the PUBLIC k9x-hil database.

Sentinel's queue moved to the internal instance (HIL_PROFILE=internal); the
public database still holds the old K9X Sentinel application, its Security
tasks queue and tasks, and the ravinatarajan account (deactivated, not
deleted, so the task history that names it stays intact).

Runs inside the public container, with its connection settings:
    sudo podman exec -i k9x-hil python - < tools/remove_sentinel_from_public.py            # preview
    sudo podman exec -i -e APPLY=1 k9x-hil python - < tools/remove_sentinel_from_public.py # apply
Refuses to run on the internal instance."""

import os
import sys

sys.path.insert(0, "/app")
from sqlalchemy import text  # noqa: E402
from backend.database import engine, SCHEMA  # noqa: E402

if os.getenv("HIL_PROFILE", "public").strip().lower() == "internal":
    sys.exit("This is the internal instance; nothing to do here.")

APPLY = os.getenv("APPLY") == "1"
TOPIC = "hil.requests.framework_security_updates"
S = SCHEMA

with engine.connect() as c:
    tx = c.begin()
    q = c.execute(text(f"SELECT id, application_id FROM {S}.queues WHERE topic = :t"), {"t": TOPIC}).fetchall()
    queue_ids = [r[0] for r in q]
    app_ids = [r[0] for r in c.execute(text(f"SELECT id FROM {S}.applications WHERE name = 'K9X Sentinel'")).fetchall()]
    tasks = c.execute(text(f"SELECT id, title FROM {S}.tasks WHERE queue_id = ANY(:q)"), {"q": queue_ids}).fetchall() if queue_ids else []
    print(f"schema {S}  ({'APPLY' if APPLY else 'preview, nothing changed'})")
    print(f"  K9X Sentinel application(s): {app_ids}")
    print(f"  Security tasks queue(s):     {queue_ids}")
    print(f"  tasks: {len(tasks)}")
    for t in tasks:
        print(f"    #{t[0]} {t[1][:80]}")

    if tasks:
        c.execute(text(f"DELETE FROM {S}.tasks WHERE queue_id = ANY(:q)"), {"q": queue_ids})   # actions + outbox cascade
    if queue_ids:
        c.execute(text(f"DELETE FROM {S}.queues WHERE id = ANY(:q)"), {"q": queue_ids})
    if app_ids:
        c.execute(text(f"DELETE FROM {S}.applications WHERE id = ANY(:a)"), {"a": app_ids})  # memberships cascade
    n = c.execute(text(f"UPDATE {S}.users SET is_active = false WHERE email = 'ravinatarajan@k9x.ai' AND is_active")).rowcount
    print(f"  ravinatarajan@k9x.ai deactivated: {n}")

    if APPLY:
        tx.commit()
        print("Committed.")
    else:
        tx.rollback()
        print("Rolled back. Run again with -e APPLY=1 to apply.")
