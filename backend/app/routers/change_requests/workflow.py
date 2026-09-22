"""
Module: routers.change_requests.workflow

Submitting a change request for review, withdrawing it, and a project
manager approving or rejecting it. Approval applies the proposed change to
the target requirement (or creates a new one, or adds/removes an action or
link) through the same versioning mechanism used for direct scoping-stage
edits, so both paths share one audit trail.

Split out of the former flat `routers/change_requests.py` as a pure
code-organization refactor — see `routers/change_requests/__init__.py`'s
module docstring for the package layout. Imports `_to_out`/`_latest_version`
from `core.py`, the only other bucket that needs them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_request_channel
from app.metrics import (
    change_requests_approved_total,
    change_requests_rejected_total,
    change_requests_submitted_total,
)
from app.models.action_type import ActionTypeDefinition
from app.models.change_request import ChangeRequest, ChangeRequestVersion
from app.models.enums import ArtefactType, ChangeRequestKind, ChangeRequestStatus, ProjectRole, RequirementLevel, RequirementStatus
from app.models.file import FileAsset, RequirementFile
from app.models.notification import NotificationType
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.models.requirement_action import RequirementAction
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.routers.change_requests.core import _latest_version, _to_out
from app.schemas.change_request import ChangeRequestDecision, ChangeRequestOut
from app.services import notifications, pubsub
from app.services.actions import generate_unique_code as generate_action_unique_code
from app.services.audit import log_event
from app.services.rbac import (
    get_effective_project_roles,
    get_project_member_user_ids,
    get_project_users_by_role,
    require_ai_approvals_enabled,
    require_project_view,
)
from app.services.relationships import create_link as create_artefact_link
from app.services.relationships import get_link_between as get_artefact_link_between
from app.services.requirements import apply_new_version, create_requirement, get_current_version

router = APIRouter(tags=["change-requests-workflow"])


def _display_title(db: Session, cr: ChangeRequest, version: ChangeRequestVersion) -> str:
    """Human-readable label for a change request, used in notification
    titles. `proposed_name` alone is only ever set for NEW_REQUIREMENT, or
    for MODIFY_REQUIREMENT when `"name"` is itself one of `changed_fields`
    — every other case needs a fallback, rather than a notification title
    silently rendering "None" (a pre-existing gap for a MODIFY_REQUIREMENT
    CR that doesn't rename anything, found while adding ADD_ACTION — item
    514's own new kind never sets `proposed_name` at all, so it would hit
    this on every single notification without a fallback)."""
    if version.proposed_name:
        return version.proposed_name
    if cr.kind == ChangeRequestKind.ADD_ACTION:
        return version.proposed_action_title or "add an action"
    if cr.requirement_id is not None:
        requirement = db.get(Requirement, cr.requirement_id)
        if requirement is not None:
            return get_current_version(db, requirement.id).name
    return "change request"


@router.post("/{cr_id}/submit", response_model=ChangeRequestOut)
def submit_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Submits a draft change request for review."""
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    if cr.creator_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the creator may submit this change request.")
    if cr.status != ChangeRequestStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only draft change requests can be submitted.")
    cr.status = ChangeRequestStatus.SUBMITTED
    cr.submitted_at = datetime.now(UTC)
    log_event(db, entity_type="change_request", entity_id=cr.id, action="submitted",
              actor_id=current_user.id, project_id=project_id)
    change_requests_submitted_total.inc()

    version = _latest_version(db, cr)
    display_title = _display_title(db, cr, version)
    for user_id in get_project_users_by_role(db, project_id, ProjectRole.PROJECT_MANAGER):
        user = db.get(User, user_id)
        if user is not None:
            notifications.notify(
                db, user, notification_type=NotificationType.CHANGE_REQUEST_SUBMITTED,
                title=f"Change request submitted: {display_title}",
                project_id=project_id, entity_type="change_request", entity_id=str(cr.id),
                actor_id=current_user.id,
            )
    for user_id in get_project_users_by_role(db, project_id, ProjectRole.STAKEHOLDER):
        user = db.get(User, user_id)
        if user is not None:
            notifications.notify(
                db, user, notification_type=NotificationType.STAKEHOLDER_INPUT_REQUESTED,
                title=f"Your input is requested: {display_title}",
                project_id=project_id, entity_type="change_request", entity_id=str(cr.id),
                actor_id=current_user.id,
            )

    db.commit()
    db.refresh(cr)
    pubsub.notify(project_id, {"type": "change_request", "action": "submitted", "id": str(cr.id)})
    return _to_out(db, cr, _latest_version(db, cr), current_user.id)


@router.post("/{cr_id}/withdraw", response_model=ChangeRequestOut)
def withdraw_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    if cr.creator_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the creator may withdraw this change request.")
    if cr.status in (ChangeRequestStatus.APPROVED, ChangeRequestStatus.REJECTED):
        raise HTTPException(status.HTTP_409_CONFLICT, "This change request has already been decided.")
    cr.status = ChangeRequestStatus.WITHDRAWN
    log_event(db, entity_type="change_request", entity_id=cr.id, action="withdrawn",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(cr)
    return _to_out(db, cr, _latest_version(db, cr), current_user.id)


@router.post("/{cr_id}/decide", response_model=ChangeRequestOut)
def decide_change_request(
    project_id: UUID, cr_id: UUID, payload: ChangeRequestDecision,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Approves or rejects a submitted change request (C-U-03: project manager only).

    Approval applies the proposed change immediately: for a modification, a
    new requirement version is created via the change-request path; for a
    new requirement, the requirement is created directly in approved state.

    When reached through the MCP server (`channel == "mcp"`), additionally
    requires this project and its organisation to both have explicitly
    enabled AI approval — see `requirements.approve_requirement`'s
    docstring and docs/decisions.md's "AI approval via MCP" entry. A plain
    UI/API call is unaffected by that flag either way.
    """
    if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can decide change requests.")
    if channel == "mcp":
        require_ai_approvals_enabled(db, db.get(Project, project_id))

    # Row-locked (not a plain db.get): two concurrent /decide calls on the
    # same CR (e.g. one approve, one reject) would otherwise both read
    # status == SUBMITTED before either commits, both pass the status
    # check, and both apply their side effects — whichever commits last
    # silently overwrites the other's decision, leaving cr.status
    # mismatched with whatever side effects actually landed (e.g. a
    # requirement gets modified/created by the "approve" transaction while
    # the CR itself ends up recorded as REJECTED). The lock serializes the
    # two calls so the second one's status check runs against the first
    # one's already-committed result.
    cr = db.scalar(select(ChangeRequest).where(ChangeRequest.id == cr_id).with_for_update())
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    if cr.status not in (ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only submitted change requests can be decided.")

    version = _latest_version(db, cr)
    cr.decided_at = datetime.now(UTC)
    cr.decided_by = current_user.id
    cr.decision_note = payload.note

    if payload.approve:
        cr.status = ChangeRequestStatus.APPROVED
        if cr.kind == ChangeRequestKind.MODIFY_REQUIREMENT:
            requirement = db.get(Requirement, cr.requirement_id)
            current_version = get_current_version(db, requirement.id)
            # Only fields actually listed in changed_fields are applied —
            # everything else is left completely untouched (apply_new_version's
            # own "None/not-explicitly-set carries the current value forward"
            # convention), not silently re-written with a stale or default
            # proposed value. See ChangeRequestVersion.changed_fields's
            # docstring and docs/decisions.md's "Change request field-level
            # tracking" entry for why this replaced the previous
            # unconditional-apply-every-field behaviour.
            changed = set(version.changed_fields)
            apply_new_version(
                db, requirement, current_version, current_user,
                name=version.proposed_name if "name" in changed else None,
                reasoning=version.proposed_reasoning if "reasoning" in changed else None,
                clarification=version.proposed_clarification if "clarification" in changed else None,
                description=version.proposed_description if "description" in changed else None,
                # Was unconditionally `RequirementStatus.APPROVED` (2026-08
                # UX audit roadmap, found alongside "No requirement approval
                # action") — silently reverted an already-completed
                # requirement's *lifecycle status* as a side effect of any
                # modify-CR approval. `create_change_request`'s own guard
                # (above) only allows a MODIFY_REQUIREMENT change request
                # against an already-locked (`APPROVED`) requirement, so the
                # current status is always `APPROVED` by the time it's
                # decided — `None` carries it forward unchanged
                # (`apply_new_version`'s own convention) instead of forcing
                # it back down. Since C-G-11's completion overlay
                # (`Requirement.is_completed`) is a separate field from
                # `status` entirely, this line was never responsible for
                # preserving/clearing it either way — see `clear_completion`
                # below for the explicit, opt-in way an approver can clear
                # it as a deliberate part of this same decision.
                status_value=None,
                target_stage_id=version.proposed_target_stage_id, target_stage_explicitly_set="target_stage_id" in changed,
                level=version.proposed_level if "level" in changed else None,
                change_note=f"Applied via approved change request: {version.reason}",
                change_request_id=cr.id,
                custom_fields=version.custom_fields if "custom_fields" in changed else None,
                review_date=version.proposed_review_date, review_date_explicitly_set="review_date" in changed,
                review_lead_days=version.proposed_review_lead_days, review_lead_days_explicitly_set="review_lead_days" in changed,
                reviewer_id=version.proposed_reviewer_id, reviewer_id_explicitly_set="reviewer_id" in changed,
            )
            if "attachments" in changed and version.proposed_attachment_file_ids:
                project = db.get(Project, project_id)
                for raw_file_id in version.proposed_attachment_file_ids:
                    file_id = UUID(raw_file_id) if isinstance(raw_file_id, str) else raw_file_id
                    asset = db.get(FileAsset, file_id)
                    # Re-checked here, not just trusted from creation time
                    # (the same file could theoretically have been deleted
                    # or changed ownership between CR creation and approval)
                    # — same "never trust a stale reference" posture as
                    # report image resolution.
                    if asset is None or asset.organization_id != project.organization_id or not asset.is_org_resource:
                        continue
                    existing = db.scalar(
                        select(RequirementFile).where(
                            RequirementFile.requirement_id == requirement.id, RequirementFile.file_id == file_id
                        )
                    )
                    if existing is None:
                        db.add(RequirementFile(
                            requirement_id=requirement.id, file_id=file_id, linked_by=cr.creator_id,
                            created_at=datetime.now(UTC),
                        ))
                        log_event(
                            db, entity_type="requirement", entity_id=requirement.id, action="file_linked",
                            actor_id=current_user.id, project_id=project_id,
                            detail={"file_id": str(file_id), "via": "change_request", "change_request_id": str(cr.id)},
                        )
            # C-G-11: an explicit, opt-in approver choice, applied as a
            # separate step from the version-apply above (which never
            # touches `is_completed` either way — see the `status_value`
            # comment). A no-op, not an error, unless every precondition
            # holds — `clear_completion=True` on a requirement that isn't
            # currently completed (or wasn't otherwise applicable) simply
            # does nothing extra, matching this field's own docstring.
            # Logged as a distinct audit event from `approved` below, so
            # it's traceable that the approver made this call deliberately
            # rather than it being a side effect of approving the CR.
            if payload.clear_completion and requirement.is_completed:
                requirement.is_completed = False
                requirement.completed_at = None
                requirement.completed_by = None
                log_event(
                    db, entity_type="requirement", entity_id=requirement.id, action="completion_cleared_via_change_request",
                    actor_id=current_user.id, project_id=project_id,
                    detail={"change_request_id": str(cr.id)},
                )
        elif cr.kind == ChangeRequestKind.ADD_ACTION:
            # Item 514 — mirrors the "attachments" re-check just above:
            # the referenced action/action-type could have changed or been
            # archived between submission and approval, so both are
            # re-validated here rather than trusted from creation time.
            # `linked_by`/`creator_id` attribute to `cr.creator_id` (the
            # original submitter), matching `RequirementFile.linked_by`'s
            # own convention just above rather than `apply_new_version`'s —
            # an added action is closer in kind to a proposed attachment
            # (a new artifact the submitter is contributing) than to a
            # requirement version (whose authorship follows the approving
            # PM, since approval is what actually changes the requirement's
            # own content).
            requirement = db.get(Requirement, cr.requirement_id)
            project = db.get(Project, project_id)
            if version.proposed_action_link_id is not None:
                action = db.get(RequirementAction, version.proposed_action_link_id)
                if action is not None and action.project_id == project_id:
                    existing = get_artefact_link_between(
                        db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action.id,
                        target_type=ArtefactType.REQUIREMENT, target_id=requirement.id,
                    )
                    if existing is None:
                        create_artefact_link(
                            db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action.id,
                            target_type=ArtefactType.REQUIREMENT, target_id=requirement.id,
                            link_type_id=None, created_by=cr.creator_id,
                        )
                        log_event(
                            db, entity_type="requirement_action_link", entity_id=action.id, action="linked",
                            actor_id=current_user.id, project_id=project_id,
                            detail={
                                "requirement_id": str(requirement.id), "action_id": str(action.id),
                                "via": "change_request", "change_request_id": str(cr.id),
                            },
                        )
            else:
                action_type = db.get(ActionTypeDefinition, version.proposed_action_type_id)
                if action_type is not None and action_type.project_id == project_id:
                    action = RequirementAction(
                        project_id=project_id, unique_code=generate_action_unique_code(project),
                        action_type_id=version.proposed_action_type_id,
                        title=version.proposed_action_title, description=version.proposed_action_description or "",
                        assignee_id=version.proposed_action_assignee_id, due_date=version.proposed_action_due_date,
                        creator_id=cr.creator_id,
                    )
                    db.add(action)
                    db.flush()
                    create_artefact_link(
                        db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action.id,
                        target_type=ArtefactType.REQUIREMENT, target_id=requirement.id,
                        link_type_id=None, created_by=cr.creator_id,
                    )
                    log_event(
                        db, entity_type="requirement_action", entity_id=action.id, action="created",
                        actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
                        detail={
                            "unique_code": action.unique_code, "title": action.title,
                            "linked_requirement_id": str(requirement.id),
                            "via": "change_request", "change_request_id": str(cr.id),
                        },
                    )
        elif cr.kind == ChangeRequestKind.REMOVE_ACTION:
            # Platform review 2026-09, Phase 8 — mirrors ADD_ACTION's own
            # re-check above: the link could have already been removed
            # directly (before this requirement was re-locked, say) between
            # submission and approval, so re-verify rather than assume.
            requirement = db.get(Requirement, cr.requirement_id)
            existing = get_artefact_link_between(
                db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=version.proposed_action_link_id,
                target_type=ArtefactType.REQUIREMENT, target_id=requirement.id,
            )
            if existing is not None:
                log_event(
                    db, entity_type="requirement_action_link", entity_id=existing.source_id, action="unlinked",
                    actor_id=current_user.id, project_id=project_id,
                    detail={
                        "requirement_id": str(requirement.id), "action_id": str(existing.source_id),
                        "via": "change_request", "change_request_id": str(cr.id),
                    },
                )
                db.delete(existing)
        elif cr.kind == ChangeRequestKind.ADD_LINK:
            # Platform review 2026-09, Phase 8 — same re-check posture as
            # ADD_ACTION/attachments above.
            requirement = db.get(Requirement, cr.requirement_id)
            target = db.get(Requirement, version.proposed_link_target_requirement_id)
            link_type = db.get(RequirementLinkTypeDefinition, version.proposed_link_type_id)
            if target is not None and target.project_id == project_id and link_type is not None:
                existing = get_artefact_link_between(
                    db, source_type=ArtefactType.REQUIREMENT, source_id=requirement.id,
                    target_type=ArtefactType.REQUIREMENT, target_id=target.id,
                    link_type_id=link_type.id,
                )
                if existing is None:
                    link = create_artefact_link(
                        db, source_type=ArtefactType.REQUIREMENT, source_id=requirement.id,
                        target_type=ArtefactType.REQUIREMENT, target_id=target.id,
                        link_type_id=link_type.id, created_by=cr.creator_id,
                    )
                    log_event(
                        db, entity_type="requirement_link", entity_id=link.id, action="created",
                        actor_id=current_user.id, project_id=project_id,
                        detail={
                            "source_requirement_id": str(requirement.id), "target_requirement_id": str(target.id),
                            "link_type_id": str(link_type.id),
                            "via": "change_request", "change_request_id": str(cr.id),
                        },
                    )
        elif cr.kind == ChangeRequestKind.REMOVE_LINK:
            # Platform review 2026-09, Phase 8 — same re-check posture as
            # ADD_LINK above: the link may already have been removed via
            # some other path between submission and approval.
            link = db.get(ArtefactLink, version.proposed_link_id)
            if link is not None:
                log_event(
                    db, entity_type="requirement_link", entity_id=link.id, action="deleted",
                    actor_id=current_user.id, project_id=project_id,
                    detail={
                        "source_requirement_id": str(link.source_id),
                        "target_requirement_id": str(link.target_id),
                        "via": "change_request", "change_request_id": str(cr.id),
                    },
                )
                db.delete(link)
        else:
            project = db.get(Project, project_id)
            component = db.get(ProjectComponent, version.proposed_component_id)
            category = db.get(ProjectCategory, version.proposed_category_id)
            if component is None or category is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Change request is missing component/category.")
            target_stage_id = version.proposed_target_stage_id
            if target_stage_id is None:
                # Not left unset: default to the project's own earliest
                # stage, same as a direct create
                # (routers/requirements.py::create_requirement_endpoint).
                default_stage = db.scalar(
                    select(ProjectStage).where(ProjectStage.project_id == project_id).order_by(ProjectStage.sort_order.asc())
                )
                if default_stage is None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project has no stages; cannot assign a target.")
                target_stage_id = default_stage.id
            count = len(db.scalars(select(Requirement.id).where(Requirement.project_id == project_id)).all())
            requirement = create_requirement(
                db, project, component, category, current_user,
                name=version.proposed_name, reasoning=version.proposed_reasoning or "",
                clarification=version.proposed_clarification or "", description=version.proposed_description or "",
                owner_id=None, keywords=[], sort_order=count,
                target_stage_id=target_stage_id, level=version.proposed_level or RequirementLevel.REQUIREMENT,
                custom_fields=version.custom_fields,
                review_date=version.proposed_review_date, review_lead_days=version.proposed_review_lead_days,
                reviewer_id=version.proposed_reviewer_id,
            )
            db.flush()
            current_version = get_current_version(db, requirement.id)
            apply_new_version(
                db, requirement, current_version, current_user, status_value=RequirementStatus.APPROVED,
                change_note=f"Created via approved change request: {version.reason}", change_request_id=cr.id,
            )
            cr.requirement_id = requirement.id
        change_requests_approved_total.inc()
    else:
        cr.status = ChangeRequestStatus.REJECTED
        change_requests_rejected_total.inc()

    log_event(
        db, entity_type="change_request", entity_id=cr.id,
        action="approved" if payload.approve else "rejected",
        actor_id=current_user.id, project_id=project_id,
        detail={"note": payload.note, "via": "mcp"} if channel == "mcp" else {"note": payload.note},
    )

    display_title = _display_title(db, cr, version)
    creator = db.get(User, cr.creator_id)
    if creator is not None:
        notifications.notify(
            db, creator,
            notification_type=NotificationType.CHANGE_REQUEST_APPROVED if payload.approve else NotificationType.CHANGE_REQUEST_REJECTED,
            title=f"Your change request was {'approved' if payload.approve else 'rejected'}: {display_title}",
            body=payload.note, project_id=project_id, entity_type="change_request", entity_id=str(cr.id),
            actor_id=current_user.id,
        )
    if payload.approve:
        project_name = db.get(Project, project_id).name
        for user_id in get_project_member_user_ids(db, project_id):
            user = db.get(User, user_id)
            if user is not None:
                notifications.notify(
                    db, user, notification_type=NotificationType.REQUIREMENTS_UPDATED,
                    title=f"{project_name}: requirements updated via change request",
                    body=display_title, project_id=project_id,
                    entity_type="change_request", entity_id=str(cr.id),
                    actor_id=current_user.id,
                )

    db.commit()
    db.refresh(cr)
    pubsub.notify(project_id, {"type": "change_request", "action": cr.status.value, "id": str(cr.id)})
    return _to_out(db, cr, version, current_user.id)
