"""
Module: routers.requirements

Requirement CRUD, version history / change log (C-A-09), traceability links
(C-G-09), keyword search (C-M-01), discussion threads (C-R-01), and scoping-
stage-only ordering (C-E-03).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.metrics import (
    requirements_archived_total,
    requirements_created_total,
    requirements_updated_total,
)
from app.models.change_request import ChangeRequest, ReviewComment
from app.models.custom_field import CustomFieldEntityKind
from app.models.enums import (
    ChangeRequestStatus,
    ProjectRole,
    RequirementLevel,
    RequirementReviewOutcome,
    RequirementStatus,
    ReviewTargetType,
    StageStatus,
)
from app.models.file import FileAsset, RequirementFile
from app.models.notification import NotificationType
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.requirement import Requirement, RequirementLink, RequirementReview, RequirementVersion
from app.models.user import User
from app.schemas.changes import ChangeEntryOut
from app.schemas.file import FileAssetOut, LinkResourceRequest
from app.schemas.project import MoveDirection
from app.schemas.requirement import (
    CommentCreate,
    CommentOut,
    RequirementCreate,
    RequirementDueForReviewOut,
    RequirementImportError,
    RequirementImportResult,
    RequirementLinkCreate,
    RequirementLinkOut,
    RequirementOut,
    RequirementReviewCreate,
    RequirementReviewOut,
    RequirementUpdate,
    RequirementVersionOut,
)
from app.services import engagement, notifications, pubsub
from app.services.audit import log_event
from app.services.changes import get_project_changes
from app.services.custom_fields import validate_custom_field_values
from app.services.files import delete_file, upload_file
from app.services.rbac import get_effective_project_roles, require_project_manage, require_project_view
from app.services.requirements import (
    apply_new_version,
    archive_requirement,
    create_requirement,
    get_current_version,
    get_keywords,
    is_locked,
    set_keywords,
)
from app.services.reviews import get_due_reviews_for_project

router = APIRouter(prefix="/api/v1/projects/{project_id}/requirements", tags=["requirements"])

CAN_EDIT_ROLES = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)


def _require_edit_role(db: Session, user: User, project_id: UUID) -> None:
    """Raises 403 unless `user` holds a requirement-editing role on the project.

    No server-admin bypass (I-M-05): requirement content is "data within
    organisations".
    """
    if not get_effective_project_roles(db, user.id, project_id) & set(CAN_EDIT_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders, administrators, or managers may do this.")


REQUIRES_APPROVAL_STATUSES = {RequirementStatus.DRAFT, RequirementStatus.REVIEWED}
OPEN_CR_STATUSES = (ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW)


def _has_open_change_request(db: Session, requirement_id: UUID) -> bool:
    return (
        db.scalar(
            select(ChangeRequest.id).where(
                ChangeRequest.requirement_id == requirement_id, ChangeRequest.status.in_(OPEN_CR_STATUSES)
            )
        )
        is not None
    )


def _to_out(db: Session, requirement: Requirement, version: RequirementVersion, current_user_id: UUID) -> RequirementOut:
    """Builds the API response shape for a requirement from its identity row
    plus one version snapshot, including `current_user_id`'s subscription
    state (C-N-01) and derived list-view badge indicators."""
    return RequirementOut(
        id=requirement.id, project_id=requirement.project_id, unique_code=requirement.unique_code,
        name=version.name, reasoning=version.reasoning, clarification=version.clarification,
        status=version.status, owner_id=version.owner_id, component_id=requirement.component_id,
        category_id=requirement.category_id, target_stage_id=version.target_stage_id, level=version.level,
        sort_order=version.sort_order, creator_id=requirement.creator_id,
        is_archived=requirement.is_archived, is_locked=is_locked(version),
        keywords=get_keywords(db, requirement.id), custom_fields=version.custom_fields,
        created_at=requirement.created_at, updated_at=version.created_at,
        is_subscribed=engagement.is_subscribed(db, current_user_id, "requirement", requirement.id),
        comment_count=engagement.get_comment_count(db, ReviewTargetType.REQUIREMENT, requirement.id),
        has_open_change_request=_has_open_change_request(db, requirement.id),
        requires_approval=version.status in REQUIRES_APPROVAL_STATUSES,
        review_date=version.review_date, review_lead_days=version.review_lead_days, reviewer_id=version.reviewer_id,
    )


@router.post("", response_model=RequirementOut, status_code=status.HTTP_201_CREATED)
def create_requirement_endpoint(
    project_id: UUID, payload: RequirementCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Creates a requirement (C-G-02). Requires stakeholder/administrator/manager."""
    _require_edit_role(db, current_user, project_id)
    project = db.get(Project, project_id)
    component = db.get(ProjectComponent, payload.component_id)
    category = db.get(ProjectCategory, payload.category_id)
    if project is None or component is None or component.project_id != project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid component.")
    if category is None or category.project_id != project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid category.")

    custom_fields = validate_custom_field_values(db, project_id, CustomFieldEntityKind.REQUIREMENT, payload.custom_fields)

    creator_override_id = None
    if payload.creator_id is not None:
        # PM re-attributing authorship at creation time (C-A-11).
        if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can assign the creator.")
        creator_override_id = payload.creator_id

    count = len(db.scalars(select(Requirement.id).where(Requirement.project_id == project_id)).all())
    requirement = create_requirement(
        db, project, component, category, current_user,
        name=payload.name, reasoning=payload.reasoning, clarification=payload.clarification,
        owner_id=payload.owner_id, keywords=payload.keywords, sort_order=count,
        target_stage_id=payload.target_stage_id, level=payload.level,
        custom_fields=custom_fields, creator_override_id=creator_override_id,
        review_date=payload.review_date, review_lead_days=payload.review_lead_days, reviewer_id=payload.reviewer_id,
    )
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="created",
              actor_id=current_user.id, project_id=project_id)
    requirements_created_total.inc()
    db.commit()
    db.refresh(requirement)
    version = get_current_version(db, requirement.id)
    pubsub.notify(project_id, {"type": "requirement", "action": "created", "id": str(requirement.id)})
    return _to_out(db, requirement, version, current_user.id)


@router.get("", response_model=list[RequirementOut])
def list_requirements(
    project_id: UUID,
    response: Response,
    component_id: UUID | None = None,
    category_id: UUID | None = None,
    keyword: str | None = None,
    search: str | None = None,
    status_filter: RequirementStatus | None = Query(None, alias="status"),
    target_stage_id: UUID | None = None,
    has_comments: bool | None = None,
    only_watched: bool | None = None,
    include_archived: bool = False,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists requirements, sorted by component/category (C-G-04) with search (U-E-01)
    and filter-panel query params (status/target version/comments/watched).

    `limit`/`offset` (U-P-06) are optional: omitting both returns every
    matching requirement, unchanged from before pagination existed (C-G-05:
    no artificial limit is ever imposed unless the caller asks for a page).
    When `limit` is given, the total match count (before slicing) is
    returned in the `X-Total-Count` response header so a client can tell
    whether more pages remain.
    """
    query = select(Requirement).where(Requirement.project_id == project_id)
    if not include_archived:
        query = query.where(Requirement.is_archived.is_(False))
    if component_id:
        query = query.where(Requirement.component_id == component_id)
    if category_id:
        query = query.where(Requirement.category_id == category_id)
    requirements = db.scalars(query).all()

    out = []
    for req in requirements:
        version = get_current_version(db, req.id)
        kws = get_keywords(db, req.id)
        if keyword and keyword.lower() not in kws:
            continue
        if search:
            needle = search.lower()
            if needle not in version.name.lower() and needle not in req.unique_code.lower():
                continue
        if status_filter and version.status != status_filter:
            continue
        if target_stage_id and version.target_stage_id != target_stage_id:
            continue
        item = _to_out(db, req, version, current_user.id)
        if has_comments and item.comment_count == 0:
            continue
        if only_watched and not item.is_subscribed:
            continue
        out.append(item)

    comp_order = {c.id: c.sort_order for c in db.scalars(
        select(ProjectComponent).where(ProjectComponent.project_id == project_id)).all()}
    cat_order = {c.id: c.sort_order for c in db.scalars(
        select(ProjectCategory).where(ProjectCategory.project_id == project_id)).all()}
    out.sort(key=lambda r: (comp_order.get(r.component_id, 0), cat_order.get(r.category_id, 0), r.sort_order))

    response.headers["X-Total-Count"] = str(len(out))
    if limit is not None:
        out = out[offset:offset + limit]
    return out


@router.post("/import", response_model=RequirementImportResult, status_code=status.HTTP_201_CREATED)
async def import_requirements(
    project_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Bulk-creates requirements from an uploaded CSV.

    Expected columns: `name` (required), `reasoning`, `component_prefix`
    (required, must match an existing `ProjectComponent.prefix`),
    `category_prefix` (required, must match an existing
    `ProjectCategory.prefix`), `level` ("requirement"/"recommended",
    optional), `target_version` (optional, must match an existing
    `ProjectStage.name`).

    Unknown prefixes/stage names are reported as row errors rather than
    silently creating new components/categories/stages. Registered before
    `GET /{requirement_id}` so the static "/import" path isn't swallowed by
    that dynamic route.

    Every valid row is created in a single transaction — nothing commits
    until the whole file has been processed, so a mid-file server error
    can't leave a half-imported batch; per-row validation errors, by
    contrast, are expected and simply skip that row while the rest import
    normally.
    """
    _require_edit_role(db, current_user, project_id)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")

    components = {c.prefix: c for c in db.scalars(select(ProjectComponent).where(ProjectComponent.project_id == project_id)).all()}
    categories = {c.prefix: c for c in db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == project_id)).all()}
    stages = {s.name: s for s in db.scalars(select(ProjectStage).where(ProjectStage.project_id == project_id)).all()}

    raw = await file.read()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))

    count = len(db.scalars(select(Requirement.id).where(Requirement.project_id == project_id)).all())
    errors: list[RequirementImportError] = []
    created = 0

    for row_num, row in enumerate(reader, start=2):  # header is row 1
        name = (row.get("name") or "").strip()
        component_prefix = (row.get("component_prefix") or "").strip()
        category_prefix = (row.get("category_prefix") or "").strip()
        level_raw = (row.get("level") or "requirement").strip().lower()
        target_version = (row.get("target_version") or "").strip()

        if not name:
            errors.append(RequirementImportError(row=row_num, message="Missing required 'name'."))
            continue
        component = components.get(component_prefix)
        if component is None:
            errors.append(RequirementImportError(row=row_num, message=f"Unknown component_prefix '{component_prefix}'."))
            continue
        category = categories.get(category_prefix)
        if category is None:
            errors.append(RequirementImportError(row=row_num, message=f"Unknown category_prefix '{category_prefix}'."))
            continue
        try:
            level = RequirementLevel(level_raw)
        except ValueError:
            errors.append(RequirementImportError(row=row_num, message=f"Invalid level '{level_raw}'."))
            continue
        target_stage_id = None
        if target_version:
            stage = stages.get(target_version)
            if stage is None:
                errors.append(RequirementImportError(row=row_num, message=f"Unknown target_version '{target_version}'."))
                continue
            target_stage_id = stage.id

        create_requirement(
            db, project, component, category, current_user,
            name=name, reasoning=(row.get("reasoning") or "").strip(), clarification="",
            owner_id=None, keywords=[], sort_order=count, target_stage_id=target_stage_id, level=level,
        )
        count += 1
        created += 1

    if created:
        log_event(db, entity_type="project", entity_id=project_id, action="requirements_imported",
                   actor_id=current_user.id, project_id=project_id, detail={"created": created, "errors": len(errors)})
        db.commit()
    return RequirementImportResult(created=created, errors=errors)


@router.get("/reviews/due", response_model=list[RequirementDueForReviewOut])
def list_due_reviews(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Requirements due/overdue for review in this project, project-basis (C-R-09).

    Registered before `GET /{requirement_id}` so this static path isn't
    swallowed by that dynamic route (same reasoning as `/import` above).
    """
    return [
        RequirementDueForReviewOut(
            requirement_id=req.id, project_id=req.project_id, unique_code=req.unique_code,
            name=version.name, review_date=version.review_date, reviewer_id=version.reviewer_id,
        )
        for version, req in get_due_reviews_for_project(db, project_id)
    ]


@router.get("/{requirement_id}", response_model=RequirementOut)
def get_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    version = get_current_version(db, requirement.id)
    return _to_out(db, requirement, version, current_user.id)


@router.put("/{requirement_id}", response_model=RequirementOut)
def update_requirement(
    project_id: UUID, requirement_id: UUID, payload: RequirementUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Direct requirement edit. Rejected once the requirement is locked (C-G-12) —
    at that point, changes must go through a change request instead."""
    _require_edit_role(db, current_user, project_id)
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    current_version = get_current_version(db, requirement.id)
    if is_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved; changes must be made via a change request.",
        )
    custom_fields = validate_custom_field_values(db, project_id, CustomFieldEntityKind.REQUIREMENT, payload.custom_fields)
    new_version = apply_new_version(
        db, requirement, current_version, current_user,
        name=payload.name, reasoning=payload.reasoning, clarification=payload.clarification,
        status_value=payload.status, owner_id=payload.owner_id,
        target_stage_id=payload.target_stage_id, target_stage_explicitly_set=True, level=payload.level,
        change_note=payload.change_note or "Direct edit during scoping.",
        custom_fields=custom_fields,
        review_date=payload.review_date, review_date_explicitly_set=True,
        review_lead_days=payload.review_lead_days, review_lead_days_explicitly_set=True,
        reviewer_id=payload.reviewer_id, reviewer_id_explicitly_set=True,
    )
    if payload.component_id != requirement.component_id or payload.category_id != requirement.category_id:
        component = db.get(ProjectComponent, payload.component_id)
        category = db.get(ProjectCategory, payload.category_id)
        if component is None or component.project_id != project_id or category is None or category.project_id != project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid component or category.")
        requirement.component_id = payload.component_id
        requirement.category_id = payload.category_id
    set_keywords(db, requirement, payload.keywords)
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="updated",
              actor_id=current_user.id, project_id=project_id, detail={"change_note": payload.change_note})
    requirements_updated_total.inc()
    db.commit()
    db.refresh(requirement)
    pubsub.notify(project_id, {"type": "requirement", "action": "updated", "id": str(requirement.id)})
    return _to_out(db, requirement, new_version, current_user.id)


@router.delete("/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Archives (soft-deletes) a requirement, preserving its history (C-A-06)."""
    if not get_effective_project_roles(db, current_user.id, project_id) & {
        ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR,
    }:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators or managers may archive requirements.")
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    archive_requirement(db, requirement, current_user)
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    requirements_archived_total.inc()
    db.commit()
    pubsub.notify(project_id, {"type": "requirement", "action": "archived", "id": str(requirement.id)})


@router.post("/{requirement_id}/reviews", response_model=RequirementReviewOut, status_code=status.HTTP_201_CREATED)
def record_review_outcome(
    project_id: UUID, requirement_id: UUID, payload: RequirementReviewCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Records the outcome of a requirement's scheduled review (C-R-07).

    Gate: the requirement's assigned reviewer (C-R-10), or a project manager
    as a fallback. Doesn't touch `review_date` itself (see
    `services/reviews.py`'s due-list definition) — the requirement drops off
    the due list because a review now exists, not because the date changed.
    """
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    version = get_current_version(db, requirement.id)
    is_reviewer = version.reviewer_id == current_user.id
    is_manager = ProjectRole.PROJECT_MANAGER in get_effective_project_roles(db, current_user.id, project_id)
    if not (is_reviewer or is_manager):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the assigned reviewer or a project manager may record this.")
    if payload.outcome == RequirementReviewOutcome.FAILED and not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required when the outcome is 'failed'.")

    review = RequirementReview(
        requirement_id=requirement.id, requirement_version_id=version.id,
        reviewed_by=current_user.id, reviewed_at=datetime.now(UTC),
        outcome=payload.outcome, comment=payload.comment,
    )
    db.add(review)
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="review_recorded",
              actor_id=current_user.id, project_id=project_id, detail={"outcome": payload.outcome.value})
    db.commit()
    db.refresh(review)
    return RequirementReviewOut(
        id=review.id, requirement_id=review.requirement_id, reviewed_by=review.reviewed_by,
        reviewed_at=review.reviewed_at, outcome=review.outcome, comment=review.comment,
    )


@router.post("/{requirement_id}/complete", response_model=RequirementOut)
def complete_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Marks an approved requirement completed (C-P-03), gated the same as
    archiving — a status transition a project manager can make directly,
    not content that needs to go through a change request. Who/when is
    captured by the resulting version's created_by/created_at, same as
    every other requirement edit."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    current_version = get_current_version(db, requirement.id)
    if current_version.status != RequirementStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an approved requirement can be marked completed.")
    new_version = apply_new_version(
        db, requirement, current_version, current_user,
        status_value=RequirementStatus.COMPLETED, change_note="Marked completed.",
    )
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="completed",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(requirement)
    return _to_out(db, requirement, new_version, current_user.id)


@router.post("/{requirement_id}/uncomplete", response_model=RequirementOut)
def uncomplete_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Reverts a completed requirement back to approved, to correct a mistake."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    current_version = get_current_version(db, requirement.id)
    if current_version.status != RequirementStatus.COMPLETED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This requirement is not marked completed.")
    new_version = apply_new_version(
        db, requirement, current_version, current_user,
        status_value=RequirementStatus.APPROVED, change_note="Completion reverted.",
    )
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="uncompleted",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(requirement)
    return _to_out(db, requirement, new_version, current_user.id)


@router.get("/{requirement_id}/history", response_model=list[RequirementVersionOut])
def requirement_history(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Change log for a requirement, excluding discussion comments (C-A-09)."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    versions = db.scalars(
        select(RequirementVersion)
        .where(RequirementVersion.requirement_id == requirement_id)
        .order_by(RequirementVersion.version_number)
    ).all()
    return [
        RequirementVersionOut(
            version_number=v.version_number, name=v.name, reasoning=v.reasoning,
            clarification=v.clarification, status=v.status, owner_id=v.owner_id,
            target_stage_id=v.target_stage_id, level=v.level,
            change_note=v.change_note, change_request_id=v.change_request_id,
            custom_fields=v.custom_fields,
            created_by=v.created_by, created_at=v.created_at, valid_to=v.valid_to,
        )
        for v in versions
    ]


@router.get("/{requirement_id}/activity", response_model=list[ChangeEntryOut])
def requirement_activity(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Per-entity activity timeline for the requirement detail view's side
    panel (mock's "Subscribed" activity log): audit events plus version
    history, filtered to this requirement. Excludes discussion comments,
    which are shown separately (C-A-09 clarification)."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    entries = get_project_changes(db, project_id, since=None, until=None, include_comments=False)
    return [e for e in entries if e.entity_type == "requirement" and e.entity_id == str(requirement_id)]


@router.post("/{requirement_id}/move", response_model=RequirementOut)
def move_requirement(
    project_id: UUID, requirement_id: UUID, payload: MoveDirection,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Reorders a requirement within its list. Scoping-stage only (C-E-03)."""
    _require_edit_role(db, current_user, project_id)
    current_stage = db.scalar(
        select(ProjectStage).where(ProjectStage.project_id == project_id, ProjectStage.is_current.is_(True))
    )
    if current_stage is None or current_stage.status != StageStatus.SCOPING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Requirements can only be reordered during scoping.")

    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")

    siblings = db.scalars(
        select(Requirement).where(
            Requirement.project_id == project_id, Requirement.component_id == requirement.component_id,
            Requirement.category_id == requirement.category_id, Requirement.is_archived.is_(False),
        )
    ).all()
    versions = {r.id: get_current_version(db, r.id) for r in siblings}
    siblings.sort(key=lambda r: versions[r.id].sort_order)
    idx = next(i for i, r in enumerate(siblings) if r.id == requirement.id)
    swap_idx = idx - 1 if payload.direction == "up" else idx + 1
    if 0 <= swap_idx < len(siblings):
        a, b = siblings[idx], siblings[swap_idx]
        versions[a.id].sort_order, versions[b.id].sort_order = versions[b.id].sort_order, versions[a.id].sort_order
        db.commit()
    version = get_current_version(db, requirement.id)
    return _to_out(db, requirement, version, current_user.id)


def _get_requirement_in_project(db: Session, project_id: UUID, requirement_id: UUID) -> Requirement:
    """Loads a requirement and 404s unless it belongs to `project_id`.

    Without this check, an endpoint that only verifies the caller's role on
    `project_id` (via `require_project_view`/`_require_edit_role`) would let
    any project member read or write links/comments on a requirement
    belonging to a different, inaccessible project by supplying its id —
    an IDOR. Every handler taking both a `project_id` and a `requirement_id`
    must load through this helper rather than trusting `requirement_id` alone.
    """
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    return requirement


@router.post("/{requirement_id}/links", response_model=RequirementLinkOut, status_code=status.HTTP_201_CREATED)
def create_link(
    project_id: UUID, requirement_id: UUID, payload: RequirementLinkCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Creates a traceability link between two requirements (C-G-09)."""
    _require_edit_role(db, current_user, project_id)
    _get_requirement_in_project(db, project_id, requirement_id)
    target = _get_requirement_in_project(db, project_id, payload.target_requirement_id)
    link = RequirementLink(
        source_requirement_id=requirement_id, target_requirement_id=target.id,
        link_type=payload.link_type, created_by=current_user.id,
    )
    db.add(link)
    db.flush()
    log_event(db, entity_type="requirement_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"source_requirement_id": str(requirement_id), "target_requirement_id": str(target.id),
                      "link_type": payload.link_type.value})
    db.commit()
    db.refresh(link)
    return link


@router.get("/{requirement_id}/links", response_model=list[RequirementLinkOut])
def list_links(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    return db.scalars(
        select(RequirementLink).where(
            (RequirementLink.source_requirement_id == requirement_id)
            | (RequirementLink.target_requirement_id == requirement_id)
        )
    ).all()


@router.post("/{requirement_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(
    project_id: UUID, requirement_id: UUID, payload: CommentCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Adds a discussion thread comment (C-R-01), notifying subscribers."""
    _get_requirement_in_project(db, project_id, requirement_id)
    comment = ReviewComment(
        target_type=ReviewTargetType.REQUIREMENT, target_id=requirement_id,
        author_id=current_user.id, body=payload.body,
    )
    db.add(comment)
    db.flush()

    for subscriber_id in engagement.get_subscriber_ids(
        db, "requirement", requirement_id, exclude_user_id=current_user.id
    ):
        subscriber = db.get(User, subscriber_id)
        if subscriber is not None:
            notifications.notify(
                db, subscriber, notification_type=NotificationType.COMMENT_ADDED,
                title="New comment on a requirement you follow",
                body=payload.body[:200],
                project_id=project_id, entity_type="requirement", entity_id=str(requirement_id),
            )
    db.commit()
    db.refresh(comment)
    return engagement.comment_to_out(db, comment, current_user.id)


@router.get("/{requirement_id}/comments", response_model=list[CommentOut])
def list_comments(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    comments = db.scalars(
        select(ReviewComment)
        .where(ReviewComment.target_type == ReviewTargetType.REQUIREMENT, ReviewComment.target_id == requirement_id)
        .order_by(ReviewComment.created_at)
    ).all()
    return [engagement.comment_to_out(db, c, current_user.id) for c in comments]


@router.put("/{requirement_id}/comments/{comment_id}/reaction", status_code=status.HTTP_204_NO_CONTENT)
def react_to_comment(
    project_id: UUID, requirement_id: UUID, comment_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Adds the caller's reaction to a comment (a single "like", not a
    multi-emoji reaction picker — see CommentReaction model docstring)."""
    _get_requirement_in_project(db, project_id, requirement_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_id != requirement_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    engagement.add_reaction(db, comment_id, current_user.id)


@router.delete("/{requirement_id}/comments/{comment_id}/reaction", status_code=status.HTTP_204_NO_CONTENT)
def unreact_to_comment(
    project_id: UUID, requirement_id: UUID, comment_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_id != requirement_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    engagement.remove_reaction(db, comment_id, current_user.id)


@router.put("/{requirement_id}/subscription", status_code=status.HTTP_204_NO_CONTENT)
def subscribe_to_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Opts the caller into notifications for this specific requirement
    (independent of their broad per-type notification preferences)."""
    _get_requirement_in_project(db, project_id, requirement_id)
    engagement.subscribe(db, current_user.id, "requirement", requirement_id)


@router.delete("/{requirement_id}/subscription", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe_from_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    engagement.unsubscribe(db, current_user.id, "requirement", requirement_id)


# --- File attachments (C-M-02) and shared-resource links (C-M-04) ----------


@router.post("/{requirement_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_requirement_attachment(
    project_id: UUID, requirement_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Uploads and attaches a new file to a requirement (C-M-02)."""
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    project = db.get(Project, project_id)
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(RequirementFile(requirement_id=requirement.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at))
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/{requirement_id}/files/link", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
def link_org_resource(
    project_id: UUID, requirement_id: UUID, payload: LinkResourceRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Links an organisation shared resource file to a requirement (C-M-04)."""
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    project = db.get(Project, project_id)
    asset = db.get(FileAsset, payload.file_id)
    if asset is None or not asset.is_org_resource or asset.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file_id must be a shared resource in this project's organisation.")
    existing = db.scalar(
        select(RequirementFile).where(RequirementFile.requirement_id == requirement.id, RequirementFile.file_id == asset.id)
    )
    if existing is None:
        from datetime import datetime

        db.add(RequirementFile(requirement_id=requirement.id, file_id=asset.id, linked_by=current_user.id, created_at=datetime.now(UTC)))
        log_event(db, entity_type="requirement", entity_id=requirement.id, action="file_linked",
                  actor_id=current_user.id, project_id=project_id, detail={"file_id": str(asset.id)})
        db.commit()
    return asset


@router.get("/{requirement_id}/files", response_model=list[FileAssetOut])
def list_requirement_files(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    return db.scalars(
        select(FileAsset)
        .join(RequirementFile, RequirementFile.file_id == FileAsset.id)
        .where(RequirementFile.requirement_id == requirement_id)
    ).all()


@router.delete("/{requirement_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_requirement_file(
    project_id: UUID, requirement_id: UUID, file_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Removes a file from a requirement. Direct (non-shared) uploads are
    deleted outright; shared org resources are only unlinked (C-M-03/C-M-04)."""
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    link = db.scalar(
        select(RequirementFile).where(RequirementFile.requirement_id == requirement.id, RequirementFile.file_id == file_id)
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this requirement.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None and not asset.is_org_resource:
        delete_file(db, asset)
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()
