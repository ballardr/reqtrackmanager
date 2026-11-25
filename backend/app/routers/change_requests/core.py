"""
Module: routers.change_requests.core

Change request creation and read paths (C-G-03, C-G-12): drafting a change request (against an existing
requirement, or proposing a new one, an action add/remove or a link add/remove), listing/fetching one and
its activity timeline. Also holds `_to_out`/`_latest_version` (used by `workflow.py`) and
`OPEN_CR_STATUSES` (used by `votes.py`), each used by one sibling, so not promoted to `_shared.py`
(which holds helpers used by three or more).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.action_type import ActionTypeDefinition
from app.models.change_request import ChangeRequest, ChangeRequestProposedLink, ChangeRequestVersion
from app.models.custom_field import CustomFieldEntityKind
from app.models.enums import ArtefactType, ChangeRequestKind, ChangeRequestStatus, ProjectRole, RequirementLevel, ReviewTargetType
from app.models.file import FileAsset
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement, RequirementVersion
from app.models.user import User
from app.schemas.change_request import (
    CHANGEABLE_REQUIREMENT_FIELDS,
    FIELDS_REQUIRING_A_VALUE_WHEN_CHANGED,
    ChangeRequestCreate,
    ChangeRequestOut,
)
from app.schemas.changes import ChangeEntryOut
from app.services import change_request_list as list_service
from app.services import engagement
from app.services.actions import get_requirement_action_in_project
from app.services.audit import log_event
from app.services.change_request_links import ProposedLinkProblem, check_proposed_link, describe_links
from app.services.change_request_summary import CHANGE_REQUEST_ARTEFACT_TYPE, CHANGE_REQUEST_CODE_PREFIX
from app.services.changes import get_project_changes
from app.services.custom_fields import validate_custom_field_values
from app.services.external_reference_surfaces import reference_texts
from app.services.list_sort import canonical_key, instant, order_records
from app.services.lookups import project_or_404
from app.services.placements import placement_texts
from app.services.principals import principal_columns, principal_out, validate_principal
from app.services.project_scope import ProjectScope
from app.services.rbac import get_effective_project_roles, require_project_view
from app.services.relationships import get_link_between as get_artefact_link_between
from app.services.requirements import get_current_version, is_locked, requires_change_request_for_links
from app.services.sequences import generate_unique_code
from app.services.tags import TagFilter

router = APIRouter(tags=["change-requests-core"])


def _require_can_create_change_request(db: Session, user: User, project: Project) -> None:
    """Raises 403 unless `user` may submit a change request here (`may_submit_change_request`, which also answers the
    Links panel's "Create new"); the member toggle (C-U-13, enabled by default) applies to creating only, since
    commenting on a request still requires stakeholder or above (`CAN_SUBMIT_ROLES`)."""
    if not list_service.may_submit_change_request(db, user, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to submit change requests on this project.")


OPEN_CR_STATUSES = (ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW)


@dataclass
class _ListFacts:
    """What `_to_out` reads per request, loaded once for a whole list: the caller's subscriptions and each request's
    comment count."""

    subscribed: set[UUID]
    comment_counts: dict[UUID, int]


def _list_facts(db: Session, crs: list[ChangeRequest], current_user_id: UUID) -> _ListFacts:
    """Loads the facts a list of `crs` needs in two statements."""
    ids = [cr.id for cr in crs]
    return _ListFacts(
        subscribed=engagement.subscribed_ids(db, current_user_id, "change_request", ids),
        comment_counts=engagement.get_comment_counts(db, ReviewTargetType.CHANGE_REQUEST, ids),
    )


def _to_out(
    db: Session, cr: ChangeRequest, version: ChangeRequestVersion, current_user_id: UUID, *, with_links: bool = True,
    facts: _ListFacts | None = None,
) -> ChangeRequestOut:
    """Builds the API response shape for a change request from its identity
    row plus one version snapshot, including `current_user_id`'s
    subscription state (C-N-01) and derived list-view badge indicators.

    `with_links` resolves the proposed links for display (the far end's title
    only where `current_user_id` may see it); the list view passes false and
    carries just `proposed_link_count`. `facts` is what `_list_facts` loaded for a whole list; omitted, the
    subscription and comment count are read for this one request."""
    project = db.get(Project, cr.project_id) if with_links and version.proposed_links else None
    return ChangeRequestOut(
        id=cr.id, project_id=cr.project_id, unique_code=cr.unique_code, requirement_id=cr.requirement_id, kind=cr.kind,
        status=cr.status,
        creator_id=cr.creator_id, changed_fields=version.changed_fields,
        proposed_name=version.proposed_name, proposed_reasoning=version.proposed_reasoning,
        proposed_clarification=version.proposed_clarification, proposed_description=version.proposed_description,
        proposed_target_stage_id=version.proposed_target_stage_id, proposed_level=version.proposed_level,
        proposed_attachment_file_ids=[UUID(file_id) for file_id in version.proposed_attachment_file_ids],
        reason=version.reason,
        custom_fields=version.custom_fields,
        submitted_at=cr.submitted_at, decided_at=cr.decided_at, decided_by=cr.decided_by,
        decision_note=cr.decision_note, created_at=cr.created_at, updated_at=cr.updated_at,
        is_subscribed=(
            cr.id in facts.subscribed if facts else engagement.is_subscribed(db, current_user_id, "change_request", cr.id)
        ),
        comment_count=(
            facts.comment_counts.get(cr.id, 0) if facts
            else engagement.get_comment_count(db, ReviewTargetType.CHANGE_REQUEST, cr.id)
        ),
        requires_approval=cr.status in OPEN_CR_STATUSES,
        proposed_review_date=version.proposed_review_date,
        proposed_review_lead_days=version.proposed_review_lead_days,
        proposed_reviewer=principal_out(db, version.proposed_reviewer_type, version.proposed_reviewer_id),
        proposed_action_link_id=version.proposed_action_link_id,
        proposed_action_title=version.proposed_action_title,
        proposed_action_description=version.proposed_action_description,
        proposed_action_type_id=version.proposed_action_type_id,
        proposed_action_assignee=principal_out(
            db, version.proposed_action_assignee_type, version.proposed_action_assignee_id
        ),
        proposed_action_due_date=version.proposed_action_due_date,
        proposed_links=describe_links(db, project, current_user_id, list(version.proposed_links)) if project else [],
        proposed_link_count=len(version.proposed_links),
        proposed_link_id=version.proposed_link_id,
    )


def _latest_version(db: Session, cr: ChangeRequest) -> ChangeRequestVersion:
    """Returns the most recently created version row for a change request."""
    version = db.scalars(
        select(ChangeRequestVersion)
        .where(ChangeRequestVersion.change_request_id == cr.id)
        .order_by(ChangeRequestVersion.version_number.desc())
    ).first()
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request version not found.")
    return version


MAX_PROPOSED_LINKS = 50


def _validate_proposed_links(db: Session, project: Project, payload: ChangeRequestCreate, *, creator_id: UUID) -> None:
    """400 unless every proposed link could be created by `creator_id` now.

    Links are allowed on new, modify and add-link requests only. Each is checked with
    the rules of creating a link directly (`services.change_request_links`), against the
    existing requirement or, for a new one, the project; a repeated link in one request
    is refused. The messages never reveal a record the creator cannot see.
    """
    links = payload.proposed_links
    if not links:
        return
    if payload.kind not in (
        ChangeRequestKind.NEW_REQUIREMENT, ChangeRequestKind.MODIFY_REQUIREMENT, ChangeRequestKind.ADD_LINK
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Links can only be proposed on a new, modify or add-link change request."
        )
    if len(links) > MAX_PROPOSED_LINKS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"At most {MAX_PROPOSED_LINKS} links can be proposed in one request.")
    seen: set[tuple] = set()
    for position, proposed in enumerate(links, start=1):
        key = (proposed.link_type_id, proposed.direction, proposed.other_type, proposed.other_id)
        if key in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Proposed link {position} repeats an earlier one.")
        seen.add(key)
        try:
            check_proposed_link(
                db, project=project, requirement_id=payload.requirement_id, creator_id=creator_id,
                link_type_id=proposed.link_type_id, outgoing=proposed.direction.value == "outgoing",
                other_type=proposed.other_type, other_id=proposed.other_id,
                other_project_id=proposed.other_project_id,
            )
        except ProposedLinkProblem as problem:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Proposed link {position}: {problem.message}") from problem


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
        # Requirement-status guard: a change request gates edits once direct editing is locked
        # (`LOCKED_STATUSES = {APPROVED}`, services/requirements.py); a draft or reviewed requirement is
        # edited directly (routers/requirements.py::update_requirement).
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
        # Mirrors MODIFY_REQUIREMENT's guard above: an action is added through a change request only once
        # the requirement is locked; before that the direct path applies
        # (routers/requirements.py::create_and_link_action/link_action) and rejects it once locked.
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
        if payload.proposed_action_link_id is not None:
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
        # Mirrors ADD_ACTION's guard above and is unconditional (no project/org opt-in): removing a linked
        # action from a locked requirement always requires a change request, as `unlink_action` enforces.
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
        # Opt-in sibling of ADD_ACTION/REMOVE_ACTION: reachable only when
        # `services.requirements.requires_change_request_for_links` is true for this project (links are
        # otherwise ungated, see `models.relationship.ArtefactLink`) and the target requirement is locked.
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
            if not payload.proposed_links:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposed_links is required to add a link.")
        else:
            if payload.proposed_link_id is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposed_link_id is required to remove a link.")
            link = db.get(ArtefactLink, payload.proposed_link_id)
            if (
                link is None
                or link.source_type != ArtefactType.REQUIREMENT
                or link.target_type != ArtefactType.REQUIREMENT
                or requirement.id not in (link.source_id, link.target_id)
                or link.source_project_id is not None  # change requests cover same-project links only
            ):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid proposed_link_id.")
    else:
        # NEW_REQUIREMENT ignores changed_fields entirely (there's no
        # existing version to diff against) but still needs the fields a
        # brand-new requirement can never be without.
        if payload.proposed_name is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposed_name is required for a new requirement.")
        # proposed_target_stage_id may be omitted; approval defaults it to the project's earliest stage,
        # as a direct create does (routers/requirements.py::create_requirement_endpoint).
        # proposed_component_id/proposed_category_id are validated against project_id here, as in the
        # direct-create path: they are write-once (set only at creation), and approval only checks
        # `is None`, so an unvalidated cross-project reference would be baked into a real Requirement row.
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

    for person_field in ("proposed_action_assignee", "proposed_reviewer"):
        validate_principal(
            db, getattr(payload, person_field), organization_id=project.organization_id, project_id=project_id,
            field=person_field,
        )
    _validate_proposed_links(db, project, payload, creator_id=payload.creator_id or current_user.id)

    if payload.proposed_attachment_file_ids:
        # Same cross-org isolation check as report images (services/report_document.py::resolve_report_images):
        # a proposed attachment must be an org shared resource of this project's own organisation.
        for file_id in payload.proposed_attachment_file_ids:
            asset = db.get(FileAsset, file_id)
            if asset is None or asset.organization_id != project.organization_id or not asset.is_org_resource:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid proposed attachment file id: {file_id}.")

    # Validated against the requirement entity kind, not change_request: these are proposed custom-attribute
    # values for the requirement being created or modified, copied onto its version on approval. The
    # `CustomFieldEntityKind.CHANGE_REQUEST` kind (attributes of the change request itself) has no consuming
    # workflow step, so none are collected here (see docs/decisions.md).
    custom_fields = validate_custom_field_values(db, project_id, CustomFieldEntityKind.REQUIREMENT, payload.custom_fields)

    creator_id = current_user.id
    if payload.creator_id is not None:
        # PM re-attributing authorship at creation time (C-A-12).
        if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can assign the creator.")
        creator_id = payload.creator_id

    cr = ChangeRequest(
        project_id=project_id, unique_code=generate_unique_code(db, project, CHANGE_REQUEST_ARTEFACT_TYPE, CHANGE_REQUEST_CODE_PREFIX),
        requirement_id=payload.requirement_id, kind=payload.kind,
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
        **principal_columns("proposed_reviewer", payload.proposed_reviewer),
        proposed_action_link_id=payload.proposed_action_link_id,
        proposed_action_title=payload.proposed_action_title,
        proposed_action_description=payload.proposed_action_description,
        proposed_action_type_id=payload.proposed_action_type_id,
        **principal_columns("proposed_action_assignee", payload.proposed_action_assignee),
        proposed_action_due_date=payload.proposed_action_due_date,
        proposed_link_id=payload.proposed_link_id,
    )
    db.add(version)
    for position, proposed in enumerate(payload.proposed_links):
        version.proposed_links.append(ChangeRequestProposedLink(
            link_type_id=proposed.link_type_id, direction=proposed.direction.value, other_type=proposed.other_type,
            other_id=proposed.other_id,
            other_project_id=proposed.other_project_id if proposed.other_project_id != project_id else None,
            sort_order=position,
        ))
    log_event(db, entity_type="change_request", entity_id=cr.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"proposed_links": len(payload.proposed_links)} if payload.proposed_links else None)
    db.commit()
    db.refresh(cr)
    return _to_out(db, cr, version, current_user.id)


def _sort_value(item: ChangeRequestOut, sort: str) -> Any:
    """What the list is ordered by for `sort` (a canonical key or the list's own name): a change request with no
    proposed name (a modification that did not touch it) has no title and sorts last."""
    key = canonical_key(sort)
    if key == "title" or sort == "proposed_name":
        return item.proposed_name
    if key == "code":
        return item.unique_code
    if key == "created":
        return instant(item.created_at)
    if key == "modified":
        return instant(item.updated_at)
    return item.status.value


#: Sorts whose value is read for the whole list at once: the target stage and level (the change request's own, else the
#: requirement's current), where the request sits (`places`) and its external references.
LOOKUP_SORTS = ("target", "level", "places", "references")
_LEVEL_RANK = {RequirementLevel.REQUIREMENT: 0, RequirementLevel.RECOMMENDED: 1, RequirementLevel.OPTIONAL: 2}


def _lookup_sort_values(db: Session, items: list[ChangeRequestOut], sort: str) -> Callable[[ChangeRequestOut], Any]:
    """The value function for a `LOOKUP_SORTS` key, reading what it needs for every item in a fixed number of statements.

    Args:
        db: Active session (read only).
        items: The change requests being ordered.
        sort: One of `LOOKUP_SORTS`.

    Returns:
        `(item) -> number, text or None`: the target stage's position, the level's rank (mandatory, recommended,
        optional), the places text or the references text; `None` when the request has none.
    """
    ids = [item.id for item in items]
    if sort == "places":
        places = placement_texts(db, CHANGE_REQUEST_ARTEFACT_TYPE, ids)
        return lambda item: places.get(item.id)
    if sort == "references":
        references = reference_texts(db, CHANGE_REQUEST_ARTEFACT_TYPE, ids)
        return lambda item: references.get(item.id)
    requirement_ids = {item.requirement_id for item in items if item.requirement_id is not None}
    current = {
        row[0]: (row[1], row[2]) for row in db.execute(
            select(RequirementVersion.requirement_id, RequirementVersion.target_stage_id, RequirementVersion.level).where(
                RequirementVersion.requirement_id.in_(requirement_ids), RequirementVersion.valid_to.is_(None),
            )
        ).all()
    } if requirement_ids else {}
    stage_ids = {item.proposed_target_stage_id for item in items if item.proposed_target_stage_id} | {stage for stage, _ in current.values()}
    positions = {
        row[0]: row[1] for row in db.execute(select(ProjectStage.id, ProjectStage.sort_order).where(ProjectStage.id.in_(stage_ids))).all()
    } if stage_ids else {}

    def value(item: ChangeRequestOut) -> Any:
        stage, level = current.get(item.requirement_id, (None, None)) if item.requirement_id is not None else (None, None)
        if sort == "target":
            return positions.get(item.proposed_target_stage_id or stage)
        chosen = item.proposed_level or level
        return _LEVEL_RANK[chosen] if chosen is not None else None

    return value


@router.get("", response_model=list[ChangeRequestOut])
def list_change_requests(
    project_id: UUID,
    response: Response,
    cr_status: ChangeRequestStatus | None = None,
    active_only: bool = False,
    target_stage_id: UUID | None = None,
    search: str | None = None,
    sort: str | None = Query(
        None, pattern="^(proposed_name|title|unique_code|code|status|created_at|created|updated_at|modified|target|level|places|references)$",
    ),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    tag_filter: TagFilter = Depends(),
    project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists change requests, with optional status/target-version filters. `tag`/`tag_mode` narrow to
    change requests carrying those tags. `limit`/`offset` (U-P-06) paginate, as `list_requirements`.

    `active_only` filters to the non-terminal statuses (`draft`/`submitted`/`in_review`) server-side, so a
    paginated page is not filtered client-side. Ignored when `cr_status` is given (a single status is more
    specific).

    `sort` sorts by `proposed_name` (`title`), `unique_code` (`code`; by prefix then number, so `CR-2`
    precedes `CR-10`), `status`, `created_at` (`created`), `updated_at` (`modified`), `target` (the target stage's
    position), `level` (mandatory, recommended, optional), `places` or `references`; `order` picks `asc`
    (default) or `desc`. Without `sort`, rows are newest first. Rows with no `proposed_name` (the list
    view falls back to the requirement's name, see `crTitle()` in `ChangeRequestsPage.tsx`) sort as empty,
    since the raw column cannot resolve that fallback without an extra join.

    `search` is a case-insensitive substring match against what the list shows: the request's code, the
    proposed name, the reason, and the target requirement's current name and code (looked up in one
    batched query).

    `X-Total-Unfiltered-Count` reports the count within only the mandatory project scope, before
    `cr_status`/`active_only`/`target_stage_id` narrow it; unlike `X-Total-Count` it does not change
    with those filters.

    `project_scope` adds the change requests of the related projects the caller can open, each row
    labelled with `from_project_*` (see `list_requirements`).
    """
    unfiltered = 0

    def rows_for(pid: UUID) -> list[ChangeRequestOut]:
        nonlocal unfiltered
        unfiltered += list_service.count_change_requests(db, pid)
        crs = list_service.query_change_requests(db, pid, cr_status=cr_status, active_only=active_only)
        crs = tag_filter.keep(db, pid, "change_request", crs)
        pairs = list_service.narrow_change_requests(db, crs, target_stage_id=target_stage_id, search=search)
        facts = _list_facts(db, [cr for cr, _version in pairs], current_user.id)
        return [_to_out(db, cr, version, current_user.id, with_links=False, facts=facts) for cr, version in pairs]

    out = project_scope.collect(db, project_or_404(db, project_id), current_user.id, "change_request", rows_for)
    response.headers["X-Total-Unfiltered-Count"] = str(unfiltered)

    if sort:
        value_of = _lookup_sort_values(db, out, sort) if sort in LOOKUP_SORTS else (lambda item: _sort_value(item, sort))
        out = order_records(out, value_of, descending=order == "desc")

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
    return get_project_changes(
        db, project_id, since=None, until=None, include_comments=False,
        entity_type="change_request", entity_id=cr_id,
    )
