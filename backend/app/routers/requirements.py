"""
Module: routers.requirements

Requirement CRUD, version history / change log (C-A-09), traceability links
(C-G-09), keyword search (C-M-01), discussion threads (C-R-01), and scoping-
stage-only ordering (C-E-03).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.metrics import (
    requirements_archived_total,
    requirements_created_total,
    requirements_updated_total,
)
from app.models.custom_field import CustomFieldEntityKind
from app.models.enums import ProjectRole, ReviewTargetType, StageStatus
from app.models.file import FileAsset, RequirementFile
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.requirement import Requirement, RequirementLink, RequirementVersion
from app.models.change_request import ReviewComment
from app.models.user import User
from app.schemas.file import FileAssetOut, LinkResourceRequest
from app.schemas.requirement import (
    CommentCreate,
    CommentOut,
    RequirementCreate,
    RequirementLinkCreate,
    RequirementLinkOut,
    RequirementOut,
    RequirementUpdate,
    RequirementVersionOut,
)
from app.schemas.project import MoveDirection
from app.services import pubsub
from app.services.audit import log_event
from app.services.custom_fields import validate_custom_field_values
from app.services.files import delete_file, upload_file
from app.services.rbac import get_effective_project_roles, require_project_view
from app.services.requirements import (
    apply_new_version,
    archive_requirement,
    create_requirement,
    get_current_version,
    get_keywords,
    is_locked,
    set_keywords,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/requirements", tags=["requirements"])

CAN_EDIT_ROLES = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)


def _require_edit_role(db: Session, user: User, project_id: UUID) -> None:
    if user.is_server_admin:
        return
    if not get_effective_project_roles(db, user.id, project_id) & set(CAN_EDIT_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders, administrators, or managers may do this.")


def _to_out(db: Session, requirement: Requirement, version: RequirementVersion) -> RequirementOut:
    return RequirementOut(
        id=requirement.id, project_id=requirement.project_id, unique_code=requirement.unique_code,
        name=version.name, reasoning=version.reasoning, clarification=version.clarification,
        status=version.status, owner_id=version.owner_id, component_id=requirement.component_id,
        category_id=requirement.category_id, sort_order=version.sort_order, creator_id=requirement.creator_id,
        is_archived=requirement.is_archived, is_locked=is_locked(version),
        keywords=get_keywords(db, requirement.id), custom_fields=version.custom_fields,
        created_at=requirement.created_at, updated_at=version.created_at,
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
        if not current_user.is_server_admin and ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(
            db, current_user.id, project_id
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can assign the creator.")
        creator_override_id = payload.creator_id

    count = len(db.scalars(select(Requirement.id).where(Requirement.project_id == project_id)).all())
    requirement = create_requirement(
        db, project, component, category, current_user,
        name=payload.name, reasoning=payload.reasoning, clarification=payload.clarification,
        owner_id=payload.owner_id, keywords=payload.keywords, sort_order=count,
        custom_fields=custom_fields, creator_override_id=creator_override_id,
    )
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="created",
              actor_id=current_user.id, project_id=project_id)
    requirements_created_total.inc()
    db.commit()
    db.refresh(requirement)
    version = get_current_version(db, requirement.id)
    pubsub.notify(project_id, {"type": "requirement", "action": "created", "id": str(requirement.id)})
    return _to_out(db, requirement, version)


@router.get("", response_model=list[RequirementOut])
def list_requirements(
    project_id: UUID,
    component_id: UUID | None = None,
    category_id: UUID | None = None,
    keyword: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists requirements, sorted by component/category (C-G-04) with search (U-E-01)."""
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
        out.append(_to_out(db, req, version))

    comp_order = {c.id: c.sort_order for c in db.scalars(
        select(ProjectComponent).where(ProjectComponent.project_id == project_id)).all()}
    cat_order = {c.id: c.sort_order for c in db.scalars(
        select(ProjectCategory).where(ProjectCategory.project_id == project_id)).all()}
    out.sort(key=lambda r: (comp_order.get(r.component_id, 0), cat_order.get(r.category_id, 0), r.sort_order))
    return out


@router.get("/{requirement_id}", response_model=RequirementOut)
def get_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    version = get_current_version(db, requirement.id)
    return _to_out(db, requirement, version)


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
        change_note=payload.change_note or "Direct edit during scoping.",
        custom_fields=custom_fields,
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
    return _to_out(db, requirement, new_version)


@router.delete("/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Archives (soft-deletes) a requirement, preserving its history (C-A-06)."""
    if not current_user.is_server_admin and not get_effective_project_roles(db, current_user.id, project_id) & {
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
            change_note=v.change_note, change_request_id=v.change_request_id,
            custom_fields=v.custom_fields,
            created_by=v.created_by, created_at=v.created_at, valid_to=v.valid_to,
        )
        for v in versions
    ]


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
    return _to_out(db, requirement, version)


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
    """Adds a discussion thread comment (C-R-01)."""
    _get_requirement_in_project(db, project_id, requirement_id)
    comment = ReviewComment(
        target_type=ReviewTargetType.REQUIREMENT, target_id=requirement_id,
        author_id=current_user.id, body=payload.body,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/{requirement_id}/comments", response_model=list[CommentOut])
def list_comments(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    return db.scalars(
        select(ReviewComment)
        .where(ReviewComment.target_type == ReviewTargetType.REQUIREMENT, ReviewComment.target_id == requirement_id)
        .order_by(ReviewComment.created_at)
    ).all()


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
        from datetime import datetime, timezone

        db.add(RequirementFile(requirement_id=requirement.id, file_id=asset.id, linked_by=current_user.id, created_at=datetime.now(timezone.utc)))
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
    db.commit()
