# SPDX-License-Identifier: Apache-2.0
"""
Shared task-action logic -- the single place a task's status actually
transitions. Used by both the human-driven HTTP path
(routes.perform_action) and the automated TTL-sweep path
(ttl_sweep.sweep_expired_tasks), so a TTL-driven action and a
human-driven action apply the exact same status/audit semantics
rather than two independently-maintained copies that could drift.
"""
from datetime import datetime, timezone
from typing import Optional

from backend.models import Task, TaskAction


def apply_task_action(db, task: Task, action: str, actor: str,
                       comment: Optional[str] = None, result: Optional[dict] = None) -> str:
    """Mutate `task` per `action`, record a TaskAction, and commit.

    Returns the resulting status. Callers own the session (`db`) and
    the task's queue/db.query(Task)... lookup -- this only applies the
    transition once a specific Task row has already been found.
    """
    now = datetime.now(timezone.utc)

    if action == "claim":
        task.assigned_to = actor
        task.status = "pending"
    elif action == "start":
        task.status = "in_progress"
    elif action == "complete":
        task.status = "completed"
        task.completed_at = now
        if result:
            task.result = result
    elif action == "escalate":
        task.status = "escalated"
    elif action == "reject":
        task.status = "rejected"
        task.completed_at = now
    elif action == "expire":
        task.status = "expired"
        task.completed_at = now
    else:
        raise ValueError(f"Unknown task action: {action!r}")

    task.updated_at = now
    db.add(TaskAction(task_id=task.id, action=action, actor=actor, comment=comment))
    db.commit()
    return task.status
