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

from backend.hil_reply import publish_hil_reply
from backend.models import Task, TaskAction

_TERMINAL_DECISION_ACTIONS = {"complete", "reject", "expire"}
# "claim"/"start" aren't decisions -- someone picked the task up, nothing
# for a waiting orchestrator to resume on yet. "escalate" isn't terminal
# either -- the task stays in-flight for someone else to act on; *that*
# action, whenever it lands, is what publishes (see dashboard()'s own
# treatment of "escalated" as its own live bucket, not a completion).


class TaskConflictError(Exception):
    """Raised when a task's status changed between when the caller read
    it and when apply_task_action() tried to write the transition --
    i.e. the caller lost a race with another concurrent decision on the
    same task. The caller receives this instead of a silent no-op."""
    pass


def apply_task_action(db, task: Task, action: str, actor: str,
                       comment: Optional[str] = None, result: Optional[dict] = None) -> str:
    """Atomically transition `task` per `action`, record a TaskAction,
    and commit. Returns the resulting status.

    The write is guarded by a conditional UPDATE ... WHERE id = :id AND
    status = :expected_status, where expected_status is whatever the
    caller's copy of `task` had when this was called. If another
    transaction already changed the row's status (a concurrent
    decision on the same task), the UPDATE matches zero rows and this
    raises TaskConflictError rather than silently overwriting that
    decision -- closing the compare-and-swap gap previously disclosed
    for this endpoint.

    Callers own the session (`db`) and the task's
    db.query(Task)... lookup -- this only applies the transition once a
    specific Task row has already been found.
    """
    expected_status = task.status
    now = datetime.now(timezone.utc)
    # Captured before the write, not read back off `task` after commit --
    # avoids relying on SQLAlchemy's post-commit object-expiry behavior
    # (expire_on_commit defaults True; re-touching `task` after commit()
    # would trigger a lazy reload this function has no reason to need).
    reply_to = task.reply_to
    correlation_id = task.correlation_id

    updates = {"updated_at": now}
    if action == "claim":
        updates["assigned_to"] = actor
        updates["status"] = "pending"
    elif action == "start":
        updates["status"] = "in_progress"
    elif action == "complete":
        updates["status"] = "completed"
        updates["completed_at"] = now
        if result:
            updates["result"] = result
    elif action == "escalate":
        updates["status"] = "escalated"
    elif action == "reject":
        updates["status"] = "rejected"
        updates["completed_at"] = now
    elif action == "expire":
        updates["status"] = "expired"
        updates["completed_at"] = now
    else:
        raise ValueError(f"Unknown task action: {action!r}")

    affected = (
        db.query(Task)
        .filter(Task.id == task.id, Task.status == expected_status)
        .update(updates, synchronize_session=False)
    )
    if affected == 0:
        db.rollback()
        raise TaskConflictError(
            f"Task {task.id} was already updated since it was read "
            f"(expected status {expected_status!r}); action {action!r} rejected"
        )

    db.add(TaskAction(task_id=task.id, action=action, actor=actor, comment=comment))
    db.commit()

    if action in _TERMINAL_DECISION_ACTIONS:
        publish_hil_reply(
            reply_to=reply_to,
            correlation_id=correlation_id,
            action=action,
            actor=actor,
            status=updates["status"],
            comment=comment,
            result=result,
        )

    return updates["status"]
