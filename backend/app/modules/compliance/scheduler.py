"""
Module: modules.compliance.scheduler

The Compliance Module's date-driven notification sweeps (§18, §28), registered with the core scheduler through
`app.modules.registry.ModuleScheduledJob` (`MODULE_DEFINITION.scheduled_jobs`) so no core file imports this module. Each
sweep is a plain `(db: Session) -> None` function with one `db.commit()` at the end, as
`app.services.reviews.send_due_review_reminders`.

Four sweeps:
- `send_evidence_expiry_notifications`: evidence approaching or past expiry (§14, §18).
- `send_review_due_notifications`: scheduled reviews becoming due or overdue (§17, §18).
- `send_required_action_due_notifications`: required actions approaching or past their due date (§6, §18).
- `send_target_date_notifications`: a project's compliance target date approaching or exceeded (§7, §18).

Each sweep is idempotent per notification: the owning row's `*_reminder_sent_at` / `*_notified_at` columns (see
`models.py`) are stamped the first time each notification for the row's current due or expiry value is sent, so
re-running never duplicates (as `RequirementVersion.review_reminder_sent_at` does for the core sweep).

Recipients come from `service.get_effective_compliance_officers` / `get_effective_compliance_managers`, which are not an
authorization check.

External dependencies: `app.services.notifications` (§18: no separate notification framework),
`app.modules.compliance.models` and `.service`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import NotificationType
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.models import (
    ComplianceEvidence,
    ComplianceRequiredActionAssessment,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.compliance.service import (
    EVIDENCE_EXPIRY_WARNING_DAYS,
    get_effective_compliance_officers,
)
from app.services import notifications
from app.services.codes import qualify
from app.services.principals import principal_recipients, principal_ref

#: Days before a required action's `due_date` that it is notified as approaching (§18); shorter than evidence's 30 days
#: because a required action is a task, not a renewal planned well ahead.
REQUIRED_ACTION_DUE_WARNING_DAYS = 7

#: Days before `ProjectCompliance.target_compliance_date` that it is notified as approaching (§18); the same plan-ahead
#: window as `EVIDENCE_EXPIRY_WARNING_DAYS`.
TARGET_DATE_WARNING_DAYS = 30


def _notify_many(db: Session, user_ids: set[UUID], **notify_kwargs) -> None:
    """Sends the same notification to every id in `user_ids`, skipping any
    that no longer resolve to a real `User` — the shared fan-out loop every
    sweep below uses, mirroring `services.reviews.send_due_review_
    reminders`'s own per-recipient loop shape."""
    for user_id in user_ids:
        user = db.get(User, user_id)
        if user is None:
            continue
        notifications.notify(db, user, **notify_kwargs)


def send_evidence_expiry_notifications(db: Session) -> None:
    """Daily sweep (§14, §18, §28): notifies a project's compliance
    officers when a non-archived piece of evidence is approaching or has
    passed its expiry date, at most once per notification per current
    `expiry_date` (`ComplianceEvidence.expiry_reminder_sent_at`/
    `expiry_notified_at`)."""
    today = date.today()
    candidates = db.scalars(
        select(ComplianceEvidence).where(
            ComplianceEvidence.expiry_date.is_not(None), ComplianceEvidence.is_archived.is_(False)
        )
    ).all()

    for evidence in candidates:
        project = db.get(Project, evidence.project_id)
        if project is None:
            continue
        recipients = get_effective_compliance_officers(db, evidence.project_id)
        # A notification is read out of context, so the record is named by its qualified code.
        named = f"{qualify(project.code, evidence.unique_code)} {evidence.title}"

        expiry_date = evidence.expiry_date
        if expiry_date is None:
            continue  # the query selects only dated evidence
        if expiry_date < today:
            if evidence.expiry_notified_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_EVIDENCE_EXPIRED,
                title=f"Evidence expired: {named}",
                body=f'"{evidence.title}" expired on {expiry_date.isoformat()}.',
                project_id=evidence.project_id, entity_type="compliance_evidence", entity_id=str(evidence.id),
            )
            evidence.expiry_notified_at = datetime.now(UTC)
        elif expiry_date <= today + timedelta(days=EVIDENCE_EXPIRY_WARNING_DAYS):
            if evidence.expiry_reminder_sent_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_EVIDENCE_EXPIRING_SOON,
                title=f"Evidence expiring soon: {named}",
                body=f'"{evidence.title}" expires on {expiry_date.isoformat()}.',
                project_id=evidence.project_id, entity_type="compliance_evidence", entity_id=str(evidence.id),
            )
            evidence.expiry_reminder_sent_at = datetime.now(UTC)

    db.commit()


def send_required_action_due_notifications(db: Session) -> None:
    """Daily sweep (§6, §18, §28): notifies a required action's own
    assignee (a user, or every member of an assigned group; or, if unassigned
    or the assignee has no one left to notify, the owning project's compliance officers)
    when it is approaching or has passed its due date, at most once per
    notification per current `due_date` (`ComplianceRequiredActionAssessment.
    due_reminder_sent_at`/`overdue_notified_at`). Excludes already-completed
    assessments — a completed action has nothing left to be overdue about."""
    today = date.today()
    candidates = db.scalars(
        select(ComplianceRequiredActionAssessment).where(
            ComplianceRequiredActionAssessment.due_date.is_not(None),
            ComplianceRequiredActionAssessment.is_completed.is_(False),
        )
    ).all()

    for assessment in candidates:
        pcr = db.get(ProjectComplianceRequirement, assessment.project_compliance_requirement_id)
        if pcr is None:
            continue
        project_compliance = db.get(ProjectCompliance, pcr.project_compliance_id)
        if project_compliance is None:
            continue
        project_id = project_compliance.project_id
        recipients = principal_recipients(db, [principal_ref(assessment.assignee_type, assessment.assignee_id)])
        if not recipients:
            recipients = get_effective_compliance_officers(db, project_id)

        due_date = assessment.due_date
        if due_date is None:
            continue  # the query selects only dated assessments
        if due_date < today:
            if assessment.overdue_notified_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_REQUIRED_ACTION_OVERDUE,
                title="Required action overdue",
                body=f"A required action was due on {due_date.isoformat()}.",
                project_id=project_id, entity_type="compliance_required_action_assessment",
                entity_id=str(assessment.id),
            )
            assessment.overdue_notified_at = datetime.now(UTC)
        elif due_date <= today + timedelta(days=REQUIRED_ACTION_DUE_WARNING_DAYS):
            if assessment.due_reminder_sent_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_REQUIRED_ACTION_DUE_SOON,
                title="Required action due soon",
                body=f"A required action is due on {due_date.isoformat()}.",
                project_id=project_id, entity_type="compliance_required_action_assessment",
                entity_id=str(assessment.id),
            )
            assessment.due_reminder_sent_at = datetime.now(UTC)

    db.commit()


def send_target_date_notifications(db: Session) -> None:
    """Daily sweep (§7, §18, §28): notifies a project's compliance officers
    when a non-archived `ProjectCompliance` assignment's own `target_
    compliance_date` is approaching or has passed, at most once per
    notification per current `target_compliance_date` (`ProjectCompliance.
    target_date_reminder_sent_at`/`target_date_overdue_notified_at`)."""
    today = date.today()
    candidates = db.scalars(
        select(ProjectCompliance).where(
            ProjectCompliance.target_compliance_date.is_not(None), ProjectCompliance.is_archived.is_(False)
        )
    ).all()

    for project_compliance in candidates:
        if db.get(Project, project_compliance.project_id) is None:
            continue
        recipients = get_effective_compliance_officers(db, project_compliance.project_id)
        target_date = project_compliance.target_compliance_date
        if target_date is None:
            continue  # the query selects only assignments with a target date

        if target_date < today:
            if project_compliance.target_date_overdue_notified_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_TARGET_DATE_EXCEEDED,
                title="Compliance target date exceeded",
                body=f"This project's compliance target date of {target_date.isoformat()} has passed.",
                project_id=project_compliance.project_id, entity_type="project_compliance",
                entity_id=str(project_compliance.id),
            )
            project_compliance.target_date_overdue_notified_at = datetime.now(UTC)
        elif target_date <= today + timedelta(days=TARGET_DATE_WARNING_DAYS):
            if project_compliance.target_date_reminder_sent_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_TARGET_DATE_APPROACHING,
                title="Compliance target date approaching",
                body=f"This project's compliance target date is {target_date.isoformat()}.",
                project_id=project_compliance.project_id, entity_type="project_compliance",
                entity_id=str(project_compliance.id),
            )
            project_compliance.target_date_reminder_sent_at = datetime.now(UTC)

    db.commit()
