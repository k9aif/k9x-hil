"""Who may decide a task (1.3.0).

A producer names the minimum HIL role that may decide its task
(``required_role`` in the task message, else the queue's ``required_role``)
and, as a label, the authority that decides (``decision_authority``, e.g.
"Milestone Decision Authority"). A terminal decision (complete / reject)
by a user whose role ranks below that is refused with 403. The decider is
always the authenticated user, never a name sent by the client.

Before 1.3.0 any authenticated user could decide any task, and the actor
recorded with a decision was whatever the client sent.
"""

from typing import Optional

ROLE_RANK = {"worker": 1, "manager": 2, "admin": 3}
DECISION_ACTIONS = {"complete", "reject"}


class DecisionNotAuthorized(Exception):
    """The user's role is below the role the task requires for a decision."""


def required_role(task) -> Optional[str]:
    role = (task.required_role or "").strip().lower() or None
    if role is not None and role not in ROLE_RANK:
        raise ValueError(f"Task {task.id} names unknown required_role {task.required_role!r}")
    return role


def check_may_decide(user, task, action: str) -> None:
    """Raise DecisionNotAuthorized when ``user`` may not take ``action`` on ``task``."""
    if action not in DECISION_ACTIONS:
        return
    needed = required_role(task)
    if needed is None:
        return
    have = ROLE_RANK.get((user.role or "").lower(), 0)
    if have < ROLE_RANK[needed]:
        authority = f" ({task.decision_authority})" if task.decision_authority else ""
        raise DecisionNotAuthorized(
            f"Task {task.id} must be decided by role {needed!r} or above{authority}; "
            f"{user.email} has role {user.role!r}")
