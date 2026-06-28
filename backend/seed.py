from datetime import datetime, timezone, timedelta
from backend.database import SessionLocal
from backend.models import User, Project, Application, Queue, Task, TaskAction
import hashlib


def seed():
    db = SessionLocal()
    try:
        # ── Users ────────────────────────────────────────────────────
        users = [
            dict(name="Ravi Natarajan", email="ravinatarajan@k9x.ai", role="admin",
                 department="Platform Engineering", team="k9x"),
            dict(name="Sarah Chen", email="sarah.chen@k9x.ai", role="manager",
                 department="Claims Processing", team="Insurance Ops"),
            dict(name="James Park", email="james.park@k9x.ai", role="worker",
                 department="Claims Processing", team="Insurance Ops"),
            dict(name="Maria Silva", email="maria.silva@k9x.ai", role="worker",
                 department="Architecture", team="Enterprise Architecture"),
        ]
        for u in users:
            if not db.query(User).filter(User.email == u["email"]).first():
                db.add(User(**u, password_hash=hashlib.sha256(b"changeme").hexdigest()))
        # Demo user
        if not db.query(User).filter(User.email == "demo@k9x.ai").first():
            db.add(User(name="Demo User", email="demo@k9x.ai", role="worker",
                        department="Demo", team="Demo",
                        password_hash=hashlib.sha256(b"demo").hexdigest()))
        db.commit()

        # ── Projects ────────────────────────────────────────────────
        if not db.query(Project).filter(Project.name == "Demo").first():
            db.add(Project(name="Demo", description="Demonstration project — insurance document processing pipeline"))
        if not db.query(Project).filter(Project.name == "K9 Platform").first():
            db.add(Project(name="K9 Platform", description="K9-AIF framework and ecosystem platform services"))
        db.commit()

        demo_proj = db.query(Project).filter(Project.name == "Demo").first()
        k9_proj   = db.query(Project).filter(Project.name == "K9 Platform").first()

        # ── Applications ─────────────────────────────────────────────
        apps_data = [
            dict(project_id=demo_proj.id, name="EOC",
                 description="Evidence of Coverage — multi-agent insurance claim extraction and validation"),
            dict(project_id=demo_proj.id, name="Document Verification",
                 description="OCR extraction verification for insurance documents"),
            dict(project_id=k9_proj.id, name="Architecture Review",
                 description="SBB promotion and architecture pattern governance"),
        ]
        for a in apps_data:
            if not db.query(Application).filter(Application.name == a["name"], Application.project_id == a["project_id"]).first():
                db.add(Application(**a))
        db.commit()

        claims_app = db.query(Application).filter(Application.name == "Claims Processor").first()
        docver_app = db.query(Application).filter(Application.name == "Document Verification").first()
        archrev_app = db.query(Application).filter(Application.name == "Architecture Review").first()

        # ── Assign users to applications ─────────────────────────────
        james = db.query(User).filter(User.email == "james.park@k9x.ai").first()
        sarah = db.query(User).filter(User.email == "sarah.chen@k9x.ai").first()
        maria = db.query(User).filter(User.email == "maria.silva@k9x.ai").first()
        ravi  = db.query(User).filter(User.email == "ravinatarajan@k9x.ai").first()
        demo  = db.query(User).filter(User.email == "demo@k9x.ai").first()

        if james and claims_app not in james.applications:
            james.applications.extend([claims_app, docver_app])
        if sarah and claims_app not in sarah.applications:
            sarah.applications.extend([claims_app, docver_app])
        if maria and archrev_app not in maria.applications:
            maria.applications.append(archrev_app)
        if ravi:
            for app in [claims_app, docver_app, archrev_app]:
                if app not in ravi.applications:
                    ravi.applications.append(app)
        if demo:
            for app in [claims_app, docver_app, archrev_app]:
                if app not in demo.applications:
                    demo.applications.append(app)
        db.commit()

        # ── Queues ───────────────────────────────────────────────────
        queues_data = [
            dict(application_id=claims_app.id, name="Flagged Claims",
                 description="Claims where agent confidence is below threshold",
                 topic="workflow.hil.eoc.claims.flagged",
                 ttl_hours=168, ttl_action="reject"),
            dict(application_id=claims_app.id, name="Escalations",
                 description="Claims escalated by workers needing manager review",
                 topic="workflow.hil.eoc.claims.escalated",
                 ttl_hours=72, ttl_action="escalate"),
            dict(application_id=docver_app.id, name="OCR Verification",
                 description="Documents requiring human verification of OCR extraction",
                 topic="workflow.hil.eoc.documents.ocr-verify",
                 ttl_hours=48, ttl_action="reject", pii=1),
            dict(application_id=archrev_app.id, name="SBB Promotion",
                 description="SBB promotion requests requiring architecture board approval",
                 topic="workflow.hil.k9platform.architecture.sbb-promotion",
                 ttl_hours=336, ttl_action="expire"),
            dict(application_id=archrev_app.id, name="Compliance Approval",
                 description="Regulatory compliance sign-offs for production deployment",
                 topic="workflow.hil.k9platform.architecture.compliance",
                 ttl_hours=168, ttl_action="reject"),
        ]
        for q in queues_data:
            if not db.query(Queue).filter(Queue.topic == q["topic"]).first():
                db.add(Queue(**q))
        db.commit()

        flagged_q   = db.query(Queue).filter(Queue.topic == "workflow.hil.eoc.claims.flagged").first()
        escalated_q = db.query(Queue).filter(Queue.topic == "workflow.hil.eoc.claims.escalated").first()
        ocr_q       = db.query(Queue).filter(Queue.topic == "workflow.hil.eoc.documents.ocr-verify").first()
        sbb_q       = db.query(Queue).filter(Queue.topic == "workflow.hil.k9platform.architecture.sbb-promotion").first()
        compliance_q = db.query(Queue).filter(Queue.topic == "workflow.hil.k9platform.architecture.compliance").first()

        # ── Example tasks ────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        tasks = [
            dict(queue_id=flagged_q.id,
                 title="Review flagged claim — Policy #EOC-2024-8847",
                 description="Agent confidence below threshold (0.62). Extracted coverage amount $450,000 needs human verification against source document.",
                 source_orchestrator="EOCOrchestrator", source_topic="workflow.hil.eoc.claims.flagged",
                 reply_to="workflow.eoc.hil.response",
                 correlation_id="exec-a1b2c3d4", status="pending", priority="high",
                 assigned_to="james.park@k9x.ai",
                 payload={"policy_id": "EOC-2024-8847", "confidence": 0.62, "extracted_amount": 450000, "agent": "EOCValidationAgent"},
                 ttl_hours=168, ttl_action="reject",
                 due_date=now + timedelta(hours=4)),

            dict(queue_id=ocr_q.id,
                 title="Verify extracted beneficiary data — Document #DOC-9921",
                 description="OCR extraction returned multiple possible beneficiary names. Human must confirm correct entry.",
                 source_orchestrator="DocumentOrchestrator", source_topic="workflow.hil.eoc.documents.ocr-verify",
                 reply_to="workflow.eoc.hil.response",
                 correlation_id="exec-e5f6g7h8", status="in_progress", priority="medium",
                 assigned_to="james.park@k9x.ai", pii=1, pii_fields=["payload.candidates"],
                 payload={"document_id": "DOC-9921", "candidates": ["John A. Smith", "John A. Smyth"], "agent": "DocumentExtractorAgent"},
                 ttl_hours=48, ttl_action="reject"),

            dict(queue_id=sbb_q.id,
                 title="Approve SBB promotion — ZeroTrust Orchestrator",
                 description="ZeroTrustOrchestrator SBB proposed for promotion to Enterprise shared catalog. Architecture board review required.",
                 source_orchestrator="ContinuumOrchestrator", source_topic="workflow.hil.k9platform.architecture.sbb-promotion",
                 reply_to="workflow.k9platform.hil.response",
                 correlation_id="exec-i9j0k1l2", status="pending", priority="medium",
                 assigned_to="maria.silva@k9x.ai",
                 payload={"sbb_name": "ZeroTrustOrchestrator", "current_tier": "Industry", "proposed_tier": "CommonSystems"},
                 ttl_hours=336, ttl_action="expire"),

            dict(queue_id=compliance_q.id,
                 title="Compliance sign-off — DoDAF Pipeline data handling",
                 description="DoDAF Pipeline Squad processes defense architecture documents. Compliance team must approve data handling procedures before production deployment.",
                 source_orchestrator="ComplianceOrchestrator", source_topic="workflow.hil.k9platform.architecture.compliance",
                 reply_to="workflow.k9platform.hil.response",
                 correlation_id="exec-m3n4o5p6", status="pending", priority="critical",
                 assigned_to=None,
                 payload={"project": "DoDAFPipeline", "classification": "CUI", "review_type": "data_handling"},
                 ttl_hours=168, ttl_action="reject"),

            dict(queue_id=flagged_q.id,
                 title="Review low-confidence extraction — Policy #EOC-2024-9102",
                 description="Validation loop reached max iterations without converging. Final confidence: 0.48. Human review required.",
                 source_orchestrator="EOCOrchestrator", source_topic="workflow.hil.eoc.claims.flagged",
                 reply_to="workflow.eoc.hil.response",
                 correlation_id="exec-q7r8s9t0", status="completed", priority="high",
                 assigned_to="sarah.chen@k9x.ai",
                 payload={"policy_id": "EOC-2024-9102", "confidence": 0.48, "iterations": 5},
                 result={"decision": "approved", "corrected_amount": 125000, "note": "Agent missed rider addendum on page 4"},
                 completed_at=now - timedelta(hours=2)),

            dict(queue_id=escalated_q.id,
                 title="Escalated claim — Policy #EOC-2024-7733",
                 description="Worker escalated to manager — policy language is ambiguous regarding flood coverage in zone X.",
                 source_orchestrator="EOCOrchestrator", source_topic="workflow.hil.eoc.claims.escalated",
                 reply_to="workflow.eoc.hil.response",
                 correlation_id="exec-u1v2w3x4", status="escalated", priority="high",
                 assigned_to="sarah.chen@k9x.ai",
                 payload={"policy_id": "EOC-2024-7733", "original_assignee": "james.park@k9x.ai", "reason": "Ambiguous flood coverage language"}),
        ]
        for t in tasks:
            if not db.query(Task).filter(Task.correlation_id == t["correlation_id"]).first():
                db.add(Task(**t))
        db.commit()

        # ── Task actions ─────────────────────────────────────────────
        completed = db.query(Task).filter(Task.correlation_id == "exec-q7r8s9t0").first()
        if completed and not db.query(TaskAction).filter(TaskAction.task_id == completed.id).first():
            db.add(TaskAction(task_id=completed.id, action="created", actor="system"))
            db.add(TaskAction(task_id=completed.id, action="assigned", actor="system", comment="Auto-assigned to sarah.chen@k9x.ai"))
            db.add(TaskAction(task_id=completed.id, action="started", actor="sarah.chen@k9x.ai"))
            db.add(TaskAction(task_id=completed.id, action="completed", actor="sarah.chen@k9x.ai",
                              comment="Approved with correction — agent missed rider addendum on page 4"))

        escalated = db.query(Task).filter(Task.correlation_id == "exec-u1v2w3x4").first()
        if escalated and not db.query(TaskAction).filter(TaskAction.task_id == escalated.id).first():
            db.add(TaskAction(task_id=escalated.id, action="created", actor="system"))
            db.add(TaskAction(task_id=escalated.id, action="assigned", actor="system", comment="Auto-assigned to james.park@k9x.ai"))
            db.add(TaskAction(task_id=escalated.id, action="started", actor="james.park@k9x.ai"))
            db.add(TaskAction(task_id=escalated.id, action="escalated", actor="james.park@k9x.ai",
                              comment="Ambiguous flood coverage language in zone X — needs manager review"))

        db.commit()
    finally:
        db.close()
