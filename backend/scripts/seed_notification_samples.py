"""
Module: scripts.seed_notification_samples

Gives one seeded person a notification for every target kind a notification can open (record, Delivery status, project,
project members, organisation, organisation files, policy, report run, security preferences, server files, a message with
no page, a project's Compliance page, a Compliance standard), so the bell and the email link have one of each to open.

Responsibilities:
- `seed_notification_samples`: writes the rows for one user, each pointing at a real record of the seeded organisation and
  project, and reports kinds it could not seed because the dataset has no such record.

Design decisions:
- Rows are written directly: the API creates notifications only as an event side effect and several kinds (a full disk, a
  changed password) cannot be caused harmlessly. Each row carries the real `type`, `entity_type` and `entity_id`.
- It is a separate helper called after the seed, for a user dedicated to it, so tests counting a persona's notifications
  are undisturbed.

Dependencies: the `app` package (session, `Notification`, pointed-at records); the backend directory is added to the import path.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def seed_notification_samples(user_email: str, organization_id: str, project_id: str) -> list[str]:
    """Writes one notification per target kind for a user.

    Args:
        user_email: The recipient; must already exist.
        organization_id: The seeded organisation (its policy, report run and standard are used when present).
        project_id: The seeded project (its stage and a requirement are used).

    Returns:
        The target kinds that could not be seeded because the dataset has no record for them.

    Raises:
        LookupError: If the user does not exist.
    """
    import uuid

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.generated_report import GeneratedReport
    from app.models.notification import Notification
    from app.models.policy import PolicyDocument
    from app.models.project import ProjectStage
    from app.models.requirement import Requirement
    from app.models.user import User
    from app.modules.compliance.models import ComplianceStandard

    org_id, proj_id = uuid.UUID(organization_id), uuid.UUID(project_id)
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == user_email))
        if user is None:
            raise LookupError(f"No user {user_email!r} to give sample notifications to.")
        stage = db.scalar(select(ProjectStage).where(ProjectStage.project_id == proj_id))
        requirement = db.scalar(select(Requirement).where(Requirement.project_id == proj_id))
        policy = db.scalar(select(PolicyDocument).where(PolicyDocument.organization_id == org_id))
        report = db.scalar(select(GeneratedReport).where(GeneratedReport.organization_id == org_id))
        standard = db.scalar(select(ComplianceStandard).where(ComplianceStandard.organization_id == org_id))

        # (target kind, type, title, project, entity type, entity id) — `None` for the entity means the record is absent.
        rows: list[tuple[str, str, str, uuid.UUID | None, str | None, str | None, bool]] = [
            ("record", "comment_added", "New comment on a followed requirement", proj_id, "requirement",
             str(requirement.id) if requirement else None, requirement is not None),
            ("delivery_status", "stage_phase_overdue", "A stage phase is overdue", proj_id, "project_stage",
             str(stage.id) if stage else None, stage is not None),
            ("project", "project_joined", "You were added to a project", proj_id, None, None, True),
            ("project_members", "project_members_changed_by_org", "Project members were changed", proj_id, "user", None, True),
            ("organization", "permission_granted", "Organisation permission granted", None, "organization", str(org_id), True),
            ("organization_files", "storage_limit_near", "Organisation file storage is nearly full", None,
             "organization", str(org_id), True),
            ("policy", "policy_published", "Policy published", None, "policy", str(policy.id) if policy else None, policy is not None),
            ("report_run", "report_run_finished", "A background report is ready", report.project_id if report else None,
             "generated_report", str(report.id) if report else None, report is not None),
            ("preferences_security", "password_changed", "Your password was changed", None, None, None, True),
            ("server_files", "system_storage_alert", "Server file storage is nearly full", None, None, None, True),
            ("detail", "system_announcement", "Planned maintenance", None, "announcement", None, True),
            ("project_compliance", "compliance_assignment_created", "New compliance assignment", proj_id,
             "project_compliance", None, True),
            ("standard", "compliance_review_due", "Compliance review due soon: Annual", None, "compliance_standard",
             str(standard.id) if standard else None, standard is not None),
        ]
        skipped: list[str] = []
        now = datetime.now(UTC)
        for index, (kind, notification_type, title, project, entity_type, entity_id, available) in enumerate(rows):
            if not available:
                skipped.append(kind)
                continue
            db.add(
                Notification(
                    id=uuid.uuid4(), user_id=user.id, type=notification_type, title=title,
                    body="Sample notification for the " + kind.replace("_", " ") + " target.",
                    project_id=project, entity_type=entity_type, entity_id=entity_id,
                    created_at=now - timedelta(minutes=index),
                )
            )
        db.commit()
        return skipped
    finally:
        db.close()
