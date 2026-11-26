"""
Module: modules.risk_management.alerts

Notifications for Risk Management: the notification types (a review due or overdue, which `reviews.RISK_REVIEW_ADAPTER`
hands to the core review engine, and a treatment verdict that may no longer hold because its artefact changed) and
`on_artefact_changed` (moves `EFFECTIVE` verdicts resting on a changed artefact to `NEEDS_REASSESSMENT`). Recipients: the
owner (group members included), else Risk Managers and project managers; never the actor.
"""

from __future__ import annotations

import logging
import uuid

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
from app.services.codes import qualify
from app.services.principals import principal_recipients, principal_ref
from app.services.rbac import get_effective_project_managers

logger = logging.getLogger(__name__)

REVIEW_DUE_TYPE = "risk_review_due"
REVIEW_OVERDUE_TYPE = "risk_review_overdue"
TREATMENT_REASSESSMENT_TYPE = "risk_treatment_needs_reassessment"

NOTIFICATION_TYPES: tuple[NotificationTypeDefinition, ...] = (
    NotificationTypeDefinition(REVIEW_DUE_TYPE, "Risk review due soon", target_kinds=("record",)),
    NotificationTypeDefinition(REVIEW_OVERDUE_TYPE, "Risk review overdue", target_kinds=("record",)),
    NotificationTypeDefinition(TREATMENT_REASSESSMENT_TYPE, "Risk treatment needs reassessment", target_kinds=("record",)),
)


def risk_recipients(db: Session, risk: Risk, version: RiskVersion) -> set[uuid.UUID]:
    """Who should hear about a risk: its owner (every member of an owner group), else the
    project's Risk Managers and project managers, which also covers an owner group with no
    one left to notify. Addressing only, not an authorisation check."""
    owners = principal_recipients(db, [principal_ref(version.owner_type, version.owner_id)])
    return owners or manager_recipients(db, risk.project_id)


def manager_recipients(db: Session, project_id: uuid.UUID) -> set[uuid.UUID]:
    """The project's Risk Managers and project managers: who hears about a risk nobody owns."""
    managers = set(db.scalars(
        select(UserModuleRole.user_id).where(
            UserModuleRole.module_key == RISK_MODULE_KEY, UserModuleRole.role_key == "risk_manager",
            UserModuleRole.project_id == project_id,
        )
    ).all())
    return managers | get_effective_project_managers(db, project_id)


def _notify(
    db: Session, user_ids: set[uuid.UUID], risk: Risk, version: RiskVersion, *, kind: str, title: str, body: str,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Sends one notification about `risk` to each existing user in `user_ids`."""
    project = db.get(Project, risk.project_id)
    code = qualify(project.code, risk.unique_code) if project is not None else risk.unique_code  # read out of context
    for user_id in user_ids:
        user = db.get(User, user_id)
        if user is None:
            continue
        notifications.notify(
            db, user, notification_type=kind, title=f"{code}: {title}", body=body.replace("{title}", version.title),
            project_id=risk.project_id, entity_type=RISK_ARTEFACT_TYPE, entity_id=str(risk.id), actor_id=actor_id,
        )


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
