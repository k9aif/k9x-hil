import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import User, Project, Application, Queue, Task, TaskAction

router = APIRouter(prefix="/api")


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginReq(BaseModel):
    email: str
    password: str

@router.post("/auth/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    h = hashlib.sha256(req.password.encode()).hexdigest()
    user = db.query(User).filter(User.email == req.email, User.password_hash == h, User.is_active == True).first()
    if not user:
        raise HTTPException(401, "Invalid credentials")
    apps = [{"id": a.id, "name": a.name, "project": a.project.name, "project_id": a.project_id}
            for a in user.applications]
    return {"name": user.name, "email": user.email, "role": user.role,
            "department": user.department, "team": user.team, "applications": apps}


# ── Projects ─────────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name, "description": p.description,
             "app_count": len(p.applications)} for p in db.query(Project).all()]


# ── Applications ─────────────────────────────────────────────────────────────

@router.get("/applications")
def list_applications(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Application)
    if project_id:
        q = q.filter(Application.project_id == project_id)
    return [{"id": a.id, "name": a.name, "description": a.description,
             "project": a.project.name, "project_id": a.project_id,
             "queue_count": len(a.queues)} for a in q.all()]


@router.get("/applications/{app_id}")
def get_application(app_id: int, db: Session = Depends(get_db)):
    a = db.query(Application).filter(Application.id == app_id).first()
    if not a:
        raise HTTPException(404, "Application not found")
    queues = [{"id": q.id, "name": q.name, "description": q.description,
               "topic": q.topic, "ttl_hours": q.ttl_hours, "ttl_action": q.ttl_action,
               "pii": bool(q.pii),
               "active_count": db.query(Task).filter(Task.queue_id == q.id, Task.status.in_(["pending","in_progress"])).count()}
              for q in a.queues]
    return {"id": a.id, "name": a.name, "description": a.description,
            "project": a.project.name, "queues": queues}


# ── Queues ───────────────────────────────────────────────────────────────────

@router.get("/queues")
def list_queues(application_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Queue).order_by(Queue.name)
    if application_id:
        q = q.filter(Queue.application_id == application_id)
    result = []
    for queue in q.all():
        count = db.query(Task).filter(Task.queue_id == queue.id, Task.status.in_(["pending", "in_progress"])).count()
        result.append({"id": queue.id, "name": queue.name, "description": queue.description,
                       "topic": queue.topic, "ttl_hours": queue.ttl_hours, "ttl_action": queue.ttl_action,
                       "pii": bool(queue.pii), "active_count": count,
                       "application": queue.application.name, "application_id": queue.application_id})
    return result


# ── Tasks ────────────────────────────────────────────────────────────────────

@router.get("/tasks")
def list_tasks(status: Optional[str] = None, assigned_to: Optional[str] = None,
               application_id: Optional[int] = None, queue_id: Optional[int] = None,
               db: Session = Depends(get_db)):
    q = db.query(Task).order_by(Task.created_at.desc())
    if status:
        q = q.filter(Task.status == status)
    if assigned_to:
        q = q.filter(Task.assigned_to == assigned_to)
    if queue_id:
        q = q.filter(Task.queue_id == queue_id)
    elif application_id:
        queue_ids = [qr.id for qr in db.query(Queue).filter(Queue.application_id == application_id).all()]
        if queue_ids:
            q = q.filter(Task.queue_id.in_(queue_ids))
        else:
            return []
    return [_task_dict(t, db) for t in q.all()]


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    t = db.query(Task).filter(Task.id == task_id).first()
    if not t:
        raise HTTPException(404, "Task not found")
    actions = db.query(TaskAction).filter(TaskAction.task_id == task_id).order_by(TaskAction.created_at).all()
    d = _task_dict(t, db)
    d["actions"] = [{"id": a.id, "action": a.action, "actor": a.actor,
                     "comment": a.comment, "created_at": _iso(a.created_at)} for a in actions]
    return d


class TaskActionReq(BaseModel):
    action: str
    actor: str
    comment: Optional[str] = None
    result: Optional[dict] = None

@router.post("/tasks/{task_id}/action")
def perform_action(task_id: int, req: TaskActionReq, db: Session = Depends(get_db)):
    t = db.query(Task).filter(Task.id == task_id).first()
    if not t:
        raise HTTPException(404, "Task not found")

    now = datetime.now(timezone.utc)

    if req.action == "claim":
        t.assigned_to = req.actor
        t.status = "pending"
    elif req.action == "start":
        t.status = "in_progress"
    elif req.action == "complete":
        t.status = "completed"
        t.completed_at = now
        if req.result:
            t.result = req.result
    elif req.action == "escalate":
        t.status = "escalated"
    elif req.action == "reject":
        t.status = "rejected"
        t.completed_at = now

    t.updated_at = now
    db.add(TaskAction(task_id=task_id, action=req.action, actor=req.actor, comment=req.comment))
    db.commit()
    return {"ok": True, "status": t.status}


# ── Dashboard stats ──────────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard(application_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Task)
    if application_id:
        queue_ids = [qr.id for qr in db.query(Queue).filter(Queue.application_id == application_id).all()]
        if queue_ids:
            q = q.filter(Task.queue_id.in_(queue_ids))
        else:
            return {"total": 0, "pending": 0, "in_progress": 0, "completed": 0,
                    "escalated": 0, "rejected": 0, "critical": 0, "unassigned": 0}

    total     = q.count()
    pending   = q.filter(Task.status == "pending").count()
    active    = q.filter(Task.status == "in_progress").count()
    done      = q.filter(Task.status == "completed").count()
    escalated = q.filter(Task.status == "escalated").count()
    rejected  = q.filter(Task.status == "rejected").count()
    critical  = q.filter(Task.priority == "critical", Task.status.in_(["pending", "in_progress"])).count()
    unassigned = q.filter(Task.assigned_to == None, Task.status == "pending").count()
    return {"total": total, "pending": pending, "in_progress": active,
            "completed": done, "escalated": escalated, "rejected": rejected,
            "critical": critical, "unassigned": unassigned}


# ── Users (admin) ────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role,
             "department": u.department, "team": u.team} for u in db.query(User).all()]


def _task_dict(t, db):
    queue = db.query(Queue).filter(Queue.id == t.queue_id).first() if t.queue_id else None
    app = queue.application if queue else None
    return {"id": t.id, "title": t.title, "description": t.description,
            "source_orchestrator": t.source_orchestrator, "source_topic": t.source_topic,
            "reply_to": t.reply_to, "correlation_id": t.correlation_id,
            "status": t.status, "priority": t.priority,
            "assigned_to": t.assigned_to,
            "queue_name": queue.name if queue else None,
            "application_name": app.name if app else None,
            "application_id": app.id if app else None,
            "payload": t.payload, "result": t.result,
            "artifacts": t.artifacts, "pii": bool(t.pii), "pii_fields": t.pii_fields,
            "ttl_hours": t.ttl_hours, "ttl_action": t.ttl_action,
            "due_date": _iso(t.due_date), "created_at": _iso(t.created_at),
            "updated_at": _iso(t.updated_at), "completed_at": _iso(t.completed_at)}

def _iso(dt):
    return dt.isoformat() if dt else None
