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
        # Demo user -- a manager, so a reviewer trying the demo can decide any
        # open task (including escalated ones), not only the few assigned to
        # them. As a worker it could act on almost nothing in the seeded data.
        if not db.query(User).filter(User.email == "demo@k9x.ai").first():
            db.add(User(name="Demo User", email="demo@k9x.ai", role="manager",
                        department="Demo", team="Demo",
                        password_hash=hashlib.sha256(b"demo").hexdigest()))
        # Admin user
        if not db.query(User).filter(User.email == "admin@k9x.ai").first():
            db.add(User(name="Admin", email="admin@k9x.ai", role="admin",
                        department="Platform Engineering", team="k9x",
                        password_hash=hashlib.sha256(b"admin123").hexdigest()))
        db.commit()

        # ── Projects ────────────────────────────────────────────────
        if not db.query(Project).filter(Project.name == "Demo").first():
            db.add(Project(name="Demo", description="Demonstration project — insurance document processing pipeline"))
        if not db.query(Project).filter(Project.name == "K9 Platform").first():
            db.add(Project(name="K9 Platform", description="K9-AIF framework and ecosystem platform services"))
        if not db.query(Project).filter(Project.name == "DAS").first():
            db.add(Project(name="DAS", description="Defense Acquisition System — DoDAF/JCIDS/Acquisition/SE reference pipeline"))
        db.commit()

        demo_proj = db.query(Project).filter(Project.name == "Demo").first()
        k9_proj   = db.query(Project).filter(Project.name == "K9 Platform").first()
        das_proj  = db.query(Project).filter(Project.name == "DAS").first()

        # ── Applications ─────────────────────────────────────────────
        apps_data = [
            dict(project_id=demo_proj.id, name="EOC",
                 description="Evidence of Coverage — multi-agent insurance claim extraction and validation"),
            dict(project_id=demo_proj.id, name="Document Verification",
                 description="OCR extraction verification for insurance documents"),
            dict(project_id=k9_proj.id, name="Architecture Review",
                 description="SBB promotion and architecture pattern governance"),
            dict(project_id=das_proj.id, name="JCIDS",
                 description="Joint Capabilities Integration and Development System pipeline"),
        ]
        for a in apps_data:
            if not db.query(Application).filter(Application.name == a["name"], Application.project_id == a["project_id"]).first():
                db.add(Application(**a))
        db.commit()

        claims_app = db.query(Application).filter(Application.name == "EOC").first()
        docver_app = db.query(Application).filter(Application.name == "Document Verification").first()
        archrev_app = db.query(Application).filter(Application.name == "Architecture Review").first()
        jcids_app   = db.query(Application).filter(Application.name == "JCIDS").first()

        # ── Assign users to applications ─────────────────────────────
        james = db.query(User).filter(User.email == "james.park@k9x.ai").first()
        sarah = db.query(User).filter(User.email == "sarah.chen@k9x.ai").first()
        maria = db.query(User).filter(User.email == "maria.silva@k9x.ai").first()
        ravi  = db.query(User).filter(User.email == "ravinatarajan@k9x.ai").first()
        demo  = db.query(User).filter(User.email == "demo@k9x.ai").first()
        admin = db.query(User).filter(User.email == "admin@k9x.ai").first()

        if james and claims_app not in james.applications:
            james.applications.extend([claims_app, docver_app])
        if sarah and claims_app not in sarah.applications:
            sarah.applications.extend([claims_app, docver_app])
        if maria and archrev_app not in maria.applications:
            maria.applications.append(archrev_app)
        if ravi:
            for app in [claims_app, docver_app, archrev_app, jcids_app]:
                if app not in ravi.applications:
                    ravi.applications.append(app)
        if demo:
            for app in [claims_app, docver_app, archrev_app, jcids_app]:
                if app not in demo.applications:
                    demo.applications.append(app)
        if admin:
            for app in [claims_app, docver_app, archrev_app, jcids_app]:
                if app not in admin.applications:
                    admin.applications.append(app)
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
            dict(application_id=jcids_app.id, name="JROC Review",
                 description="JROC-VALIDATION gate: program manager or JROC representative "
                             "reviews the assembled capability-gap review package before "
                             "the pipeline may proceed to Acquisition.",
                 topic="workflow.hil.das.jroc",
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
                 artifacts=["s3://k9x-eoc-documents/DOC-9921/source.pdf"],
                 jira_ticket="EOC-142 (placeholder -- no live Jira integration yet)",
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

        # ── Process Studio Implementations / accounts_payable ──────────
        # Registration only — deliberately no example Tasks. The generated
        # HILAgent in this scaffold isn't wired to actually publish Tasks
        # yet (it's a dead, unwired LLM-call stub as of 2026-09-19), so
        # seeding fake Task rows here would misrepresent real system state.
        # This app should show 0 active until that wiring is built for real.
        if not db.query(Project).filter(Project.name == "Process Studio Implementations").first():
            db.add(Project(name="Process Studio Implementations",
                            description="Real implementations built from IBM Process Studio blueprints via K9X Studio — see github.com/k9aif/k9x-process-studio-implementations"))
        db.commit()

        psi_proj = db.query(Project).filter(Project.name == "Process Studio Implementations").first()

        if not db.query(Application).filter(Application.name == "accounts_payable", Application.project_id == psi_proj.id).first():
            db.add(Application(project_id=psi_proj.id, name="accounts_payable",
                                description="Accounts Payable & Expense Reimbursements — 7 use cases, Zero Trust + k9x_Shield + Guardian verified live on each"))
        db.commit()

        ap_app = db.query(Application).filter(Application.name == "accounts_payable", Application.project_id == psi_proj.id).first()

        ap_queues_data = [
            dict(application_id=ap_app.id, name="Matching Exceptions",
                 description="ATS4 — AP Specialist validates the agent's recommended resolution for a PO/invoice matching exception.",
                 topic="workflow.hil.processstudio.accountspayable.matching-exceptions",
                 ttl_hours=168, ttl_action="reject"),
            dict(application_id=ap_app.id, name="GL Coding Review",
                 description="ATS5 — AP Specialist verifies ambiguous GL account codes the agent couldn't classify above the 94% confidence gate.",
                 topic="workflow.hil.processstudio.accountspayable.gl-coding",
                 ttl_hours=168, ttl_action="reject"),
            dict(application_id=ap_app.id, name="Anomaly Review",
                 description="ATS6 — AP Manager + Internal Audit review a RED-scored invoice flagged by the anomaly detection loop; always blocks auto-payment.",
                 topic="workflow.hil.processstudio.accountspayable.anomaly-review",
                 ttl_hours=72, ttl_action="escalate"),
            dict(application_id=ap_app.id, name="Expense Policy Review",
                 description="ATS12 — Finance Manager reviews an expense report flagged for a policy violation.",
                 topic="workflow.hil.processstudio.accountspayable.expense-audit",
                 ttl_hours=168, ttl_action="reject"),
            dict(application_id=ap_app.id, name="Vendor Master Verification",
                 description="ATS13 — AP Supervisor independently verifies a vendor master change, especially bank detail updates.",
                 topic="workflow.hil.processstudio.accountspayable.vendor-master",
                 ttl_hours=168, ttl_action="reject"),
        ]
        for q in ap_queues_data:
            if not db.query(Queue).filter(Queue.topic == q["topic"]).first():
                db.add(Queue(**q))
        db.commit()

        # Missed on the first pass: every other app in this file assigns
        # itself to ravi/demo/admin's .applications (that's what makes it
        # show up in the sidebar's PROJECT tree and in their login response's
        # "applications" list) — accounts_payable wasn't, so it never
        # appeared there even though it correctly showed up in Queue Summary
        # (which queries Queue/Task directly, unfiltered by user).
        if ravi and ap_app not in ravi.applications:
            ravi.applications.append(ap_app)
        if demo and ap_app not in demo.applications:
            demo.applications.append(ap_app)
        if admin and ap_app not in admin.applications:
            admin.applications.append(ap_app)
        db.commit()
    finally:
        db.close()
