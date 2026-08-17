"""
Module: routers.requirements

Requirement CRUD, version history / change log (C-A-09), traceability links
(C-G-09), keyword search (C-M-01), discussion threads (C-R-01), and scoping-
stage-only ordering (C-E-03).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
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
from app.models.action_type import ActionTypeDefinition
from app.models.change_request import ChangeRequest, ReviewComment
from app.models.custom_field import CustomFieldEntityKind, CustomFieldType
from app.models.enums import (
    ChangeRequestStatus,
    ProjectRole,
    RequirementLevel,
    RequirementReviewOutcome,
    RequirementStatus,
    ReviewTargetType,
    StageStatus,
)
from app.models.file import CommentFile, FileAsset, RequirementFile
from app.models.notification import NotificationType
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.requirement import Requirement, RequirementLink, RequirementReview, RequirementVersion
from app.models.requirement_action import RequirementAction, RequirementActionLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.schemas.action import RequirementActionCreate, RequirementActionLinkCreate, RequirementActionOut
from app.schemas.changes import ChangeEntryOut
from app.schemas.file import FileAssetOut, LinkResourceRequest
from app.schemas.project import MoveDirection
from app.schemas.requirement import (
    CommentCreate,
    CommentOut,
    CommentUpdate,
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
from app.services.actions import action_to_out, generate_unique_code, get_requirement_action_in_project
from app.services.audit import log_event
from app.services.bundle_common import enforce_upload_size_limit
from app.services.changes import get_project_changes
from app.services.custom_fields import validate_custom_field_values
from app.services.downloads import filename_safe
from app.services.files import delete_file, upload_file
from app.services.rbac import get_effective_project_roles, require_project_manage, require_project_view
from app.services.requirement_csv import (
    CUSTOM_FIELD_COLUMN_PREFIX,
    custom_field_definitions_for_export,
    export_requirements_csv,
)
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
        description=version.description,
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
    if category.component_id != component.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Category does not belong to the selected component.")

    target_stage_id = payload.target_stage_id
    if target_stage_id is None:
        # Not left unset: default to the project's own earliest stage (by
        # sort_order), the same backfill convention migration 0004 and CSV
        # import use — see RequirementCreate.target_stage_id's docstring.
        default_stage = db.scalar(
            select(ProjectStage).where(ProjectStage.project_id == project_id).order_by(ProjectStage.sort_order.asc())
        )
        if default_stage is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project has no stages; target_stage_id is required.")
        target_stage_id = default_stage.id
    else:
        stage = db.get(ProjectStage, target_stage_id)
        if stage is None or stage.project_id != project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid target_stage_id.")

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
        description=payload.description,
        owner_id=payload.owner_id, keywords=payload.keywords, sort_order=count,
        target_stage_id=target_stage_id, level=payload.level,
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

    Required columns: `name`, `component_prefix` (must match an existing
    `ProjectComponent.prefix`), `category_prefix` (must match an existing
    `ProjectCategory.prefix` *nested under that same component* —
    categories are unique per component, not per project).

    Optional columns, all of which round-trip with `GET .../export`:
    `reasoning`, `clarification`, `description`, `level`
    ("requirement"/"recommended", defaults to "requirement"),
    `target_version` (must match an existing `ProjectStage.name`, defaults
    to the project's earliest stage), `owner_email` (must match an existing
    user's email; blank falls back to the importing user, same as a normal
    create), `keywords` (`;`-separated), `review_date` (`YYYY-MM-DD`),
    `review_lead_days` (integer), `reviewer_email`, and one
    `cf_<custom field name>` column per the project's requirement custom
    field definitions (validated the same way `POST` (create) validates
    them — see `validate_custom_field_values`).

    `unique_code`, `status`, `links`, and `attachments` are accepted but
    ignored if present — `GET .../export` includes them for reference/
    round-trip convenience, but a flat CSV row can't safely recreate
    cross-requirement links or binary attachments, and status has its own
    workflow-transition rules (every imported row is created as `draft`,
    matching `POST` (create)'s own default).

    Unknown prefixes/stage names/emails or invalid custom field values are
    reported as row errors rather than silently creating new components/
    categories/stages or dropping the requirement's owner. Registered
    before `GET /{requirement_id}` so the static "/import" path isn't
    swallowed by that dynamic route.

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
    # Keyed by (component_id, prefix), not prefix alone: a category prefix is
    # only unique within its parent component now (the tree), so two
    # categories under different components can share a prefix without this
    # lookup silently colliding on the wrong one.
    categories_by_key = {
        (c.component_id, c.prefix): c
        for c in db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == project_id)).all()
    }
    stages = {s.name: s for s in db.scalars(select(ProjectStage).where(ProjectStage.project_id == project_id)).all()}
    # target_stage_id is mandatory on every requirement — a CSV row that
    # doesn't specify target_version falls back to the project's own
    # earliest stage (by sort_order), the same backfill convention
    # migration 0004 uses for pre-existing rows that had no target at all.
    default_stage = min(stages.values(), key=lambda s: s.sort_order) if stages else None
    definitions_by_name = {d.name: d for d in custom_field_definitions_for_export(db, project_id)}

    raw = await file.read()
    enforce_upload_size_limit(raw, what="CSV upload")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    custom_field_columns = [h for h in (reader.fieldnames or []) if h.startswith(CUSTOM_FIELD_COLUMN_PREFIX)]

    count = len(db.scalars(select(Requirement.id).where(Requirement.project_id == project_id)).all())
    errors: list[RequirementImportError] = []
    created = 0
    email_cache: dict[str, User | None] = {}

    def _lookup_user(email: str) -> User | None:
        normalized = email.strip().lower()
        if normalized not in email_cache:
            email_cache[normalized] = db.scalar(select(User).where(User.email == normalized))
        return email_cache[normalized]

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
        category = categories_by_key.get((component.id, category_prefix))
        if category is None:
            errors.append(RequirementImportError(
                row=row_num, message=f"Unknown category_prefix '{category_prefix}' for component '{component_prefix}'."
            ))
            continue
        try:
            level = RequirementLevel(level_raw)
        except ValueError:
            errors.append(RequirementImportError(row=row_num, message=f"Invalid level '{level_raw}'."))
            continue
        target_stage_id = default_stage.id if default_stage else None
        if target_version:
            stage = stages.get(target_version)
            if stage is None:
                errors.append(RequirementImportError(row=row_num, message=f"Unknown target_version '{target_version}'."))
                continue
            target_stage_id = stage.id
        if target_stage_id is None:
            errors.append(RequirementImportError(row=row_num, message="Project has no stages; cannot assign a target."))
            continue

        owner_email = (row.get("owner_email") or "").strip()
        owner_id = None
        if owner_email:
            owner = _lookup_user(owner_email)
            if owner is None:
                errors.append(RequirementImportError(row=row_num, message=f"Unknown owner_email '{owner_email}'."))
                continue
            owner_id = owner.id

        reviewer_email = (row.get("reviewer_email") or "").strip()
        reviewer_id = None
        if reviewer_email:
            reviewer = _lookup_user(reviewer_email)
            if reviewer is None:
                errors.append(RequirementImportError(row=row_num, message=f"Unknown reviewer_email '{reviewer_email}'."))
                continue
            reviewer_id = reviewer.id

        review_date_raw = (row.get("review_date") or "").strip()
        review_date_value = None
        if review_date_raw:
            try:
                review_date_value = date.fromisoformat(review_date_raw)
            except ValueError:
                errors.append(RequirementImportError(
                    row=row_num, message=f"Invalid review_date '{review_date_raw}' (expected YYYY-MM-DD)."
                ))
                continue

        review_lead_days_raw = (row.get("review_lead_days") or "").strip()
        review_lead_days_value = None
        if review_lead_days_raw:
            try:
                review_lead_days_value = int(review_lead_days_raw)
            except ValueError:
                errors.append(RequirementImportError(row=row_num, message=f"Invalid review_lead_days '{review_lead_days_raw}'."))
                continue

        raw_custom_fields: dict[str, object] = {}
        for column in custom_field_columns:
            definition = definitions_by_name.get(column[len(CUSTOM_FIELD_COLUMN_PREFIX):])
            if definition is None:
                continue  # stale/unknown column name (e.g. field renamed/deleted since export) — ignore, don't error
            cell = row.get(column, "")
            if definition.field_type == CustomFieldType.CHECKBOX:
                # A checkbox has no "unanswered" state at the storage level
                # (unlike text/list) — a blank cell most naturally reads as
                # unchecked rather than "not set", so it's always included.
                raw_custom_fields[str(definition.id)] = cell.strip().lower() in {"true", "1", "yes", "x"}
            elif cell != "":
                raw_custom_fields[str(definition.id)] = cell
        try:
            custom_fields = validate_custom_field_values(db, project_id, CustomFieldEntityKind.REQUIREMENT, raw_custom_fields)
        except HTTPException as exc:
            errors.append(RequirementImportError(row=row_num, message=str(exc.detail)))
            continue

        keywords = [k.strip() for k in (row.get("keywords") or "").split(";") if k.strip()]

        create_requirement(
            db, project, component, category, current_user,
            name=name, reasoning=(row.get("reasoning") or "").strip(),
            clarification=(row.get("clarification") or "").strip(), description=(row.get("description") or "").strip(),
            owner_id=owner_id, keywords=keywords, sort_order=count, target_stage_id=target_stage_id, level=level,
            custom_fields=custom_fields, review_date=review_date_value, review_lead_days=review_lead_days_value,
            reviewer_id=reviewer_id,
        )
        count += 1
        created += 1

    if created:
        log_event(db, entity_type="project", entity_id=project_id, action="requirements_imported",
                   actor_id=current_user.id, project_id=project_id, detail={"created": created, "errors": len(errors)})
        db.commit()
    return RequirementImportResult(created=created, errors=errors)


@router.get("/export")
def export_requirements(
    project_id: UUID, include_archived: bool = False,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Exports every field of this project's requirements as a full-fidelity
    CSV — custom field values, target stage, keywords, review scheduling,
    and more — directly re-importable via `POST .../import` (see that
    endpoint's docstring for exactly which columns round-trip vs. are
    reference-only). Distinct from `POST /reports/csv` (R-F-02), which
    produces a fixed, formatted report table rather than a round-trippable
    data dump — see `services.reports`'s module docstring.

    Registered before `GET /{requirement_id}` so this static path isn't
    swallowed by that dynamic route (same reasoning as `/import` above).
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    csv_bytes = export_requirements_csv(db, project, include_archived=include_archived)
    return Response(
        content=csv_bytes, media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_safe(project.name, fallback="project")}-requirements-export.csv"'
        },
    )


@router.get("/reviews/due", response_model=list[RequirementDueForReviewOut])
def list_due_reviews(
    project_id: UUID,
    component_id: UUID | None = None,
    reviewer_id: UUID | None = None,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Requirements due/overdue for review in this project, project-basis (C-R-09).

    Registered before `GET /{requirement_id}` so this static path isn't
    swallowed by that dynamic route (same reasoning as `/import` above).
    Supports an optional filter panel (`component_id`/`reviewer_id`) for
    projects with enough due reviews that a flat list stops being scannable.
    """
    due = get_due_reviews_for_project(db, project_id)
    if component_id is not None:
        due = [(version, req) for version, req in due if req.component_id == component_id]
    if reviewer_id is not None:
        due = [(version, req) for version, req in due if version.reviewer_id == reviewer_id]

    reviewer_ids = {version.reviewer_id for version, _ in due if version.reviewer_id is not None}
    reviewer_names = (
        dict(db.execute(select(User.id, User.display_name).where(User.id.in_(reviewer_ids))).all())
        if reviewer_ids
        else {}
    )
    component_ids = {req.component_id for _, req in due}
    component_names = (
        dict(db.execute(select(ProjectComponent.id, ProjectComponent.name).where(ProjectComponent.id.in_(component_ids))).all())
        if component_ids
        else {}
    )

    return [
        RequirementDueForReviewOut(
            requirement_id=req.id, project_id=req.project_id, unique_code=req.unique_code,
            name=version.name, review_date=version.review_date, reviewer_id=version.reviewer_id,
            reviewer_name=reviewer_names.get(version.reviewer_id) if version.reviewer_id else None,
            component_id=req.component_id, component_name=component_names.get(req.component_id, ""),
        )
        for version, req in due
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
    if payload.status == RequirementStatus.APPROVED:
        # C-U-03's clarification is explicit that approving a requirement is
        # a *Project Manager* capability layered on top of, not shared
        # with, what administrators/stakeholders can do ("Project Managers
        # can also provide approvals for change requests and approval of
        # project requirements") — the same distinction
        # decide_change_request already enforces for CR approval
        # specifically ("C-U-03: project manager only"), which this direct-
        # edit path had not mirrored: any of the three CAN_EDIT_ROLES
        # (including a plain Stakeholder) could otherwise set
        # status="approved" here and become the requirement's own
        # approval_authority, self-approving and locking it.
        if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can approve a requirement.")
    if payload.status == RequirementStatus.COMPLETED:
        # Completion has its own dedicated, precondition-checked endpoint
        # (POST .../complete, requiring the current status to already be
        # "approved") — allowing it here too would let a caller jump
        # straight from draft to completed in one request, skipping that
        # precondition entirely regardless of role.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use POST .../complete to mark a requirement completed.")
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
        description=payload.description,
        status_value=payload.status, owner_id=payload.owner_id,
        target_stage_id=payload.target_stage_id, target_stage_explicitly_set=payload.target_stage_id is not None,
        level=payload.level,
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
        if category.component_id != component.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Category does not belong to the selected component.")
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
            clarification=v.clarification, description=v.description, status=v.status, owner_id=v.owner_id,
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


def _link_to_out(db: Session, link: RequirementLink, viewpoint_requirement_id: UUID) -> RequirementLinkOut:
    """Resolves a `RequirementLink` into the API shape from the perspective
    of `viewpoint_requirement_id` — whichever requirement `GET
    /{requirement_id}/links` was called for. Direction and the
    other-requirement's display fields can only be resolved server-side
    (per-request), since a link row alone doesn't say which end the caller
    is looking from (see `schemas.requirement.RequirementLinkOut`'s
    docstring)."""
    link_type = db.get(RequirementLinkTypeDefinition, link.link_type_id)
    if link.source_requirement_id == viewpoint_requirement_id:
        direction = "outgoing"
        display_name = link_type.forward_name if link_type is not None else ""
        other_id = link.target_requirement_id
    else:
        direction = "incoming"
        display_name = link_type.reverse_name if link_type is not None else ""
        other_id = link.source_requirement_id
    other = db.get(Requirement, other_id)
    other_version = get_current_version(db, other_id) if other is not None else None
    return RequirementLinkOut(
        id=link.id, source_requirement_id=link.source_requirement_id, target_requirement_id=link.target_requirement_id,
        link_type_id=link.link_type_id, direction=direction, display_name=display_name,
        other_requirement_id=other_id,
        other_requirement_unique_code=other.unique_code if other is not None else "",
        other_requirement_name=other_version.name if other_version is not None else "",
    )


@router.post("/{requirement_id}/links", response_model=RequirementLinkOut, status_code=status.HTTP_201_CREATED)
def create_link(
    project_id: UUID, requirement_id: UUID, payload: RequirementLinkCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Creates a traceability link between two requirements (C-G-09). Not
    gated by either requirement's lock state — see `RequirementLink`'s
    model docstring for why traceability metadata sits outside C-G-12's
    change-log boundary."""
    _require_edit_role(db, current_user, project_id)
    project = db.get(Project, project_id)
    _get_requirement_in_project(db, project_id, requirement_id)
    target = _get_requirement_in_project(db, project_id, payload.target_requirement_id)
    link_type = db.get(RequirementLinkTypeDefinition, payload.link_type_id)
    if link_type is None or link_type.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "link_type_id must be a link type defined in this project's organisation.")
    link = RequirementLink(
        source_requirement_id=requirement_id, target_requirement_id=target.id,
        link_type_id=payload.link_type_id, created_by=current_user.id,
    )
    db.add(link)
    db.flush()
    log_event(db, entity_type="requirement_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"source_requirement_id": str(requirement_id), "target_requirement_id": str(target.id),
                      "link_type_id": str(payload.link_type_id)})
    db.commit()
    db.refresh(link)
    return _link_to_out(db, link, requirement_id)


@router.get("/{requirement_id}/links", response_model=list[RequirementLinkOut])
def list_links(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    links = db.scalars(
        select(RequirementLink).where(
            (RequirementLink.source_requirement_id == requirement_id)
            | (RequirementLink.target_requirement_id == requirement_id)
        )
    ).all()
    return [_link_to_out(db, link, requirement_id) for link in links]


@router.delete("/{requirement_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(
    project_id: UUID, requirement_id: UUID, link_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Removes a traceability link. 404s unless `link_id`'s source or
    target is `requirement_id` — deletable from either end, not just the
    end it was created from."""
    _require_edit_role(db, current_user, project_id)
    _get_requirement_in_project(db, project_id, requirement_id)
    link = db.get(RequirementLink, link_id)
    if link is None or requirement_id not in (link.source_requirement_id, link.target_requirement_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
    log_event(db, entity_type="requirement_link", entity_id=link.id, action="deleted",
              actor_id=current_user.id, project_id=project_id,
              detail={"source_requirement_id": str(link.source_requirement_id),
                      "target_requirement_id": str(link.target_requirement_id)})
    db.delete(link)
    db.commit()


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
                actor_id=current_user.id,
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


@router.patch("/{requirement_id}/comments/{comment_id}", response_model=CommentOut)
def edit_comment(
    project_id: UUID, requirement_id: UUID, comment_id: UUID, payload: CommentUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Edits a comment's body — author-only (not even a project manager may
    edit someone else's words), and always stamps `edited_at` so the
    discussion thread visibly denotes an edit rather than silently rewriting
    history."""
    _get_requirement_in_project(db, project_id, requirement_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_type != ReviewTargetType.REQUIREMENT or comment.target_id != requirement_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return engagement.comment_to_out(db, comment, current_user.id)


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


@router.post("/{requirement_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_comment_attachment(
    project_id: UUID, requirement_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Uploads a file attached to a discussion comment. Unlike a direct
    requirement attachment, this is never subject to the requirement's own
    lock — a comment thread isn't part of the requirement's governed
    content (C-G-12 only applies to the requirement's own fields, per
    `ReviewComment`'s docstring on why comments live outside version
    history). Author-only, same as editing the comment's body: attaching a
    file to someone else's comment after the fact isn't "commenting", it's
    silently altering their post — the frontend only ever calls this while
    composing a new comment or editing your own existing one."""
    _get_requirement_in_project(db, project_id, requirement_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_type != ReviewTargetType.REQUIREMENT or comment.target_id != requirement_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    project = db.get(Project, project_id)
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(CommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type="requirement", entity_id=requirement_id, action="comment_file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{requirement_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_comment_attachment(
    project_id: UUID, requirement_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Removes a file from a comment — author-only, same reasoning as
    `upload_comment_attachment`. Comment attachments are always direct
    uploads (never a linked org shared resource, unlike requirement
    attachments), so the underlying `FileAsset` is deleted outright, not
    just unlinked."""
    _get_requirement_in_project(db, project_id, requirement_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_type != ReviewTargetType.REQUIREMENT or comment.target_id != requirement_id:
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
    """Uploads and attaches a new file to a requirement (C-M-02).

    Governed by the same creation-or-change-request-only rule as every
    other requirement content field once it's locked (C-G-12) — a direct
    attachment is only allowed while the requirement is still unlocked
    (i.e. at/around creation time); once approved, new attachments must go
    through a change request instead (see `decide_change_request`'s
    "attachments" handling). Hardening-review finding: this endpoint
    previously had no lock check at all, unlike every other field, letting
    attachments bypass the change-request-only rule entirely.
    """
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    if is_locked(get_current_version(db, requirement.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved; new attachments must be added via a change request.",
        )
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
    """Links an organisation shared resource file to a requirement (C-M-04).

    Same creation-or-change-request-only lock rule as
    `upload_requirement_attachment` — see its docstring."""
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    if is_locked(get_current_version(db, requirement.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved; new attachments must be added via a change request.",
        )
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


# --- Requirement<->action linking (see models.requirement_action) ----------
#
# A `RequirementAction` has its own project-scoped identity (routers.actions)
# so it can be linked from multiple requirements; these four endpoints are
# the requirement-side half of that many-to-many relationship.


@router.post("/{requirement_id}/actions", status_code=status.HTTP_204_NO_CONTENT)
def link_action(
    project_id: UUID, requirement_id: UUID, payload: RequirementActionLinkCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Links an existing action to this requirement. Unlike `create_link`
    (requirement-to-requirement), linking an action isn't itself content
    with a display direction — just membership in the action's "which
    requirements does this satisfy" set — so this returns no body."""
    _require_edit_role(db, current_user, project_id)
    _get_requirement_in_project(db, project_id, requirement_id)
    action = get_requirement_action_in_project(db, project_id, payload.action_id)
    existing = db.scalar(
        select(RequirementActionLink).where(
            RequirementActionLink.requirement_id == requirement_id, RequirementActionLink.action_id == action.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This action is already linked to this requirement.")
    db.add(RequirementActionLink(
        requirement_id=requirement_id, action_id=action.id, linked_by=current_user.id, created_at=datetime.now(UTC),
    ))
    log_event(db, entity_type="requirement_action_link", entity_id=action.id, action="linked",
              actor_id=current_user.id, project_id=project_id,
              detail={"requirement_id": str(requirement_id), "action_id": str(action.id)})
    db.commit()


@router.post(
    "/{requirement_id}/actions/create-and-link", response_model=RequirementActionOut, status_code=status.HTTP_201_CREATED
)
def create_and_link_action(
    project_id: UUID, requirement_id: UUID, payload: RequirementActionCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Creates a new action and links it to this requirement in one
    transaction — avoids a two-request create-then-link race in the
    inline-create UI (create the action, then have the very next `POST
    .../actions` fail or double-submit)."""
    _require_edit_role(db, current_user, project_id)
    _get_requirement_in_project(db, project_id, requirement_id)
    project = db.get(Project, project_id)
    action_type = db.get(ActionTypeDefinition, payload.action_type_id)
    if action_type is None or action_type.project_id != project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action_type_id must be an action type defined in this project.")
    action = RequirementAction(
        project_id=project_id, unique_code=generate_unique_code(project), action_type_id=payload.action_type_id,
        title=payload.title, description=payload.description, assignee_id=payload.assignee_id,
        due_date=payload.due_date, creator_id=current_user.id,
    )
    db.add(action)
    db.flush()
    db.add(RequirementActionLink(
        requirement_id=requirement_id, action_id=action.id, linked_by=current_user.id, created_at=datetime.now(UTC),
    ))
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="created",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
              detail={"unique_code": action.unique_code, "title": action.title, "linked_requirement_id": str(requirement_id)})
    db.commit()
    db.refresh(action)
    return action_to_out(db, action)


@router.get("/{requirement_id}/actions", response_model=list[RequirementActionOut])
def list_requirement_actions(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists every action linked to this requirement."""
    _get_requirement_in_project(db, project_id, requirement_id)
    actions = db.scalars(
        select(RequirementAction)
        .join(RequirementActionLink, RequirementActionLink.action_id == RequirementAction.id)
        .where(RequirementActionLink.requirement_id == requirement_id)
        .order_by(RequirementAction.unique_code)
    ).all()
    return [action_to_out(db, a) for a in actions]


@router.delete("/{requirement_id}/actions/{action_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_action(
    project_id: UUID, requirement_id: UUID, action_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Unlinks an action from this requirement — never deletes the action
    itself, which may still be linked from other requirements."""
    _require_edit_role(db, current_user, project_id)
    _get_requirement_in_project(db, project_id, requirement_id)
    link = db.scalar(
        select(RequirementActionLink).where(
            RequirementActionLink.requirement_id == requirement_id, RequirementActionLink.action_id == action_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This action is not linked to this requirement.")
    log_event(db, entity_type="requirement_action_link", entity_id=action_id, action="unlinked",
              actor_id=current_user.id, project_id=project_id,
              detail={"requirement_id": str(requirement_id), "action_id": str(action_id)})
    db.delete(link)
    db.commit()
