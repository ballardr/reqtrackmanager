"""
Module: routers.requirements.comments

Discussion thread comments on a requirement (C-R-01): add/list/edit,
single-reaction like/unlike, and per-comment file attachments. Comments
live outside the requirement's own version history (C-G-12 doesn't apply
here — see `ReviewComment`'s docstring), so none of these endpoints check
the requirement's lock state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.change_request import ReviewComment
from app.models.enums import ReviewTargetType
from app.models.file import CommentFile, FileAsset
from app.models.notification import NotificationType
from app.models.project import Project
from app.models.user import User
from app.routers.requirements.core import _get_requirement_in_project
from app.schemas.file import FileAssetOut
from app.schemas.requirement import CommentCreate, CommentOut, CommentUpdate
from app.services import engagement, notifications
from app.services.audit import log_event
from app.services.files import upload_file
from app.services.rbac import require_project_view

router = APIRouter(tags=["requirements-comments"])


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
