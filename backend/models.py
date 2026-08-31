import os
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Table, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.database import Base

_SCHEMA = os.getenv("POSTGRES_SCHEMA", "k9hil")


# ── Many-to-many: users ↔ applications ───────────────────────────────────────

user_applications = Table(
    "user_applications", Base.metadata,
    Column("user_id", Integer, ForeignKey(f"{_SCHEMA}.users.id", ondelete="CASCADE")),
    Column("application_id", Integer, ForeignKey(f"{_SCHEMA}.applications.id", ondelete="CASCADE")),
    schema=_SCHEMA,
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": _SCHEMA}

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(255), nullable=False)
    email         = Column(String(255), unique=True, nullable=False)
    role          = Column(String(20), default="worker")
    department    = Column(String(255))
    team          = Column(String(255))
    password_hash = Column(String(255))
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, server_default=func.now())

    applications = relationship("Application", secondary=user_applications, back_populates="users")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = {"schema": _SCHEMA}

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    created_at  = Column(DateTime, server_default=func.now())

    applications = relationship("Application", back_populates="project")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = {"schema": _SCHEMA}

    id          = Column(Integer, primary_key=True, index=True)
    project_id  = Column(Integer, ForeignKey(f"{_SCHEMA}.projects.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(255), nullable=False)
    description = Column(Text)
    created_at  = Column(DateTime, server_default=func.now())

    project = relationship("Project", back_populates="applications")
    queues  = relationship("Queue", back_populates="application")
    users   = relationship("User", secondary=user_applications, back_populates="applications")


class Queue(Base):
    __tablename__ = "queues"
    __table_args__ = {"schema": _SCHEMA}

    id             = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey(f"{_SCHEMA}.applications.id", ondelete="CASCADE"), nullable=False)
    name           = Column(String(255), nullable=False)
    description    = Column(Text)
    topic          = Column(String(255), unique=True, nullable=False)
    ttl_hours      = Column(Integer)
    ttl_action     = Column(String(20))
    pii            = Column(Boolean, default=False)
    created_at     = Column(DateTime, server_default=func.now())

    application = relationship("Application", back_populates="queues")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = {"schema": _SCHEMA}

    id                   = Column(Integer, primary_key=True, index=True)
    queue_id             = Column(Integer, ForeignKey(f"{_SCHEMA}.queues.id"))
    title                = Column(String(500), nullable=False)
    description          = Column(Text)
    source_orchestrator  = Column(String(255))
    source_topic         = Column(String(255))
    reply_to             = Column(String(255))
    correlation_id       = Column(String(255))
    status               = Column(String(20), default="pending")
    priority             = Column(String(20), default="medium")
    assigned_to          = Column(String(255))
    payload              = Column(JSON)
    result               = Column(JSON)
    artifacts            = Column(JSON)
    jira_ticket          = Column(String(500))
    pii                  = Column(Boolean, default=False)
    pii_fields           = Column(JSON)
    ttl_hours            = Column(Integer)
    ttl_action           = Column(String(20))
    due_date             = Column(DateTime)
    created_at           = Column(DateTime, server_default=func.now())
    updated_at           = Column(DateTime, server_default=func.now(), onupdate=func.now())
    completed_at         = Column(DateTime)


class TaskAction(Base):
    __tablename__ = "task_actions"
    __table_args__ = {"schema": _SCHEMA}

    id         = Column(Integer, primary_key=True, index=True)
    task_id    = Column(Integer, ForeignKey(f"{_SCHEMA}.tasks.id", ondelete="CASCADE"), nullable=False)
    action     = Column(String(50), nullable=False)
    actor      = Column(String(255))
    comment    = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
