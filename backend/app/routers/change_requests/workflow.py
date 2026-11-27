"""
Module: routers.change_requests.workflow

Submitting a change request for review, withdrawing it, and a project manager approving or rejecting it.
Approval applies the proposed change to the target requirement (or creates a new one, or adds/removes an
action or link) through the versioning mechanism used for direct scoping-stage edits, so both paths share
one audit trail. Imports `_to_out`/`_latest_version` from `core.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
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
from app.models.user import User
from app.routers.change_requests.core import _latest_version, _to_out
from app.schemas.change_request import ChangeRequestDecision, ChangeRequestOut, ProposedLinkPreviewOut
from app.services import approval_policy, approval_separation, notifications, pubsub
from app.services.actions import generate_unique_code as generate_action_unique_code
from app.services.audit import log_event
from app.services.baseline import check_record_approval
from app.services.change_request_links import build_preview, decline_all, resolve_links
from app.services.codes import qualify
from app.services.lifecycles import check_move
from app.services.lookups import get_or_404, project_or_404
from app.services.principals import revalidated_principal, revalidated_principal_columns
from app.services.rbac import (
    get_effective_project_roles,
    get_project_member_user_ids,
    get_project_users_by_role,
    require_ai_approvals_enabled,
    require_project_view,
)
from app.services.relationships import create_link as create_artefact_link
from app.services.relationships import get_link_between as get_artefact_link_between
from app.services.requirements import (
    apply_new_version,
    create_requirement,
    get_current_version,
    get_current_version_for_update,
    resolve_type_or_422,
)


def _check_move(db: Session, cr: ChangeRequest, target: ChangeRequestStatus) -> None:
    """Refuses (409) a status move of the change request that the project's lifecycle for change requests does not allow.

    Args:
        db: Active session.
        cr: The change request, in its current status.
        target: The status it is moved to; a move to the status it already has is not a move.

    Raises:
        HTTPException: 409 naming the allowed next states.
    """
    if cr.status == target:
        return
    try:
        check_move(db, cr.project_id, "change_request", cr.status.value, target.value, record_id=cr.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


router = APIRouter(tags=["change-requests-workflow"])


def _decision_body(note: str, result) -> str:
    """The approval note plus, when links were proposed, how many were merged and how many were
    not, so a partial merge is never a surprise to the person who proposed them."""
    if result is None or result.total == 0:
        return note
    not_merged = result.total - result.merged
    summary = f"{result.merged} of {result.total} proposed link{'s' if result.total != 1 else ''} merged"
    if not_merged:
        parts = [f"{count} {label}" for count, label in ((result.declined, "left out"), (result.skipped, "not valid")) if count]
        summary += f" ({', '.join(parts)})"
    return f"{note}\n{summary}." if note else f"{summary}."


def _display_title(db: Session, cr: ChangeRequest, version: ChangeRequestVersion) -> str:
    """Human-readable label for a change request, used in notification titles. `proposed_name` alone is set
    only for NEW_REQUIREMENT, or MODIFY_REQUIREMENT when `"name"` is in `changed_fields`, so every other
    case needs a fallback rather than rendering "None". The request's qualified code leads the title
    (`ACME-CR-003 Wider doors`): a notification is read out of any project's context, so a bare `CR-003`
    would be ambiguous."""
    project = db.get(Project, cr.project_id)
    code = qualify(project.code, cr.unique_code) if project is not None else cr.unique_code
    return f"{code} {_title_text(db, cr, version)}"


def _title_text(db: Session, cr: ChangeRequest, version: ChangeRequestVersion) -> str:
    """The title text of `_display_title`, without the code."""
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
    _check_move(db, cr, ChangeRequestStatus.SUBMITTED)
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
    _check_move(db, cr, ChangeRequestStatus.WITHDRAWN)
    cr.status = ChangeRequestStatus.WITHDRAWN
    decline_all(_latest_version(db, cr))
    log_event(db, entity_type="change_request", entity_id=cr.id, action="withdrawn",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(cr)
    return _to_out(db, cr, _latest_version(db, cr), current_user.id)


def _require_decider(db: Session, user: User, project_id: UUID) -> None:
    """403 unless `user` may decide change requests of the project: a project manager, a holder of the change request
    `approve_baseline` permission or a holder of a role the project's approval policy names
    (`services.approval_policy`)."""
    project = project_or_404(db, project_id)
    approval_policy.require_approver(
        db, user, artefact_type="change_request", organization_id=project.organization_id, project_id=project_id,
        default=ProjectRole.PROJECT_MANAGER in get_effective_project_roles(db, user.id, project_id),
        denied="Only a project manager can decide change requests.",
    )


def _stale_selection(preview: ProposedLinkPreviewOut) -> HTTPException:
    """409 carrying a fresh preview, so the approver re-confirms rather than links being silently skipped."""
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "message": "Some of the links you chose can no longer be merged. Review the updated list and confirm again.",
            "preview": preview.model_dump(mode="json"),
        },
    )


@router.get("/{cr_id}/link-merge-preview", response_model=ProposedLinkPreviewOut)
def preview_change_request_links(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """What approving this change request would merge: each proposed link re-validated now.

    A link is selectable only if the request's creator could still create it and the caller
    (the would-be approver) can view its far end; an unselectable one carries the reason. Links
    of a decided request are shown with the outcome they ended in.

    Raises:
        HTTPException: 403 unless the caller may decide change requests; 404 unknown change request.
    """
    _require_decider(db, current_user, project_id)
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    version = _latest_version(db, cr)
    return ProposedLinkPreviewOut(rows=build_preview(db, project_or_404(db, project_id), cr, version, current_user.id))


@router.post("/{cr_id}/decide", response_model=ChangeRequestOut)
def decide_change_request(
    project_id: UUID, cr_id: UUID, payload: ChangeRequestDecision,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Approves or rejects a submitted change request (C-U-03: a project manager, or a holder of the change request
    `approve_baseline` permission or of a role the project's approval policy names).

    Approval applies the proposed change immediately: for a modification a new requirement version is
    created via the change-request path; for a new requirement it is created directly in approved state.

    Through the MCP server (`channel == "mcp"`) this additionally requires the project and its
    organisation to have enabled AI approval (see `requirements.approve_requirement` and docs/decisions.md's
    "AI approval via MCP" entry); a UI/API call is unaffected.
    """
    _require_decider(db, current_user, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project_or_404(db, project_id))

    # Row-locked: two concurrent /decide calls (one approve, one reject) would otherwise both read
    # status == SUBMITTED, both pass the check and both apply side effects, leaving cr.status out of step
    # with the requirement changes. The lock makes the second call see the first's committed result.
    cr = db.scalar(select(ChangeRequest).where(ChangeRequest.id == cr_id).with_for_update())
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    if cr.status not in (ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only submitted change requests can be decided.")
    _check_move(db, cr, ChangeRequestStatus.APPROVED if payload.approve else ChangeRequestStatus.REJECTED)
    if payload.approve:
        approval_separation.enforce_approval(
            db, user=current_user, artefact_type="change_request", record_id=cr.id, creator_id=cr.creator_id,
            organization_id=project_or_404(db, project_id).organization_id, project_id=project_id, comment=payload.note,
        )

    version = _latest_version(db, cr)
    if payload.approve and payload.merge_link_ids is not None:
        # Checked before anything is applied: a chosen link that has become invalid since the
        # approver looked is refused with a fresh preview, never silently left out.
        chosen = set(payload.merge_link_ids)
        pending_ids = {row.id for row in version.proposed_links}
        if not chosen <= pending_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "merge_link_ids names a link this change request does not propose.")
        rows = build_preview(db, project_or_404(db, project_id), cr, version, current_user.id)
        if any(row.link.id in chosen and not row.selectable for row in rows):
            raise _stale_selection(ProposedLinkPreviewOut(rows=rows))
    cr.decided_at = datetime.now(UTC)
    cr.decided_by = current_user.id
    cr.decision_note = payload.note
    link_result = None

    if payload.approve:
        cr.status = ChangeRequestStatus.APPROVED
        if cr.kind == ChangeRequestKind.MODIFY_REQUIREMENT:
            requirement = get_or_404(db, Requirement, cr.requirement_id, "Requirement")
            current_version = get_current_version_for_update(db, requirement.id)
            # Only fields listed in changed_fields are applied; the rest carry the current value forward
            # (`apply_new_version`'s convention) rather than being rewritten with a stale proposed value
            # (see ChangeRequestVersion.changed_fields and docs/decisions.md's "Change request field-level
            # tracking" entry).
            changed = set(version.changed_fields)
            apply_new_version(
                db, requirement, current_version, current_user,
                name=version.proposed_name if "name" in changed else None,
                reasoning=version.proposed_reasoning if "reasoning" in changed else None,
                clarification=version.proposed_clarification if "clarification" in changed else None,
                description=version.proposed_description if "description" in changed else None,
                # `None` carries the current status forward (`apply_new_version`'s convention): a
                # MODIFY_REQUIREMENT change request is only allowed against a locked (`APPROVED`) requirement
                # (see `create_change_request`), so approval must not rewrite the lifecycle status. The
                # completion overlay (`Requirement.is_completed`) is a separate field, cleared only through
                # `clear_completion` below.
                status_value=None,
                target_stage_id=version.proposed_target_stage_id, target_stage_explicitly_set="target_stage_id" in changed,
                level=version.proposed_level if "level" in changed else None,
                project_type_id=(
                    resolve_type_or_422(db, project_or_404(db, project_id), version.proposed_project_type_id)
                    if "type_id" in changed else None
                ),
                project_type_explicitly_set="type_id" in changed,
                change_note=f"Applied via approved change request: {version.reason}",
                change_request_id=cr.id,
                custom_fields=version.custom_fields if "custom_fields" in changed else None,
                review_date=version.proposed_review_date, review_date_explicitly_set="review_date" in changed,
                review_lead_days=version.proposed_review_lead_days, review_lead_days_explicitly_set="review_lead_days" in changed,
                reviewer=revalidated_principal(
                    db, version.proposed_reviewer_type, version.proposed_reviewer_id,
                    organization_id=project_or_404(db, project_id).organization_id, project_id=project_id, field="reviewer",
                ),
                reviewer_explicitly_set="reviewer_id" in changed,
            )
            if "attachments" in changed and version.proposed_attachment_file_ids:
                project = project_or_404(db, project_id)
                for raw_file_id in version.proposed_attachment_file_ids:
                    file_id = UUID(raw_file_id) if isinstance(raw_file_id, str) else raw_file_id
                    asset = db.get(FileAsset, file_id)
                    # Re-checked here, not trusted from creation time: the file could have been deleted
                    # or changed ownership since (the same "never trust a stale reference" posture as
                    # report image resolution).
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
            # C-G-11: an explicit, opt-in approver choice applied separately from the version-apply above
            # (which never touches `is_completed`). A no-op unless every precondition holds. Logged as an
            # audit event distinct from `approved` below, so the approver's deliberate choice is traceable.
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
            # Mirrors the "attachments" re-check above: the referenced action/action-type may have changed
            # or been archived since submission, so both are re-validated. `linked_by`/`creator_id` is
            # `cr.creator_id` (the submitter), as for `RequirementFile.linked_by`: an added action is a new
            # artefact the submitter contributes, whereas a requirement version's authorship follows the
            # approving PM.
            requirement = get_or_404(db, Requirement, cr.requirement_id, "Requirement")
            project = project_or_404(db, project_id)
            if version.proposed_action_link_id is not None:
                action = db.get(RequirementAction, version.proposed_action_link_id)
                if action is not None and action.project_id == project_id:
                    existing_link = get_artefact_link_between(
                        db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action.id,
                        target_type=ArtefactType.REQUIREMENT, target_id=requirement.id,
                    )
                    if existing_link is None:
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
                        **revalidated_principal_columns(
                            db, "assignee", version.proposed_action_assignee_type, version.proposed_action_assignee_id,
                            organization_id=project.organization_id, project_id=project_id,
                        ),
                        due_date=version.proposed_action_due_date,
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
            # Mirrors ADD_ACTION's re-check above: the link can be removed directly between submission and
            # approval, so it is re-verified rather than assumed.
            requirement = get_or_404(db, Requirement, cr.requirement_id, "Requirement")
            action_link = (
                get_artefact_link_between(
                    db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=version.proposed_action_link_id,
                    target_type=ArtefactType.REQUIREMENT, target_id=requirement.id,
                )
                if version.proposed_action_link_id is not None else None
            )
            if action_link is not None:
                log_event(
                    db, entity_type="requirement_action_link", entity_id=action_link.source_id, action="unlinked",
                    actor_id=current_user.id, project_id=project_id,
                    detail={
                        "requirement_id": str(requirement.id), "action_id": str(action_link.source_id),
                        "via": "change_request", "change_request_id": str(cr.id),
                    },
                )
                db.delete(action_link)
        elif cr.kind == ChangeRequestKind.ADD_LINK:
            # An add-link request is nothing but its proposed links, which
            # `resolve_links` below merges (re-validated now, as the approver chose).
            pass
        elif cr.kind == ChangeRequestKind.REMOVE_LINK:
            # Same re-check as ADD_LINK above: another path can remove the link between submission and
            # approval.
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
            project = project_or_404(db, project_id)
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
            count = db.scalar(select(func.count()).select_from(Requirement).where(Requirement.project_id == project_id)) or 0
            if not version.proposed_name:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "The change request proposes no requirement name.")
            requirement = create_requirement(
                db, project, component, category, current_user,
                name=version.proposed_name, reasoning=version.proposed_reasoning or "",
                clarification=version.proposed_clarification or "", description=version.proposed_description or "",
                owner=None, keywords=[], sort_order=count,
                target_stage_id=target_stage_id, level=version.proposed_level or RequirementLevel.REQUIREMENT,
                type_id=version.proposed_project_type_id,
                custom_fields=version.custom_fields,
                review_date=version.proposed_review_date, review_lead_days=version.proposed_review_lead_days,
                reviewer=revalidated_principal(
                    db, version.proposed_reviewer_type, version.proposed_reviewer_id,
                    organization_id=project.organization_id, project_id=project_id, field="reviewer",
                ),
            )
            db.flush()
            current_version = get_current_version(db, requirement.id)
            apply_new_version(
                db, requirement, current_version, current_user, status_value=RequirementStatus.APPROVED,
                change_note=f"Created via approved change request: {version.reason}", change_request_id=cr.id,
            )
            cr.requirement_id = requirement.id
        if version.proposed_links:
            link_result = resolve_links(
                db, project_or_404(db, project_id), cr, version, approver_id=current_user.id,
                merge_ids=set(payload.merge_link_ids) if payload.merge_link_ids is not None else None,
            )
        # Approving the request approves the requirement as it now stands, so the approval checks judge the result,
        # the proposed links included.
        if cr.requirement_id is not None:
            check_record_approval(db, project_or_404(db, project_id), current_user, "requirement", cr.requirement_id)
        change_requests_approved_total.inc()
    else:
        cr.status = ChangeRequestStatus.REJECTED
        decline_all(version)
        change_requests_rejected_total.inc()

    # The decision note is stored as `comment`, the key every other workflow step uses, so the
    # activity timeline shows it through one rule.
    decision_detail: dict = {"comment": payload.note} if payload.note else {}
    if channel == "mcp":
        decision_detail["via"] = "mcp"
    if link_result is not None:
        decision_detail["links"] = {
            "merged": link_result.merged, "declined": link_result.declined, "skipped": link_result.skipped,
        }
    log_event(
        db, entity_type="change_request", entity_id=cr.id,
        action="approved" if payload.approve else "rejected",
        actor_id=current_user.id, project_id=project_id,
        detail=decision_detail,
    )

    display_title = _display_title(db, cr, version)
    creator = db.get(User, cr.creator_id)
    if creator is not None:
        notifications.notify(
            db, creator,
            notification_type=NotificationType.CHANGE_REQUEST_APPROVED if payload.approve else NotificationType.CHANGE_REQUEST_REJECTED,
            title=f"Your change request was {'approved' if payload.approve else 'rejected'}: {display_title}",
            body=_decision_body(payload.note, link_result), project_id=project_id, entity_type="change_request", entity_id=str(cr.id),
            actor_id=current_user.id,
        )
    if payload.approve:
        project_name = project_or_404(db, project_id).name
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
