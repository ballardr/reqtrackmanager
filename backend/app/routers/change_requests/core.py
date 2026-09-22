"""
Module: routers.change_requests.core

Change request creation and read paths (introduction, C-G-03, C-G-12):
drafting a change request (against an existing requirement, or proposing a
new one, an action add/remove, or a link add/remove), listing/fetching one,
and its per-entity activity timeline. Also home for `_to_out`/`_latest_version`
(imported by `workflow.py`, the only other bucket that needs them),
`CAN_SUBMIT_ROLES` (imported by `comments.py`), and `OPEN_CR_STATUSES`
(imported by `votes.py`) — each used by exactly one sibling bucket besides
this one, so kept here rather than promoted to `_shared.py` (see that
module's own docstring for the "used by 3+ buckets" threshold).

Split out of the former flat `routers/change_requests.py` as a pure
code-organization refactor — see `routers/change_requests/__init__.py`'s
module docstring for the package layout.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.action_type import ActionTypeDefinition
from app.models.change_request import ChangeRequest, ChangeRequestVersion
from app.models.custom_field import CustomFieldEntityKind
from app.models.enums import ArtefactType, ChangeRequestKind, ChangeRequestStatus, ProjectRole, ReviewTargetType
from app.models.file import FileAsset
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.schemas.change_request import (
    CHANGEABLE_REQUIREMENT_FIELDS,
    FIELDS_REQUIRING_A_VALUE_WHEN_CHANGED,
    ChangeRequestCreate,
    ChangeRequestOut,
)
from app.schemas.changes import ChangeEntryOut
from app.services import engagement
from app.services.actions import get_requirement_action_in_project
from app.services.audit import log_event
from app.services.changes import get_project_changes
from app.services.custom_fields import validate_custom_field_values
from app.services.rbac import get_effective_project_roles, require_project_view
from app.services.relationships import get_link_between as get_artefact_link_between
from app.services.requirements import get_current_version, is_locked, requires_change_request_for_links

router = APIRouter(tags=["change-requests-core"])

CAN_SUBMIT_ROLES = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)


def _require_can_create_change_request(db: Session, user: User, project: Project) -> None:
    """Like `comments._require_submit_role`, but also allows plain "members"
    when the project has enabled member change-request submission (C-U-13,
    defaults to enabled). Only applies to creating a change request —
    commenting on one still requires stakeholder+ regardless of this toggle.
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
        proposed_link_target_requirement_id=version.proposed_link_target_requirement_id,
        proposed_link_type_id=version.proposed_link_type_id,
        proposed_link_id=version.proposed_link_id,
    )


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
        # locked (`LOCKED_STATUSES = {APPROVED}`, services/requirements.py)
        # — a draft or reviewed requirement isn't locked, so it should be
        # edited directly (routers/requirements.py::update_requirement), not
        # through a change request. Extends that existing precedent rather
        # than inventing a new one.
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
            existing = get_artefact_link_between(
                db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action.id,
                target_type=ArtefactType.REQUIREMENT, target_id=requirement.id,
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
    elif payload.kind == ChangeRequestKind.REMOVE_ACTION:
        # Platform review 2026-09, Phase 8 — mirrors ADD_ACTION's own guard
        # above, and is unconditional (no project/org opt-in): removing an
        # already-linked action from a locked requirement always requires a
        # change request, closing the asymmetry `unlink_action` used to have
        # with the (already-gated) add side.
        if payload.requirement_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "requirement_id is required to remove an action.")
        requirement = db.get(Requirement, payload.requirement_id)
        if requirement is None or requirement.project_id != project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid requirement_id.")
        if not is_locked(get_current_version(db, requirement.id)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This requirement isn't approved yet — remove the action directly instead of via a change request.",
            )
        if payload.proposed_action_link_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposed_action_link_id is required to remove an action.")
        action = get_requirement_action_in_project(db, project_id, payload.proposed_action_link_id)
        existing = get_artefact_link_between(
            db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action.id,
            target_type=ArtefactType.REQUIREMENT, target_id=requirement.id,
        )
        if existing is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This action is not linked to this requirement.")
    elif payload.kind in (ChangeRequestKind.ADD_LINK, ChangeRequestKind.REMOVE_LINK):
        # Platform review 2026-09, Phase 8 — a project/org opt-in sibling of
        # ADD_ACTION/REMOVE_ACTION above: only reachable once
        # `services.requirements.requires_change_request_for_links` is true
        # for this project (links otherwise stay ungated — see
        # `models.relationship.ArtefactLink`'s model docstring), *and* the
        # target requirement is locked.
        if payload.requirement_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "requirement_id is required to change a link.")
        requirement = db.get(Requirement, payload.requirement_id)
        if requirement is None or requirement.project_id != project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid requirement_id.")
        if not is_locked(get_current_version(db, requirement.id)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This requirement isn't approved yet — change its links directly instead of via a change request.",
            )
        if not requires_change_request_for_links(db, project):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This project doesn't require links to be changed via a change request — change it directly instead.",
            )
        if payload.kind == ChangeRequestKind.ADD_LINK:
            if payload.proposed_link_target_requirement_id is None or payload.proposed_link_type_id is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "proposed_link_target_requirement_id and proposed_link_type_id are required to add a link.",
                )
            target = db.get(Requirement, payload.proposed_link_target_requirement_id)
            if target is None or target.project_id != project_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid proposed_link_target_requirement_id.")
            link_type = db.get(RequirementLinkTypeDefinition, payload.proposed_link_type_id)
            if link_type is None or link_type.organization_id != project.organization_id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "proposed_link_type_id must be a link type defined in this project's organisation.",
                )
        else:
            if payload.proposed_link_id is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposed_link_id is required to remove a link.")
            link = db.get(ArtefactLink, payload.proposed_link_id)
            if (
                link is None
                or link.source_type != ArtefactType.REQUIREMENT
                or link.target_type != ArtefactType.REQUIREMENT
                or requirement.id not in (link.source_id, link.target_id)
            ):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid proposed_link_id.")
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
        proposed_link_target_requirement_id=payload.proposed_link_target_requirement_id,
        proposed_link_type_id=payload.proposed_link_type_id,
        proposed_link_id=payload.proposed_link_id,
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

    `X-Total-Unfiltered-Count` (persistent "showing X of Y" result count,
    2026-08 UX audit roadmap) is a second response header reporting the
    count within only the mandatory project scope (change requests have no
    archived-visibility concept), before `cr_status`/`active_only`/
    `target_stage_id` narrow it further — unlike `X-Total-Count`, it does
    not change when the caller applies a status/target-version filter.
    """
    base_query = select(ChangeRequest).where(ChangeRequest.project_id == project_id)
    response.headers["X-Total-Unfiltered-Count"] = str(
        db.scalar(select(func.count()).select_from(base_query.subquery()))
    )

    query = base_query
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
