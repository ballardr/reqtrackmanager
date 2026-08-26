"""
Module: routers.actions

CRUD for requirement actions (`RequirementAction`) — a required task (e.g.
review, test) with its own project-scoped identity, independent of any one
requirement (see `models.requirement_action`'s module docstring). Also
carries the action's own discussion thread and direct file attachments,
each a close mirror of the equivalent requirement endpoints in
`routers.requirements` (comments/reactions reuse the same generic
`ReviewComment`/`CommentFile` machinery via `ReviewTargetType.ACTION`).

Requirement<->action linking itself (create-and-link, list-for-requirement,
unlink) lives in `routers.requirements` instead, alongside the requirement
it's linking from — see that module's "Requirement<->action linking"
section.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.change_request import ReviewComment
from app.models.enums import ProjectRole, RequirementActionOutcome, ReviewTargetType
from app.models.file import CommentFile, FileAsset, RequirementActionFile
from app.models.project import Project
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.schemas.action import RequirementActionCreate, RequirementActionOut, RequirementActionUpdate
from app.schemas.file import FileAssetOut
from app.schemas.requirement import CommentCreate, CommentOut, CommentUpdate
from app.services import engagement
from app.services.actions import (
    action_to_out,
    apply_outcome_transition,
    generate_unique_code,
    get_requirement_action_in_project,
)
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.project_hierarchy import resolve_effective_action_types
from app.services.rbac import get_effective_project_roles, require_project_manage, require_project_view

router = APIRouter(prefix="/api/v1/projects/{project_id}/actions", tags=["actions"])

# Mirrors `routers.requirements.CAN_EDIT_ROLES` exactly — no cross-router
# import precedent exists in this codebase (see `services.actions`' module
# docstring for why the IDOR-guard helper lives in a service module
# instead), so this small role tuple is duplicated rather than imported.
CAN_EDIT_ROLES = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)


def _require_edit_role(db: Session, user: User, project_id: UUID) -> None:
    """Raises 403 unless `user` holds an action-editing role on the project."""
    if not get_effective_project_roles(db, user.id, project_id) & set(CAN_EDIT_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders, administrators, or managers may do this.")


def _validate_action_type(db: Session, project_id: UUID, action_type_id: UUID) -> None:
    """400s unless `action_type_id` is one of `project_id`'s *effective*
    action types — its own, or (hierarchical projects, always on) a
    fallback inherited from its nearest ancestor
    (`services.project_hierarchy.resolve_effective_action_types`). This is
    what lets a `RequirementAction` in a child project reference the
    parent's `ActionTypeDefinition` row directly — a deliberate
    cross-project FK reference, the same shape nested-org-group role
    inheritance already uses (referencing another scope's row rather than
    copying it)."""
    effective_ids = {at.id for at in resolve_effective_action_types(db, project_id)}
    if action_type_id not in effective_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "action_type_id must be an action type defined in this project, or inherited from a parent project.",
        )


@router.post("", response_model=RequirementActionOut, status_code=status.HTTP_201_CREATED)
def create_action(
    project_id: UUID, payload: RequirementActionCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Creates a standalone requirement action. Does not link it to any
    requirement — see `routers.requirements`'s create-and-link endpoint for
    that in one step."""
    _require_edit_role(db, current_user, project_id)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    _validate_action_type(db, project_id, payload.action_type_id)
    action = RequirementAction(
        project_id=project_id, unique_code=generate_unique_code(project), action_type_id=payload.action_type_id,
        title=payload.title, description=payload.description, assignee_id=payload.assignee_id,
        due_date=payload.due_date, creator_id=current_user.id,
    )
    db.add(action)
    db.flush()
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="created",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
              detail={"unique_code": action.unique_code, "title": action.title})
    db.commit()
    db.refresh(action)
    return action_to_out(db, action)


@router.get("", response_model=list[RequirementActionOut])
def list_actions(
    project_id: UUID, outcome_status: RequirementActionOutcome | None = None,
    action_type_id: UUID | None = None, include_archived: bool = False,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    query = select(RequirementAction).where(RequirementAction.project_id == project_id)
    if not include_archived:
        query = query.where(RequirementAction.is_archived.is_(False))
    if outcome_status is not None:
        query = query.where(RequirementAction.outcome_status == outcome_status)
    if action_type_id is not None:
        query = query.where(RequirementAction.action_type_id == action_type_id)
    actions = db.scalars(query.order_by(RequirementAction.unique_code)).all()
    return [action_to_out(db, a) for a in actions]


@router.get("/{action_id}", response_model=RequirementActionOut)
def get_action(
    project_id: UUID, action_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    action = get_requirement_action_in_project(db, project_id, action_id)
    return action_to_out(db, action)


@router.patch("/{action_id}", response_model=RequirementActionOut)
def update_action(
    project_id: UUID, action_id: UUID, payload: RequirementActionUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Edits an action's fields. Setting `outcome_status` to something other
    than its current value stamps/clears `completed_at`/`completed_by` per
    `services.actions.apply_outcome_transition` (leaving it unset in the
    payload — `None` — makes this a no-op on outcome, editing only the
    other fields)."""
    _require_edit_role(db, current_user, project_id)
    action = get_requirement_action_in_project(db, project_id, action_id)
    _validate_action_type(db, project_id, payload.action_type_id)
    action.title = payload.title
    action.description = payload.description
    action.action_type_id = payload.action_type_id
    action.assignee_id = payload.assignee_id
    action.due_date = payload.due_date
    if payload.outcome_status is not None and payload.outcome_status != action.outcome_status:
        apply_outcome_transition(action, payload.outcome_status, current_user)
    project = db.get(Project, project_id)
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="updated",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
              detail={"outcome_status": action.outcome_status.value})
    db.commit()
    db.refresh(action)
    return action_to_out(db, action)


@router.post("/{action_id}/archive", response_model=RequirementActionOut)
def archive_action(
    project_id: UUID, action_id: UUID,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Archives (soft-deletes) an action, preserving its history — mirrors
    `routers.requirements::delete_requirement`'s archive-not-delete
    behaviour (C-A-06), gated the same way (managers/administrators)."""
    action = get_requirement_action_in_project(db, project_id, action_id)
    if action.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This action is already archived.")
    action.is_archived = True
    action.archived_at = datetime.now(UTC)
    action.archived_by = current_user.id
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="archived",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id)
    db.commit()
    db.refresh(action)
    return action_to_out(db, action)


@router.post("/{action_id}/unarchive", response_model=RequirementActionOut)
def unarchive_action(
    project_id: UUID, action_id: UUID,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Restores an archived action to the active list, undoing `archive_action`
    — same permission gate, mirroring `routers.projects::unarchive_project`
    (see that endpoint's docstring/precedent, per the 2026-08 UX audit's
    roadmap item on one-way archive). Unlike `archive_action`'s 409-on-
    already-archived, calling this on an action that isn't archived is a
    harmless no-op rather than an error, matching `unarchive_project`'s own
    idempotent shape.
    """
    action = get_requirement_action_in_project(db, project_id, action_id)
    action.is_archived = False
    action.archived_at = None
    action.archived_by = None
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id)
    db.commit()
    db.refresh(action)
    return action_to_out(db, action)


# --- Discussion thread (C-R-01) — direct mirror of the requirement's own ----


@router.post("/{action_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(
    project_id: UUID, action_id: UUID, payload: CommentCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Adds a discussion thread comment to an action (C-R-01). Unlike the
    requirement equivalent, this doesn't notify subscribers: actions have
    no subscription mechanism of their own (no `PUT .../subscription`
    endpoint exists for them)."""
    get_requirement_action_in_project(db, project_id, action_id)
    comment = ReviewComment(
        target_type=ReviewTargetType.ACTION, target_id=action_id, author_id=current_user.id, body=payload.body,
    )
    db.add(comment)
    db.flush()
    db.commit()
    db.refresh(comment)
    return engagement.comment_to_out(db, comment, current_user.id)


@router.get("/{action_id}/comments", response_model=list[CommentOut])
def list_comments(
    project_id: UUID, action_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    get_requirement_action_in_project(db, project_id, action_id)
    comments = db.scalars(
        select(ReviewComment)
        .where(ReviewComment.target_type == ReviewTargetType.ACTION, ReviewComment.target_id == action_id)
        .order_by(ReviewComment.created_at)
    ).all()
    return [engagement.comment_to_out(db, c, current_user.id) for c in comments]


@router.patch("/{action_id}/comments/{comment_id}", response_model=CommentOut)
def edit_comment(
    project_id: UUID, action_id: UUID, comment_id: UUID, payload: CommentUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Edits a comment's body — author-only, same reasoning as
    `routers.requirements::edit_comment`."""
    get_requirement_action_in_project(db, project_id, action_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_type != ReviewTargetType.ACTION or comment.target_id != action_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return engagement.comment_to_out(db, comment, current_user.id)


@router.put("/{action_id}/comments/{comment_id}/reaction", status_code=status.HTTP_204_NO_CONTENT)
def react_to_comment(
    project_id: UUID, action_id: UUID, comment_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    get_requirement_action_in_project(db, project_id, action_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_id != action_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    engagement.add_reaction(db, comment_id, current_user.id)


@router.delete("/{action_id}/comments/{comment_id}/reaction", status_code=status.HTTP_204_NO_CONTENT)
def unreact_to_comment(
    project_id: UUID, action_id: UUID, comment_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    get_requirement_action_in_project(db, project_id, action_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_id != action_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    engagement.remove_reaction(db, comment_id, current_user.id)


@router.post("/{action_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_comment_attachment(
    project_id: UUID, action_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Uploads a file attached to a discussion comment — author-only, same
    reasoning as `routers.requirements::upload_comment_attachment`."""
    get_requirement_action_in_project(db, project_id, action_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_type != ReviewTargetType.ACTION or comment.target_id != action_id:
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
    log_event(db, entity_type="requirement_action", entity_id=action_id, action="comment_file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{action_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_comment_attachment(
    project_id: UUID, action_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    get_requirement_action_in_project(db, project_id, action_id)
    comment = db.get(ReviewComment, comment_id)
    if comment is None or comment.target_type != ReviewTargetType.ACTION or comment.target_id != action_id:
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


# --- Direct file attachments (separate from comment attachments) -----------


@router.post("/{action_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_action_attachment(
    project_id: UUID, action_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Uploads and attaches a file directly to an action — mirrors
    `routers.requirements::upload_requirement_attachment`, minus the
    lock/change-request gating (an action has no locked/approved content
    state the way a requirement does)."""
    _require_edit_role(db, current_user, project_id)
    action = get_requirement_action_in_project(db, project_id, action_id)
    project = db.get(Project, project_id)
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(RequirementActionFile(action_id=action.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at))
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{action_id}/files", response_model=list[FileAssetOut])
def list_action_files(
    project_id: UUID, action_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    get_requirement_action_in_project(db, project_id, action_id)
    return db.scalars(
        select(FileAsset)
        .join(RequirementActionFile, RequirementActionFile.file_id == FileAsset.id)
        .where(RequirementActionFile.action_id == action_id)
    ).all()


@router.delete("/{action_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_action_file(
    project_id: UUID, action_id: UUID, file_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Removes a file from an action. Direct attachments are always deleted
    outright (unlike requirement attachments, actions have no shared
    org-resource-linking path — see §4.5's endpoint list)."""
    _require_edit_role(db, current_user, project_id)
    action = get_requirement_action_in_project(db, project_id, action_id)
    link = db.scalar(
        select(RequirementActionFile).where(RequirementActionFile.action_id == action.id, RequirementActionFile.file_id == file_id)
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this action.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()
