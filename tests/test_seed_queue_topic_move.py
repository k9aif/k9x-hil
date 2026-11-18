#!/usr/bin/env python3
"""k9x-hil 1.5.0 -- Invoice Approvals moves from workflow.hil.openai.ap-payments to hil.requests.openai-ap-payments.

Property: seeding an instance that has the old topic moves that queue in place and starts; it never inserts a
second queue with the same topic (queues_topic_key). Found live: with autoflush off, the move wasn't flushed before
the existence check, so the seed inserted a duplicate and the app failed to start.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import backend.seed as seed  # noqa: E402
from backend.models import Base, Queue  # noqa: E402

OLD, NEW = "workflow.hil.openai.ap-payments", "hil.requests.openai-ap-payments"


def test_old_topic_is_moved_in_place(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _attach(conn, _):
        conn.execute("ATTACH DATABASE ':memory:' AS k9hil")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)   # as backend.database
    monkeypatch.setattr(seed, "SessionLocal", Session)

    seed.seed_catalog(samples=False)
    s = Session()
    s.query(Queue).filter(Queue.topic == NEW).one().topic = OLD    # an instance seeded by the first 1.5.0
    s.commit()

    seed.seed_catalog(samples=False)                                 # used to raise IntegrityError here
    assert s.query(Queue).filter(Queue.topic == NEW).count() == 1
    assert s.query(Queue).filter(Queue.topic == OLD).count() == 0
    assert s.query(Queue).filter(Queue.name == "Invoice Approvals").count() == 1


def test_openai_app_moves_under_demo(monkeypatch):
    """An instance seeded with the separate "OpenAI Demo" project: its application (and queue) move under Demo in
    place, the emptied project is removed, and nothing is duplicated."""
    from backend.models import Application, Project

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _attach(conn, _):
        conn.execute("ATTACH DATABASE ':memory:' AS k9hil")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(seed, "SessionLocal", Session)
    seed.seed_catalog(samples=False)

    s = Session()                                                    # rebuild the earlier layout
    old = Project(name=seed.OPENAI_PROJECT, description="old")
    s.add(old)
    s.flush()
    app = s.query(Application).filter(Application.name == "OpenAI Demo Application").one()
    app.project_id = old.id
    s.commit()
    app_id, queue_id = app.id, s.query(Queue).filter(Queue.topic == NEW).one().id

    seed.seed_catalog(samples=False)
    s.expire_all()
    demo = s.query(Project).filter(Project.name == "Demo").one()
    apps = s.query(Application).filter(Application.name == "OpenAI Demo Application").all()
    assert [a.id for a in apps] == [app_id] and apps[0].project_id == demo.id
    assert s.query(Project).filter(Project.name == seed.OPENAI_PROJECT).count() == 0
    assert s.query(Queue).filter(Queue.topic == NEW).one().id == queue_id
    assert demo.description == seed.DEMO_DESCRIPTION
