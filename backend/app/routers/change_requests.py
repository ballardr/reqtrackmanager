"""
Module: routers.change_requests

The formal change management workflow (introduction, C-G-03, C-G-12):
submitting a change request, reviewing/discussing it, and a project manager
approving or rejecting it. Approval applies the proposed change to the
target requirement (or creates a new one) through the same versioning
mechanism used for direct scoping-stage edits, so both paths share one
audit trail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.metrics import (
    change_requests_approved_total,
    change_requests_rejected_total,
    change_requests_submitted_total,
)
from app.models.change_request import ChangeRequest, ChangeRequestVersion, ReviewComment
from app.models.custom_field import CustomFieldEntityKind
from app.models.notification import NotificationType
from app.models.enums import (
    ChangeRequestKind,
    ChangeRequestStatus,
    ProjectRole,
    RequirementStatus,
    ReviewTargetType,
)
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement
from app.models.user import User
from app.schemas.change_request import ChangeRequestCreate, ChangeRequestDecision, ChangeRequestOut
from app.schemas.requirement import CommentCreate, CommentOut
from app.services import notifications, pubsub
from app.services.audit import log_event
from app.services.custom_fields import validate_custom_field_values
from app.services.rbac import (
    get_effective_project_roles,
    get_project_member_user_ids,
    get_project_users_by_role,
    require_project_view,
)
from app.services.requirements import apply_new_version, create_requirement, get_current_version

router = APIRouter(prefix="/api/v1/projects/{project_id}/change-requests", tags=["change-requests"])

CAN_SUBMIT_ROLES = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)


def _require_submit_role(db: Session, user: User, project_id: UUID) -> None:
    if user.is_server_admin:
        return
    if not get_effective_project_roles(db, user.id, project_id) & set(CAN_SUBMIT_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders, administrators, or managers may do this.")


def _require_can_create_change_request(db: Session, user: User, project: Project) -> None:
    """Like `_require_submit_role`, but also allows plain "members" when the
    project has enabled member change-request submission (C-U-13, defaults
    to enabled). Only applies to creating a change request — commenting on
    one still requires stakeholder+ regardless of this toggle.
    """
    if user.is_server_admin:
        return
    roles = get_effective_project_roles(db, user.id, project.id)
    allowed = set(CAN_SUBMIT_ROLES)
    if project.allow_member_change_requests:
        allowed.add(ProjectRole.MEMBER)
    if not roles & allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to submit change requests on this project.")


def _to_out(cr: ChangeRequest, version: ChangeRequestVersion) -> ChangeRequestOut:
    return ChangeRequestOut(
        id=cr.id, project_id=cr.project_id, requirement_id=cr.requirement_id, kind=cr.kind, status=cr.status,
        creator_id=cr.creator_id, proposed_name=version.proposed_name, proposed_reasoning=version.proposed_reasoning,
        proposed_clarification=version.proposed_clarification, reason=version.reason,
        custom_fields=version.custom_fields,
        submitted_at=cr.submitted_at, decided_at=cr.decided_at, decided_by=cr.decided_by,
        decision_note=cr.decision_note, created_at=cr.created_at,
    )


def _latest_version(db: Session, cr: ChangeRequest) -> ChangeRequestVersion:
    return db.scalars(
        select(ChangeRequestVersion)
        .where(ChangeRequestVersion.change_request_id == cr.id)
        .order_by(ChangeRequestVersion.version_number.desc())
    ).first()


@router.post("", response_model=ChangeRequestOut, status_code=status.HTTP_201_CREATED)
def create_change_request(
    project_id: UUID, payload: ChangeRequestCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Creates a draft change request (introduction: proposal + reason required)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    _require_can_create_change_request(db, current_user, project)
    if payload.kind == ChangeRequestKind.MODIFY_REQUIREMENT:
        if payload.requirement_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "requirement_id is required to modify a requirement.")
        requirement = db.get(Requirement, payload.requirement_id)
        if requirement is None or requirement.project_id != project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid requirement_id.")

    # Validated against the *requirement* entity kind, not change_request: these
    # values represent proposed custom-attribute values for the requirement
    # being created/modified (mirroring proposed_name/proposed_reasoning),
    # copied onto the requirement's version on approval. A separate
    # `CustomFieldEntityKind.CHANGE_REQUEST` kind exists in the data model for
    # attributes describing the change request itself (e.g. "urgency"); v1
    # doesn't yet have a workflow step that consumes those, so none are
    # collected here — see docs/decisions.md.
    custom_fields = validate_custom_field_values(db, project_id, CustomFieldEntityKind.REQUIREMENT, payload.custom_fields)

    creator_id = current_user.id
    if payload.creator_id is not None:
        # PM re-attributing authorship at creation time (C-A-12).
        if not current_user.is_server_admin and ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(
            db, current_user.id, project_id
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can assign the creator.")
        creator_id = payload.creator_id

    cr = ChangeRequest(
        project_id=project_id, requirement_id=payload.requirement_id, kind=payload.kind,
        status=ChangeRequestStatus.DRAFT, creator_id=creator_id,
    )
    db.add(cr)
    db.flush()
    version = ChangeRequestVersion(
        change_request_id=cr.id, version_number=1, proposed_name=payload.proposed_name,
        proposed_reasoning=payload.proposed_reasoning, proposed_clarification=payload.proposed_clarification,
        proposed_component_id=payload.proposed_component_id, proposed_category_id=payload.proposed_category_id,
        reason=payload.reason, custom_fields=custom_fields,
        created_by=current_user.id, created_at=datetime.now(timezone.utc),
    )
    db.add(version)
    log_event(db, entity_type="change_request", entity_id=cr.id, action="created",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(cr)
    return _to_out(cr, version)


@router.get("", response_model=list[ChangeRequestOut])
def list_change_requests(
    project_id: UUID, cr_status: ChangeRequestStatus | None = None,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    query = select(ChangeRequest).where(ChangeRequest.project_id == project_id)
    if cr_status:
        query = query.where(ChangeRequest.status == cr_status)
    crs = db.scalars(query).all()
    return [_to_out(cr, _latest_version(db, cr)) for cr in crs]


@router.get("/{cr_id}", response_model=ChangeRequestOut)
def get_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    return _to_out(cr, _latest_version(db, cr))


@router.post("/{cr_id}/submit", response_model=ChangeRequestOut)
def submit_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Submits a draft change request for review."""
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    if cr.creator_id != current_user.id and not current_user.is_server_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the creator may submit this change request.")
    if cr.status != ChangeRequestStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only draft change requests can be submitted.")
    cr.status = ChangeRequestStatus.SUBMITTED
    cr.submitted_at = datetime.now(timezone.utc)
    log_event(db, entity_type="change_request", entity_id=cr.id, action="submitted",
              actor_id=current_user.id, project_id=project_id)
    change_requests_submitted_total.inc()

    version = _latest_version(db, cr)
    for user_id in get_project_users_by_role(db, project_id, ProjectRole.PROJECT_MANAGER):
        user = db.get(User, user_id)
        if user is not None:
            notifications.notify(
                db, user, notification_type=NotificationType.CHANGE_REQUEST_SUBMITTED,
                title=f"Change request submitted: {version.proposed_name}",
                project_id=project_id, entity_type="change_request", entity_id=str(cr.id),
            )
    for user_id in get_project_users_by_role(db, project_id, ProjectRole.STAKEHOLDER):
        user = db.get(User, user_id)
        if user is not None:
            notifications.notify(
                db, user, notification_type=NotificationType.STAKEHOLDER_INPUT_REQUESTED,
                title=f"Your input is requested: {version.proposed_name}",
                project_id=project_id, entity_type="change_request", entity_id=str(cr.id),
            )

    db.commit()
    db.refresh(cr)
    pubsub.notify(project_id, {"type": "change_request", "action": "submitted", "id": str(cr.id)})
    return _to_out(cr, _latest_version(db, cr))


@router.post("/{cr_id}/withdraw", response_model=ChangeRequestOut)
def withdraw_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    if cr.creator_id != current_user.id and not current_user.is_server_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the creator may withdraw this change request.")
    if cr.status in (ChangeRequestStatus.APPROVED, ChangeRequestStatus.REJECTED):
        raise HTTPException(status.HTTP_409_CONFLICT, "This change request has already been decided.")
    cr.status = ChangeRequestStatus.WITHDRAWN
    log_event(db, entity_type="change_request", entity_id=cr.id, action="withdrawn",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(cr)
    return _to_out(cr, _latest_version(db, cr))


@router.post("/{cr_id}/decide", response_model=ChangeRequestOut)
def decide_change_request(
    project_id: UUID, cr_id: UUID, payload: ChangeRequestDecision,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Approves or rejects a submitted change request (C-U-03: project manager only).

    Approval applies the proposed change immediately: for a modification, a
    new requirement version is created via the change-request path; for a
    new requirement, the requirement is created directly in approved state.
    """
    if not current_user.is_server_admin and ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(
        db, current_user.id, project_id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can decide change requests.")

    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    if cr.status not in (ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only submitted change requests can be decided.")

    version = _latest_version(db, cr)
    cr.decided_at = datetime.now(timezone.utc)
    cr.decided_by = current_user.id
    cr.decision_note = payload.note

    if payload.approve:
        cr.status = ChangeRequestStatus.APPROVED
        if cr.kind == ChangeRequestKind.MODIFY_REQUIREMENT:
            requirement = db.get(Requirement, cr.requirement_id)
            current_version = get_current_version(db, requirement.id)
            apply_new_version(
                db, requirement, current_version, current_user,
                name=version.proposed_name, reasoning=version.proposed_reasoning,
                clarification=version.proposed_clarification, status_value=RequirementStatus.APPROVED,
                change_note=f"Applied via approved change request: {version.reason}",
                change_request_id=cr.id, custom_fields=version.custom_fields,
            )
        else:
            project = db.get(Project, project_id)
            component = db.get(ProjectComponent, version.proposed_component_id)
            category = db.get(ProjectCategory, version.proposed_category_id)
            if component is None or category is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Change request is missing component/category.")
            count = len(db.scalars(select(Requirement.id).where(Requirement.project_id == project_id)).all())
            requirement = create_requirement(
                db, project, component, category, current_user,
                name=version.proposed_name, reasoning=version.proposed_reasoning,
                clarification=version.proposed_clarification, owner_id=None, keywords=[], sort_order=count,
                custom_fields=version.custom_fields,
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
        actor_id=current_user.id, project_id=project_id, detail={"note": payload.note},
    )

    creator = db.get(User, cr.creator_id)
    if creator is not None:
        notifications.notify(
            db, creator,
            notification_type=NotificationType.CHANGE_REQUEST_APPROVED if payload.approve else NotificationType.CHANGE_REQUEST_REJECTED,
            title=f"Your change request was {'approved' if payload.approve else 'rejected'}: {version.proposed_name}",
            body=payload.note, project_id=project_id, entity_type="change_request", entity_id=str(cr.id),
        )
    if payload.approve:
        project_name = db.get(Project, project_id).name
        for user_id in get_project_member_user_ids(db, project_id):
            user = db.get(User, user_id)
            if user is not None:
                notifications.notify(
                    db, user, notification_type=NotificationType.REQUIREMENTS_UPDATED,
                    title=f"{project_name}: requirements updated via change request",
                    body=version.proposed_name, project_id=project_id,
                    entity_type="change_request", entity_id=str(cr.id),
                )

    db.commit()
    db.refresh(cr)
    pubsub.notify(project_id, {"type": "change_request", "action": cr.status.value, "id": str(cr.id)})
    return _to_out(cr, version)


def _get_cr_in_project(db: Session, project_id: UUID, cr_id: UUID) -> ChangeRequest:
    """Loads a change request and 404s unless it belongs to `project_id`.

    Prevents an IDOR where a member of one project could read/write
    comments on a change request belonging to a different project by
    supplying its id, since role checks below only validate against
    `project_id`.
    """
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    return cr


@router.post("/{cr_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(
    project_id: UUID, cr_id: UUID, payload: CommentCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Adds a discussion thread comment on a change request (C-R-01)."""
    _require_submit_role(db, current_user, project_id)
    _get_cr_in_project(db, project_id, cr_id)
    comment = ReviewComment(
        target_type=ReviewTargetType.CHANGE_REQUEST, target_id=cr_id, author_id=current_user.id, body=payload.body,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/{cr_id}/comments", response_model=list[CommentOut])
def list_comments(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_cr_in_project(db, project_id, cr_id)
    return db.scalars(
        select(ReviewComment)
        .where(ReviewComment.target_type == ReviewTargetType.CHANGE_REQUEST, ReviewComment.target_id == cr_id)
        .order_by(ReviewComment.created_at)
    ).all()
