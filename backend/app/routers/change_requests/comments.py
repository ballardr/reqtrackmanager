"""
Module: routers.change_requests.comments

Discussion-thread comments on a change request (C-R-01): adding, listing,
editing, attaching/removing a file, and reacting/unreacting — notifying
subscribers on a new comment.

Split out of the former flat `routers/change_requests.py` as a pure
code-organization refactor — see `routers/change_requests/__init__.py`'s
module docstring for the package layout. `_get_cr_in_project` is imported
from `_shared.py` (used by four sibling buckets); `CAN_SUBMIT_ROLES` is
imported from `core.py` (used by exactly one sibling bucket besides core
itself). Subscription (`PUT`/`DELETE /{cr_id}/subscription`) is a
different sub-resource and lives in its own `subscriptions.py` bucket
instead — matching how the `requirements/` package's own split gave
subscriptions their own dedicated bucket rather than folding them into
`comments.py`/`files.py`.
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
from app.routers.change_requests._shared import _get_cr_in_project
from app.routers.change_requests.core import CAN_SUBMIT_ROLES
from app.schemas.file import FileAssetOut
from app.schemas.requirement import CommentCreate, CommentOut, CommentUpdate
from app.services import engagement, notifications
from app.services.audit import log_event
from app.services.files import upload_file
from app.services.rbac import get_effective_project_roles, require_project_view

router = APIRouter(tags=["change-requests-comments"])


def _require_submit_role(db: Session, user: User, project_id: UUID) -> None:
    """Raises 403 unless `user` holds a change-request role on the project.

    No server-admin bypass (I-M-05): change request content is "data within
    organisations".
    """
    if not get_effective_project_roles(db, user.id, project_id) & set(CAN_SUBMIT_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders, administrators, or managers may do this.")


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
