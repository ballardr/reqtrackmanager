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

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.metrics import (
    change_requests_approved_total,
    change_requests_rejected_total,
    change_requests_submitted_total,
)
from app.models.action_type import ActionTypeDefinition
from app.models.change_request import (
    ChangeRequest,
    ChangeRequestTask,
    ChangeRequestVersion,
    ChangeRequestVote,
    ReviewComment,
)
from app.models.custom_field import CustomFieldEntityKind
from app.models.enums import (
    ChangeRequestKind,
    ChangeRequestStatus,
    ChangeRequestVoteChoice,
    ProjectRole,
    RequirementLevel,
    RequirementStatus,
    ReviewTargetType,
)
from app.models.file import CommentFile, FileAsset, RequirementFile
from app.models.notification import NotificationType
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.requirement import Requirement
from app.models.requirement_action import RequirementAction, RequirementActionLink
from app.models.user import User
from app.schemas.change_request import (
    CHANGEABLE_REQUIREMENT_FIELDS,
    FIELDS_REQUIRING_A_VALUE_WHEN_CHANGED,
    ChangeRequestCreate,
    ChangeRequestDecision,
    ChangeRequestOut,
    ChangeRequestTaskCreate,
    ChangeRequestTaskOut,
    ChangeRequestTaskUpdate,
    ChangeRequestVoteCreate,
    ChangeRequestVoteOut,
    ChangeRequestVoteTallyOut,
)
from app.schemas.changes import ChangeEntryOut
from app.schemas.file import FileAssetOut
from app.schemas.requirement import CommentCreate, CommentOut, CommentUpdate
from app.services import engagement, notifications, pubsub
from app.services.actions import generate_unique_code as generate_action_unique_code
from app.services.actions import get_requirement_action_in_project
from app.services.audit import log_event
from app.services.changes import get_project_changes
from app.services.custom_fields import validate_custom_field_values
from app.services.files import upload_file
from app.services.rbac import (
    get_effective_project_roles,
    get_project_member_user_ids,
    get_project_users_by_role,
    require_project_manage,
    require_project_role,
    require_project_view,
)
from app.services.requirements import apply_new_version, create_requirement, get_current_version, is_locked

router = APIRouter(prefix="/api/v1/projects/{project_id}/change-requests", tags=["change-requests"])

CAN_SUBMIT_ROLES = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)


def _require_submit_role(db: Session, user: User, project_id: UUID) -> None:
    """Raises 403 unless `user` holds a change-request role on the project.

    No server-admin bypass (I-M-05): change request content is "data within
    organisations".
    """
    if not get_effective_project_roles(db, user.id, project_id) & set(CAN_SUBMIT_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders, administrators, or managers may do this.")


def _require_can_create_change_request(db: Session, user: User, project: Project) -> None:
    """Like `_require_submit_role`, but also allows plain "members" when the
    project has enabled member change-request submission (C-U-13, defaults
    to enabled). Only applies to creating a change request — commenting on
    one still requires stakeholder+ regardless of this toggle.
    """
    roles = get_effective_project_roles(db, user.id, project.id)
    allowed = set(CAN_SUBMIT_ROLES)
    if project.allow_member_change_requests:
        allowed.add(ProjectRole.MEMBER)
    if not roles & allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to submit change requests on this project.")


OPEN_CR_STATUSES = (ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW)


def _to_out(db: Session, cr: ChangeRequest, version: ChangeRequestVersion, current_user_id: UUID) -> ChangeRequestOut:
    """Builds the API response shape for a change request from its identity
    row plus one version snapshot, including `current_user_id`'s
    subscription state (C-N-01) and derived list-view badge indicators."""
    return ChangeRequestOut(
        id=cr.id, project_id=cr.project_id, requirement_id=cr.requirement_id, kind=cr.kind, status=cr.status,
        creator_id=cr.creator_id, changed_fields=version.changed_fields,
        proposed_name=version.proposed_name, proposed_reasoning=version.proposed_reasoning,
        proposed_clarification=version.proposed_clarification, proposed_description=version.proposed_description,
        proposed_target_stage_id=version.proposed_target_stage_id, proposed_level=version.proposed_level,
        proposed_attachment_file_ids=version.proposed_attachment_file_ids,
        reason=version.reason,
        custom_fields=version.custom_fields,
        submitted_at=cr.submitted_at, decided_at=cr.decided_at, decided_by=cr.decided_by,
        decision_note=cr.decision_note, created_at=cr.created_at,
        is_subscribed=engagement.is_subscribed(db, current_user_id, "change_request", cr.id),
        comment_count=engagement.get_comment_count(db, ReviewTargetType.CHANGE_REQUEST, cr.id),
        requires_approval=cr.status in OPEN_CR_STATUSES,
        proposed_review_date=version.proposed_review_date,
        proposed_review_lead_days=version.proposed_review_lead_days,
        proposed_reviewer_id=version.proposed_reviewer_id,
        proposed_action_link_id=version.proposed_action_link_id,
        proposed_action_title=version.proposed_action_title,
        proposed_action_description=version.proposed_action_description,
        proposed_action_type_id=version.proposed_action_type_id,
        proposed_action_assignee_id=version.proposed_action_assignee_id,
        proposed_action_due_date=version.proposed_action_due_date,
    )


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


def _latest_version(db: Session, cr: ChangeRequest) -> ChangeRequestVersion:
    """Returns the most recently created version row for a change request."""
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
    """Creates a draft change request (introduction: proposal + reason required).

    For a MODIFY_REQUIREMENT change request, `changed_fields` is the
    authoritative list of what this change request actually proposes to
    change — a field's `proposed_*` value is ignored entirely if its name
    isn't listed (see `ChangeRequestCreate`'s docstring). NEW_REQUIREMENT
    change requests ignore `changed_fields` and always require `proposed_name`
    directly, since there's no existing requirement to diff against.
    """
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
        # Requirement-status guard (2026-08 UX audit roadmap, "No requirement
        # approval action; change requests can target draft requirements"):
        # a change request exists to gate edits once direct editing is
        # locked (`LOCKED_STATUSES = {APPROVED, COMPLETED}`,
        # services/requirements.py:25) — a draft or reviewed requirement
        # isn't locked, so it should be edited directly
        # (routers/requirements.py::update_requirement), not through a
        # change request. Extends that existing precedent rather than
        # inventing a new one.
        if not is_locked(get_current_version(db, requirement.id)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This requirement isn't approved yet — edit it directly instead of via a change request.",
            )
        unknown_fields = set(payload.changed_fields) - CHANGEABLE_REQUIREMENT_FIELDS
        if unknown_fields:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown changed_fields: {sorted(unknown_fields)}.")
        if not payload.changed_fields:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one field must be selected to change.")
        for field_name, attr_name in FIELDS_REQUIRING_A_VALUE_WHEN_CHANGED.items():
            if field_name in payload.changed_fields and getattr(payload, attr_name) is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"proposed value for '{field_name}' is required since it's listed in changed_fields.",
                )
        if "attachments" in payload.changed_fields and not payload.proposed_attachment_file_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "proposed_attachment_file_ids is required since 'attachments' is listed in changed_fields."
            )
    elif payload.kind == ChangeRequestKind.ADD_ACTION:
        # Item 514 — mirrors MODIFY_REQUIREMENT's own guard above: adding an
        # action is only routed through a change request once the target
        # requirement is locked; while it's still draft/reviewed, add it
        # directly (routers/requirements.py::create_and_link_action/
        # link_action), which now reject the direct path once locked.
        if payload.requirement_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "requirement_id is required to add an action.")
        requirement = db.get(Requirement, payload.requirement_id)
        if requirement is None or requirement.project_id != project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid requirement_id.")
        if not is_locked(get_current_version(db, requirement.id)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This requirement isn't approved yet — add the action directly instead of via a change request.",
            )
        # Mutually exclusive, mirroring the requirement detail page's own
        # "Link existing action" vs. "Create and link a new action" split —
        # exactly one of the two modes, never both, never neither.
        has_link = payload.proposed_action_link_id is not None
        has_new = payload.proposed_action_title is not None or payload.proposed_action_type_id is not None
        if has_link == has_new:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Provide either proposed_action_link_id (to link an existing action) or "
                "proposed_action_title and proposed_action_type_id (to create a new one) — not both, not neither.",
            )
        if has_link:
            action = get_requirement_action_in_project(db, project_id, payload.proposed_action_link_id)
            existing = db.scalar(
                select(RequirementActionLink).where(
                    RequirementActionLink.requirement_id == requirement.id, RequirementActionLink.action_id == action.id
                )
            )
            if existing is not None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "This action is already linked to this requirement.")
        else:
            if payload.proposed_action_title is None or not payload.proposed_action_title.strip():
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposed_action_title is required to create a new action.")
            if payload.proposed_action_type_id is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposed_action_type_id is required to create a new action.")
            action_type = db.get(ActionTypeDefinition, payload.proposed_action_type_id)
            if action_type is None or action_type.project_id != project_id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "proposed_action_type_id must be an action type defined in this project."
                )
    else:
        # NEW_REQUIREMENT ignores changed_fields entirely (there's no
        # existing version to diff against) but still needs the fields a
        # brand-new requirement can never be without.
        if payload.proposed_name is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposed_name is required for a new requirement.")
        # proposed_target_stage_id may be omitted — approval defaults it to
        # the project's earliest stage, same as a direct create
        # (routers/requirements.py::create_requirement_endpoint).
        # Hardening-review finding: proposed_component_id/proposed_category_id
        # for a new_requirement change request were never validated against
        # project_id at all — unlike the direct-create path
        # (create_requirement_endpoint), which checks component.project_id/
        # category.project_id explicitly. There's no update endpoint for a
        # change request's proposed_* fields (they're write-once, set only
        # here at creation — confirmed via schemas/change_request.py), so
        # this is the one place this ever needs checking; decide_change_request
        # only re-checked `is None`, not project membership, so an
        # unvalidated cross-project reference would have sailed through
        # approval unchanged and been baked into a real Requirement row.
        component = None
        if payload.proposed_component_id is not None:
            component = db.get(ProjectComponent, payload.proposed_component_id)
            if component is None or component.project_id != project_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid proposed_component_id.")
        if payload.proposed_category_id is not None:
            category = db.get(ProjectCategory, payload.proposed_category_id)
            if category is None or category.project_id != project_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid proposed_category_id.")
            if component is not None and category.component_id != component.id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "proposed_category_id does not belong to proposed_component_id."
                )

    if payload.proposed_attachment_file_ids:
        # Same cross-org isolation check report images use
        # (routers/reports.py::_resolve_report_images) — an attachment
        # proposed here must already be an org shared resource belonging to
        # this project's own organisation, not an arbitrary file id from
        # anywhere else in the system.
        for file_id in payload.proposed_attachment_file_ids:
            asset = db.get(FileAsset, file_id)
            if asset is None or asset.organization_id != project.organization_id or not asset.is_org_resource:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid proposed attachment file id: {file_id}.")

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
        if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project_id):
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
        proposed_description=payload.proposed_description,
        proposed_component_id=payload.proposed_component_id, proposed_category_id=payload.proposed_category_id,
        proposed_target_stage_id=payload.proposed_target_stage_id, proposed_level=payload.proposed_level,
        proposed_attachment_file_ids=[str(f) for f in payload.proposed_attachment_file_ids],
        changed_fields=payload.changed_fields if payload.kind == ChangeRequestKind.MODIFY_REQUIREMENT else [],
        reason=payload.reason, custom_fields=custom_fields,
        created_by=current_user.id, created_at=datetime.now(UTC),
        proposed_review_date=payload.proposed_review_date,
        proposed_review_lead_days=payload.proposed_review_lead_days,
        proposed_reviewer_id=payload.proposed_reviewer_id,
        proposed_action_link_id=payload.proposed_action_link_id,
        proposed_action_title=payload.proposed_action_title,
        proposed_action_description=payload.proposed_action_description,
        proposed_action_type_id=payload.proposed_action_type_id,
        proposed_action_assignee_id=payload.proposed_action_assignee_id,
        proposed_action_due_date=payload.proposed_action_due_date,
    )
    db.add(version)
    log_event(db, entity_type="change_request", entity_id=cr.id, action="created",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(cr)
    return _to_out(db, cr, version, current_user.id)


@router.get("", response_model=list[ChangeRequestOut])
def list_change_requests(
    project_id: UUID,
    response: Response,
    cr_status: ChangeRequestStatus | None = None,
    active_only: bool = False,
    target_stage_id: UUID | None = None,
    sort: str | None = Query(None, pattern="^(proposed_name|status|created_at)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists change requests, with optional status/target-version filters.
    `limit`/`offset` (U-P-06) are optional pagination — see `list_requirements`
    for the same pattern.

    `active_only` (2026-08 UX audit roadmap, "Default Change Requests to
    an active-only status filter") filters to the three non-terminal
    statuses (`draft`/`submitted`/`in_review`) in one round trip, so the
    frontend's default view doesn't have to request every status and then
    hide `approved`/`rejected`/`withdrawn` rows client-side — with the
    list backend-paginated (`limit`/`offset`), a client-only filter would
    silently filter just the current page rather than the true result
    set. Ignored when `cr_status` is also given — an explicit single
    status is more specific than "any active status" and wins.

    `sort` (2026-08 UX audit roadmap, "Column-header sorting on data
    tables") optionally sorts by `proposed_name`, `status`, or
    `created_at`, `order` picks `asc` (default) or `desc`. Omitting `sort`
    keeps the existing default (creation/query) order unchanged. Rows with
    no `proposed_name` (a MODIFY_REQUIREMENT change request that didn't
    touch the name — the list view falls back to the requirement's own
    name for display, see `crTitle()` in `ChangeRequestsPage.tsx`) sort as
    if empty, since sorting by the raw column can't resolve that per-row
    fallback without an extra join.
    """
    query = select(ChangeRequest).where(ChangeRequest.project_id == project_id)
    if cr_status:
        query = query.where(ChangeRequest.status == cr_status)
    elif active_only:
        query = query.where(ChangeRequest.status.in_([
            ChangeRequestStatus.DRAFT, ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW,
        ]))
    crs = db.scalars(query).all()
    out = []
    for cr in crs:
        version = _latest_version(db, cr)
        if target_stage_id and version.proposed_target_stage_id != target_stage_id:
            continue
        out.append(_to_out(db, cr, version, current_user.id))

    if sort:
        def _sort_value(item: ChangeRequestOut):
            value = getattr(item, sort)
            if isinstance(value, str):
                value = value.lower()
            return value or ""
        out.sort(key=_sort_value, reverse=(order == "desc"))

    response.headers["X-Total-Count"] = str(len(out))
    if limit is not None:
        out = out[offset:offset + limit]
    return out


@router.get("/{cr_id}", response_model=ChangeRequestOut)
def get_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    return _to_out(db, cr, _latest_version(db, cr), current_user.id)


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
):
    """Approves or rejects a submitted change request (C-U-03: project manager only).

    Approval applies the proposed change immediately: for a modification, a
    new requirement version is created via the change-request path; for a
    new requirement, the requirement is created directly in approved state.
    """
    if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can decide change requests.")

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
                # action") — silently reverted an already-`COMPLETED`
                # requirement back to `APPROVED` as a side effect of any
                # modify-CR approval. `create_change_request`'s own guard
                # (above) now only allows a MODIFY_REQUIREMENT change
                # request against an already-locked (`APPROVED`/`COMPLETED`)
                # requirement, so the current status is always one of those
                # two by the time it's decided — `None` carries it forward
                # unchanged (`apply_new_version`'s own convention) instead
                # of forcing it back down to `APPROVED`.
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
                    existing = db.scalar(
                        select(RequirementActionLink).where(
                            RequirementActionLink.requirement_id == requirement.id, RequirementActionLink.action_id == action.id
                        )
                    )
                    if existing is None:
                        db.add(RequirementActionLink(
                            requirement_id=requirement.id, action_id=action.id, linked_by=cr.creator_id,
                            created_at=datetime.now(UTC),
                        ))
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
                    db.add(RequirementActionLink(
                        requirement_id=requirement.id, action_id=action.id, linked_by=cr.creator_id,
                        created_at=datetime.now(UTC),
                    ))
                    log_event(
                        db, entity_type="requirement_action", entity_id=action.id, action="created",
                        actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
                        detail={
                            "unique_code": action.unique_code, "title": action.title,
                            "linked_requirement_id": str(requirement.id),
                            "via": "change_request", "change_request_id": str(cr.id),
                        },
                    )
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
        actor_id=current_user.id, project_id=project_id, detail={"note": payload.note},
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


@router.get("/{cr_id}/activity", response_model=list[ChangeEntryOut])
def change_request_activity(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Per-entity activity timeline for the change request detail view's side
    panel (mock's "Subscribed" activity log). Excludes discussion comments,
    shown separately."""
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    entries = get_project_changes(db, project_id, since=None, until=None, include_comments=False)
    return [e for e in entries if e.entity_type == "change_request" and e.entity_id == str(cr_id)]


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


@router.post("/{cr_id}/tasks", response_model=ChangeRequestTaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    project_id: UUID, cr_id: UUID, payload: ChangeRequestTaskCreate,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Assigns a task during a change request's review (C-R-02, C-R-04)."""
    cr = _get_cr_in_project(db, project_id, cr_id)
    task = ChangeRequestTask(
        change_request_id=cr.id, description=payload.description,
        assignee_id=payload.assignee_id, due_date=payload.due_date, created_by=current_user.id,
    )
    db.add(task)
    db.flush()
    log_event(db, entity_type="change_request_task", entity_id=task.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"description": task.description})
    db.commit()
    db.refresh(task)
    return task


@router.get("/{cr_id}/tasks", response_model=list[ChangeRequestTaskOut])
def list_tasks(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    cr = _get_cr_in_project(db, project_id, cr_id)
    return db.scalars(
        select(ChangeRequestTask).where(ChangeRequestTask.change_request_id == cr.id).order_by(ChangeRequestTask.created_at)
    ).all()


@router.patch("/{cr_id}/tasks/{task_id}", response_model=ChangeRequestTaskOut)
def update_task(
    project_id: UUID, cr_id: UUID, task_id: UUID, payload: ChangeRequestTaskUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Edits a task, or marks it done/undone.

    A project manager can edit anything. A task's own assignee may toggle
    `is_done` on their own task without manager rights, but may not reassign
    or reschedule it.
    """
    cr = _get_cr_in_project(db, project_id, cr_id)
    task = db.get(ChangeRequestTask, task_id)
    if task is None or task.change_request_id != cr.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")

    is_manager = ProjectRole.PROJECT_MANAGER in get_effective_project_roles(db, current_user.id, project_id)
    is_own_task_done_toggle = (
        task.assignee_id == current_user.id
        and payload.description is None and payload.assignee_id is None and payload.due_date is None
        and payload.is_done is not None
    )
    if not (is_manager or is_own_task_done_toggle):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager, or the task's own assignee toggling done-status, may edit this task.")

    if payload.description is not None:
        task.description = payload.description
    if payload.assignee_id is not None:
        task.assignee_id = payload.assignee_id
    if payload.due_date is not None:
        task.due_date = payload.due_date
    if payload.is_done is not None:
        task.is_done = payload.is_done
        task.completed_at = datetime.now(UTC) if payload.is_done else None
    log_event(db, entity_type="change_request_task", entity_id=task.id, action="updated",
              actor_id=current_user.id, project_id=project_id, detail={"is_done": task.is_done})
    db.commit()
    db.refresh(task)
    return task


@router.post("/{cr_id}/votes", response_model=ChangeRequestVoteOut)
def cast_vote(
    project_id: UUID, cr_id: UUID, payload: ChangeRequestVoteCreate,
    current_user: User = Depends(require_project_role(ProjectRole.STAKEHOLDER)), db: Session = Depends(get_db),
):
    """Casts (or updates) the caller's advisory vote on a change request (C-R-03).

    Advisory only — see `models.change_request.ChangeRequestVote`'s
    docstring. Voting again before a decision is made updates the existing
    vote rather than creating a duplicate.
    """
    cr = _get_cr_in_project(db, project_id, cr_id)
    if cr.status not in OPEN_CR_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Voting is only open while a change request is under review.")

    existing = db.scalar(
        select(ChangeRequestVote).where(ChangeRequestVote.change_request_id == cr.id, ChangeRequestVote.user_id == current_user.id)
    )
    if existing is not None:
        existing.vote = payload.vote
        existing.comment = payload.comment
        existing.voted_at = datetime.now(UTC)
        vote = existing
    else:
        vote = ChangeRequestVote(
            change_request_id=cr.id, user_id=current_user.id, vote=payload.vote,
            comment=payload.comment, voted_at=datetime.now(UTC),
        )
        db.add(vote)
    db.flush()
    log_event(db, entity_type="change_request_vote", entity_id=vote.id, action="cast",
              actor_id=current_user.id, project_id=project_id, detail={"vote": payload.vote.value})
    db.commit()
    db.refresh(vote)
    return vote


@router.get("/{cr_id}/votes", response_model=ChangeRequestVoteTallyOut)
def list_votes(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    cr = _get_cr_in_project(db, project_id, cr_id)
    votes = db.scalars(select(ChangeRequestVote).where(ChangeRequestVote.change_request_id == cr.id)).all()
    return ChangeRequestVoteTallyOut(
        votes=list(votes),
        approve_count=sum(1 for v in votes if v.vote == ChangeRequestVoteChoice.APPROVE),
        reject_count=sum(1 for v in votes if v.vote == ChangeRequestVoteChoice.REJECT),
    )


@router.post("/{cr_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(
    project_id: UUID, cr_id: UUID, payload: CommentCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Adds a discussion thread comment on a change request (C-R-01), notifying subscribers."""
    _require_submit_role(db, current_user, project_id)
    _get_cr_in_project(db, project_id, cr_id)
    comment = ReviewComment(
        target_type=ReviewTargetType.CHANGE_REQUEST, target_id=cr_id, author_id=current_user.id, body=payload.body,
    )
    db.add(comment)
    db.flush()

    for subscriber_id in engagement.get_subscriber_ids(db, "change_request", cr_id, exclude_user_id=current_user.id):
        subscriber = db.get(User, subscriber_id)
        if subscriber is not None:
            notifications.notify(
                db, subscriber, notification_type=NotificationType.COMMENT_ADDED,
                title="New comment on a change request you follow",
                body=payload.body[:200],
                project_id=project_id, entity_type="change_request", entity_id=str(cr_id),
                actor_id=current_user.id,
            )
    db.commit()
    db.refresh(comment)
    return engagement.comment_to_out(db, comment, current_user.id)


@router.get("/{cr_id}/comments", response_model=list[CommentOut])
def list_comments(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_cr_in_project(db, project_id, cr_id)
    comments = db.scalars(
        select(ReviewComment)
        .where(ReviewComment.target_type == ReviewTargetType.CHANGE_REQUEST, ReviewComment.target_id == cr_id)
        .order_by(ReviewComment.created_at)
    ).all()
    return [engagement.comment_to_out(db, c, current_user.id) for c in comments]


@router.post("/{cr_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_comment_attachment(
    project_id: UUID, cr_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Uploads a file attached to a discussion comment on a change request
    — see `routers/requirements.py::upload_comment_attachment`'s docstring
    for why this is never subject to a lock (comments aren't governed
    content), and is author-only (attaching to composing/editing your own
    comment only)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    _get_cr_in_project(db, project_id, cr_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_type != ReviewTargetType.CHANGE_REQUEST or comment.target_id != cr_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(CommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type="change_request", entity_id=cr_id, action="comment_file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{cr_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_comment_attachment(
    project_id: UUID, cr_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Removes a file from a change-request comment — see
    `routers/requirements.py::remove_comment_attachment`'s docstring."""
    _get_cr_in_project(db, project_id, cr_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_type != ReviewTargetType.CHANGE_REQUEST or comment.target_id != cr_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may remove its attachments.")
    link = db.scalar(select(CommentFile).where(CommentFile.comment_id == comment.id, CommentFile.file_id == file_id))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this comment.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    if asset is not None:
        db.delete(asset)
    db.commit()


@router.patch("/{cr_id}/comments/{comment_id}", response_model=CommentOut)
def edit_comment(
    project_id: UUID, cr_id: UUID, comment_id: UUID, payload: CommentUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Edits a change-request comment's body — see
    `routers/requirements.py::edit_comment`'s docstring."""
    _get_cr_in_project(db, project_id, cr_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_type != ReviewTargetType.CHANGE_REQUEST or comment.target_id != cr_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return engagement.comment_to_out(db, comment, current_user.id)


@router.put("/{cr_id}/comments/{comment_id}/reaction", status_code=status.HTTP_204_NO_CONTENT)
def react_to_comment(
    project_id: UUID, cr_id: UUID, comment_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_cr_in_project(db, project_id, cr_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_id != cr_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    engagement.add_reaction(db, comment_id, current_user.id)


@router.delete("/{cr_id}/comments/{comment_id}/reaction", status_code=status.HTTP_204_NO_CONTENT)
def unreact_to_comment(
    project_id: UUID, cr_id: UUID, comment_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_cr_in_project(db, project_id, cr_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_id != cr_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    engagement.remove_reaction(db, comment_id, current_user.id)


@router.put("/{cr_id}/subscription", status_code=status.HTTP_204_NO_CONTENT)
def subscribe_to_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_cr_in_project(db, project_id, cr_id)
    engagement.subscribe(db, current_user.id, "change_request", cr_id)


@router.delete("/{cr_id}/subscription", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe_from_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_cr_in_project(db, project_id, cr_id)
    engagement.unsubscribe(db, current_user.id, "change_request", cr_id)
