"""
Module: modules.compliance.scheduler

The Compliance Module's Phase 10 date-driven notification sweeps (docs/
compliance-module-plan.md Phase 10; docs/Compliance_Module_Requirements.md
§18, §28) — registered with the core scheduler generically via
`app.modules.registry.ModuleScheduledJob` (`module.py`'s `MODULE_DEFINITION.
scheduled_jobs`), the same way `services/scheduler.py`'s own two core jobs
are, but without that core file importing anything from this module
directly. Mirrors `app.services.reviews.send_due_review_reminders`'s own
shape exactly: a plain `(db: Session) -> None` function, no session opened
inside it, one `db.commit()` at the end.

Four sweeps, one per §28 bullet-group this phase covers:
- `send_evidence_expiry_notifications`: evidence approaching/past expiry
  (§14, §18's "Evidence approaching expiry"/"Evidence expiring").
- `send_review_due_notifications`: scheduled compliance reviews becoming
  due/overdue (§17, §18).
- `send_required_action_due_notifications`: required actions approaching/
  past their due date (§6, §18).
- `send_target_date_notifications`: a project's own compliance target date
  approaching/exceeded (§7, §18).

Every sweep is idempotent per notification: each owning row carries a pair
of `*_reminder_sent_at`/`*_notified_at` timestamp columns (see each column's
own docstring in `models.py`) that this file stamps the first time each of
the two notifications for that row's *current* due/expiry value has been
sent, so re-running the sweep (or running it more than once a day) never
sends a duplicate — the same convention `RequirementVersion.review_
reminder_sent_at` already established for the analogous core sweep.

Recipient resolution goes through `service.py::get_effective_compliance_
officers`/`get_effective_compliance_managers` — see those functions' own
docstrings for why this is deliberately not an authorization check.

External dependencies: `app.services.notifications` (existing notification
delivery, reused rather than reimplemented — §18's own explicit "should not
create a separate notification framework"), `app.modules.compliance.models`/
`.service`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import NotificationType
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.enums import ComplianceReviewStatus
from app.modules.compliance.models import (
    ComplianceEvidence,
    ComplianceRequiredActionAssessment,
    ComplianceReview,
    ComplianceStandard,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.compliance.service import (
    COMPLIANCE_REVIEW_DUE_WARNING_DAYS,
    EVIDENCE_EXPIRY_WARNING_DAYS,
    get_effective_compliance_managers,
    get_effective_compliance_officers,
)
from app.services import notifications

#: Days before a required action's `due_date` that it is notified as
#: approaching (§18's "Required Action approaching its due date") — a
#: shorter window than evidence's 30 days, matching a required action's own
#: typically shorter turnaround (a task someone must still go and do,
#: rather than a certificate whose renewal is usually planned well ahead).
REQUIRED_ACTION_DUE_WARNING_DAYS = 7

#: Days before `ProjectCompliance.target_compliance_date` that it is
#: notified as approaching (§18's "Project compliance target date
#: approaching") — mirrors `EVIDENCE_EXPIRY_WARNING_DAYS`'s own 30-day
#: window, a comparable "plan-ahead" milestone.
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
        if db.get(Project, evidence.project_id) is None:
            continue
        recipients = get_effective_compliance_officers(db, evidence.project_id)

        if evidence.expiry_date < today:
            if evidence.expiry_notified_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_EVIDENCE_EXPIRED,
                title=f"Evidence expired: {evidence.title}",
                body=f'"{evidence.title}" expired on {evidence.expiry_date.isoformat()}.',
                project_id=evidence.project_id, entity_type="compliance_evidence", entity_id=str(evidence.id),
            )
            evidence.expiry_notified_at = datetime.now(UTC)
        elif evidence.expiry_date <= today + timedelta(days=EVIDENCE_EXPIRY_WARNING_DAYS):
            if evidence.expiry_reminder_sent_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_EVIDENCE_EXPIRING_SOON,
                title=f"Evidence expiring soon: {evidence.title}",
                body=f'"{evidence.title}" expires on {evidence.expiry_date.isoformat()}.',
                project_id=evidence.project_id, entity_type="compliance_evidence", entity_id=str(evidence.id),
            )
            evidence.expiry_reminder_sent_at = datetime.now(UTC)

    db.commit()


def send_review_due_notifications(db: Session) -> None:
    """Daily sweep (§17, §18, §28): notifies the relevant compliance
    officers/managers (plus the review's own `owner_id`, if set) when a
    `SCHEDULED` `ComplianceReview` becomes due or overdue, at most once per
    notification per current `next_due_date` (`ComplianceReview.due_
    reminder_sent_at`/`overdue_notified_at`). Covers both standard-level
    and project-level reviews — see `models.py`'s own docstring for why a
    review has exactly one of the two owners."""
    today = date.today()
    reviews = db.scalars(select(ComplianceReview).where(ComplianceReview.status == ComplianceReviewStatus.SCHEDULED)).all()

    for review in reviews:
        recipients: set[UUID] = set()
        project_id: UUID | None = None
        organization_id: UUID | None = None

        if review.project_compliance_id is not None:
            project_compliance = db.get(ProjectCompliance, review.project_compliance_id)
            if project_compliance is None:
                continue
            project_id = project_compliance.project_id
            recipients = get_effective_compliance_officers(db, project_id)
        else:
            standard = db.get(ComplianceStandard, review.standard_id)
            if standard is None:
                continue
            organization_id = standard.organization_id
            recipients = get_effective_compliance_managers(db, organization_id)
        if review.owner_id is not None:
            recipients.add(review.owner_id)

        if review.next_due_date < today:
            if review.overdue_notified_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_REVIEW_OVERDUE,
                title=f"Compliance review overdue: {review.frequency_label}",
                body=f"A scheduled compliance review was due on {review.next_due_date.isoformat()}.",
                project_id=project_id, entity_type="compliance_review", entity_id=str(review.id),
            )
            review.overdue_notified_at = datetime.now(UTC)
        elif review.next_due_date <= today + timedelta(days=COMPLIANCE_REVIEW_DUE_WARNING_DAYS):
            if review.due_reminder_sent_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_REVIEW_DUE,
                title=f"Compliance review due soon: {review.frequency_label}",
                body=f"A scheduled compliance review is due on {review.next_due_date.isoformat()}.",
                project_id=project_id, entity_type="compliance_review", entity_id=str(review.id),
            )
            review.due_reminder_sent_at = datetime.now(UTC)

    db.commit()


def send_required_action_due_notifications(db: Session) -> None:
    """Daily sweep (§6, §18, §28): notifies a required action's own
    assignee (or, if unassigned, the owning project's compliance officers)
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
        recipients = {assessment.assignee_id} if assessment.assignee_id else get_effective_compliance_officers(db, project_id)

        if assessment.due_date < today:
            if assessment.overdue_notified_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_REQUIRED_ACTION_OVERDUE,
                title="Required action overdue",
                body=f"A required action was due on {assessment.due_date.isoformat()}.",
                project_id=project_id, entity_type="compliance_required_action_assessment",
                entity_id=str(assessment.id),
            )
            assessment.overdue_notified_at = datetime.now(UTC)
        elif assessment.due_date <= today + timedelta(days=REQUIRED_ACTION_DUE_WARNING_DAYS):
            if assessment.due_reminder_sent_at is not None:
                continue
            _notify_many(
                db, recipients, notification_type=NotificationType.COMPLIANCE_REQUIRED_ACTION_DUE_SOON,
                title="Required action due soon",
                body=f"A required action is due on {assessment.due_date.isoformat()}.",
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
