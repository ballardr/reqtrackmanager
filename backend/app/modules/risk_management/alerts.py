"""
Module: modules.risk_management.alerts

Notifications for Risk Management (overview §11.6): a review coming due or overdue, and a treatment whose
verdict may no longer hold because the artefact behind it changed.

Responsibilities:
- Declare the module's notification types (`NOTIFICATION_TYPES`), registered on
  `ModuleDefinition.notification_types` so core's closed enum is untouched.
- `send_review_notifications`: the daily sweep for reviews due soon or overdue.
- `on_artefact_changed`: the module's `ModuleDefinition.on_artefact_changed`
  hook; moves effective treatment verdicts that rest on a changed artefact to
  `NEEDS_REASSESSMENT` and tells the risk's owner.

Design decisions:
- Detection and notification only. A change never rewrites a risk: the verdict
  moves to `NEEDS_REASSESSMENT` (which already fails the `Mitigated` guard) and a
  human decides, using the lifecycle the risk already has. This is the platform
  "invalidation" convention for a mutable-status artefact. Decided by: Agent.
- Only `EFFECTIVE` verdicts are moved. A `proposed` link makes no claim to
  invalidate; an `INEFFECTIVE` one is not made wrong by a change. Because a
  second edit finds the verdict already moved, a burst of edits notifies once.
- The review sweep notifies once per `review_date` (the date is stored on the
  risk as `review_*_notified_for`), so re-running it is harmless and a
  rescheduled review re-arms itself with no reset step.
- Recipients: the risk's owner (every active member of an owner group, via
  `services.principals.principal_recipients`); with no owner, or a group with no
  one to notify, the project's Risk Managers and project managers, so an
  unowned risk still reaches someone accountable. This
  is addressing, not authorisation. The actor is never notified of their own
  edit (`notify`'s `actor_id`). A notification about a change in *another*
  project does not name the changed artefact, because the recipient may not be
  allowed to see it.

Dependencies: `services.notifications`, `services.artefact_changes`' payload
(`registry.ArtefactChange`), this module's models.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.module_role import UserModuleRole
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.user import User
from app.modules.registry import (
    ArtefactChange,
    NotificationTypeDefinition,
    is_module_subcomponent_enabled,
)
from app.modules.risk_management.enums import RiskStatus, TreatmentAssessmentStatus
from app.modules.risk_management.models import Risk, RiskTreatmentAssessment, RiskVersion
from app.modules.risk_management.service import (
    RISK_ARTEFACT_TYPE,
    RISK_MODULE_KEY,
    RISK_SUBCOMPONENT_KEY,
    get_current_risk_version,
)
from app.services import notifications
from app.services.audit import log_event
from app.services.principals import principal_recipients, principal_ref
from app.services.rbac import get_effective_project_managers

logger = logging.getLogger(__name__)

REVIEW_DUE_TYPE = "risk_review_due"
REVIEW_OVERDUE_TYPE = "risk_review_overdue"
TREATMENT_REASSESSMENT_TYPE = "risk_treatment_needs_reassessment"

NOTIFICATION_TYPES: tuple[NotificationTypeDefinition, ...] = (
    NotificationTypeDefinition(REVIEW_DUE_TYPE, "Risk review due soon"),
    NotificationTypeDefinition(REVIEW_OVERDUE_TYPE, "Risk review overdue"),
    NotificationTypeDefinition(TREATMENT_REASSESSMENT_TYPE, "Risk treatment needs reassessment"),
)

#: Days before `review_date` that the "due soon" notification is sent.
REVIEW_DUE_WARNING_DAYS = 7


def risk_recipients(db: Session, risk: Risk, version: RiskVersion) -> set[uuid.UUID]:
    """Who should hear about a risk: its owner (every member of an owner group), else the
    project's Risk Managers and project managers, which also covers an owner group with no
    one left to notify. Addressing only, not an authorisation check."""
    owners = principal_recipients(db, [principal_ref(version.owner_type, version.owner_id)])
    if owners:
        return owners
    managers = set(db.scalars(
        select(UserModuleRole.user_id).where(
            UserModuleRole.module_key == RISK_MODULE_KEY, UserModuleRole.role_key == "risk_manager",
            UserModuleRole.project_id == risk.project_id,
        )
    ).all())
    return managers | get_effective_project_managers(db, risk.project_id)


def _notify(
    db: Session, user_ids: set[uuid.UUID], risk: Risk, version: RiskVersion, *, kind: str, title: str, body: str,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Sends one notification about `risk` to each existing user in `user_ids`."""
    for user_id in user_ids:
        user = db.get(User, user_id)
        if user is None:
            continue
        notifications.notify(
            db, user, notification_type=kind, title=f"{risk.unique_code}: {title}", body=body.replace("{title}", version.title),
            project_id=risk.project_id, entity_type=RISK_ARTEFACT_TYPE, entity_id=str(risk.id), actor_id=actor_id,
        )


def send_review_notifications(db: Session) -> None:
    """Daily sweep: tells the risk's recipients when a scheduled review is due
    within `REVIEW_DUE_WARNING_DAYS` or overdue, once per `review_date`. Skips
    archived and closed risks and projects where Risk Management is switched
    off. Commits once at the end."""
    today = date.today()
    horizon = today + timedelta(days=REVIEW_DUE_WARNING_DAYS)
    rows = db.execute(
        select(Risk, RiskVersion).join(RiskVersion, RiskVersion.risk_id == Risk.id).where(
            RiskVersion.valid_to.is_(None), RiskVersion.review_date.is_not(None), RiskVersion.review_date <= horizon,
            Risk.is_archived.is_(False), RiskVersion.status != RiskStatus.CLOSED,
        )
    ).all()
    enabled: dict[uuid.UUID, bool] = {}
    for risk, version in rows:
        if risk.project_id not in enabled:
            enabled[risk.project_id] = (
                db.get(Project, risk.project_id) is not None
                and is_module_subcomponent_enabled(db, risk.project_id, RISK_MODULE_KEY, RISK_SUBCOMPONENT_KEY)
            )
        if not enabled[risk.project_id]:
            continue
        due = version.review_date
        recipients = risk_recipients(db, risk, version)
        if due < today:
            if risk.review_overdue_notified_for == due:
                continue
            _notify(db, recipients, risk, version, kind=REVIEW_OVERDUE_TYPE, title="review overdue",
                    body=f'The review of "{{title}}" was due on {due.isoformat()}.')
            risk.review_overdue_notified_for = due
        else:
            if risk.review_due_notified_for == due:
                continue
            _notify(db, recipients, risk, version, kind=REVIEW_DUE_TYPE, title="review due soon",
                    body=f'The review of "{{title}}" is due on {due.isoformat()}.')
            risk.review_due_notified_for = due
    db.commit()


def on_artefact_changed(db: Session, change: ArtefactChange) -> None:
    """`ModuleDefinition.on_artefact_changed`: flags every effective treatment
    verdict resting on the changed artefact for reassessment and notifies each
    affected risk's recipients once. Does not commit.

    A closed or archived risk, or one in a project where the module is off, is
    left alone. A risk is never treated as the dependency of its own treatment.
    """
    if change.artefact_type == RISK_ARTEFACT_TYPE:
        return
    here = and_(ArtefactLink.source_type == change.artefact_type, ArtefactLink.source_id == change.artefact_id)
    there = and_(ArtefactLink.target_type == change.artefact_type, ArtefactLink.target_id == change.artefact_id)
    verdicts = db.scalars(
        select(RiskTreatmentAssessment).join(ArtefactLink, ArtefactLink.id == RiskTreatmentAssessment.link_id).where(
            RiskTreatmentAssessment.status == TreatmentAssessmentStatus.EFFECTIVE, or_(here, there),
        )
    ).all()
    by_risk: dict[uuid.UUID, list[RiskTreatmentAssessment]] = {}
    for verdict in verdicts:
        by_risk.setdefault(verdict.risk_id, []).append(verdict)
    for risk_id, flagged in by_risk.items():
        risk = db.get(Risk, risk_id)
        if risk is None or risk.is_archived:
            continue
        version = get_current_risk_version(db, risk.id)
        if version.status == RiskStatus.CLOSED or not is_module_subcomponent_enabled(
            db, risk.project_id, RISK_MODULE_KEY, RISK_SUBCOMPONENT_KEY
        ):
            continue
        reason = f"{change.summary}." if change.summary else "A linked artefact changed."
        for verdict in flagged:
            verdict.status = TreatmentAssessmentStatus.NEEDS_REASSESSMENT
            verdict.reassessment_reason = reason
            log_event(
                db, entity_type=RISK_ARTEFACT_TYPE, entity_id=risk.id, action="treatment_needs_reassessment",
                actor_id=change.actor_id, project_id=risk.project_id,
                detail={"link_id": str(verdict.link_id), "other_type": change.artefact_type,
                        "other_id": str(change.artefact_id), "change": change.kind},
            )
        count = len(flagged)
        # The stored reason is only shown with a treatment the viewer can already see. A notification goes to the
        # owner whatever they may view, so a change in another project is described without naming it.
        said = reason if change.project_id == risk.project_id else "A linked artefact in another project changed."
        _notify(
            db, risk_recipients(db, risk, version), risk, version, kind=TREATMENT_REASSESSMENT_TYPE,
            title=f"{count} treatment{'s' if count != 1 else ''} need{'' if count != 1 else 's'} reassessment",
            body=f'{said} Check whether it still reduces "{{title}}".', actor_id=change.actor_id,
        )
