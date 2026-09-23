"""
Module: modules.decisions.project_router.comments

Comment CRUD/edit and comment-file attach/detach. See the package's own
`__init__.py` docstring for the full router-split account.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.decisions.models import DecisionComment, DecisionCommentFile
from app.modules.decisions.project_router._shared import _get_decision_in_project, _require_view
from app.modules.decisions.schemas import DecisionCommentCreate, DecisionCommentOut, DecisionCommentUpdate
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE
from app.schemas.file import FileAssetOut
from app.services.audit import log_event
from app.services.files import delete_file, upload_file

router = APIRouter(tags=["decisions-comments"])


def _comment_to_out(db: Session, comment: DecisionComment) -> DecisionCommentOut:
    author = db.get(User, comment.author_id)
    attachments = db.scalars(
        select(FileAsset)
        .join(DecisionCommentFile, DecisionCommentFile.file_id == FileAsset.id)
        .where(DecisionCommentFile.comment_id == comment.id)
    ).all()
    return DecisionCommentOut(
        id=comment.id, decision_id=comment.decision_id, author_id=comment.author_id,
        author_display_name=author.display_name if author is not None else "Unknown user",
        body=comment.body, created_at=comment.created_at, edited_at=comment.edited_at,
        attachments=[FileAssetOut.model_validate(a) for a in attachments],
    )


@router.post("/{decision_id}/comments", response_model=DecisionCommentOut, status_code=status.HTTP_201_CREATED)
def add_decision_comment(
    project_id: UUID, decision_id: UUID, payload: DecisionCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    decision = _get_decision_in_project(db, project_id, decision_id)
    comment = DecisionComment(decision_id=decision.id, author_id=current_user.id, body=payload.body)
    db.add(comment)
    db.flush()
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="comment_added",
              actor_id=current_user.id, project_id=project_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _comment_to_out(db, comment)


@router.get("/{decision_id}/comments", response_model=list[DecisionCommentOut])
def list_decision_comments(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    decision = _get_decision_in_project(db, project_id, decision_id)
    comments = db.scalars(
        select(DecisionComment).where(DecisionComment.decision_id == decision.id).order_by(DecisionComment.created_at)
    ).all()
    return [_comment_to_out(db, c) for c in comments]


@router.patch("/{decision_id}/comments/{comment_id}", response_model=DecisionCommentOut)
def edit_decision_comment(
    project_id: UUID, decision_id: UUID, comment_id: UUID, payload: DecisionCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Author-only — mirrors `routers.requirements.edit_comment`'s
    identical rule (not even a Decision Owner may edit someone else's
    words)."""
    _get_decision_in_project(db, project_id, decision_id)
    comment = db.get(DecisionComment, comment_id)
    if comment is None or comment.decision_id != decision_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return _comment_to_out(db, comment)


@router.post(
    "/{decision_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED,
)
async def upload_decision_comment_attachment(
    project_id: UUID, decision_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Mirrors `routers.requirements.upload_comment_attachment`'s pattern
    exactly: author-only, never subject to the Decision's own content lock
    (a comment thread isn't governed content, same reasoning as that
    endpoint's own docstring)."""
    project = db.get(Project, project_id)
    _get_decision_in_project(db, project_id, decision_id)
    comment = db.get(DecisionComment, comment_id)
    if comment is None or comment.decision_id != decision_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(DecisionCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision_id, action="comment_file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{decision_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_decision_comment_attachment(
    project_id: UUID, decision_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Author-only, same reasoning as `upload_decision_comment_attachment`.
    Always a direct upload (never a shared org resource, unlike a Decision's
    own direct attachments), so the underlying `FileAsset` is deleted
    outright — mirrors `routers.requirements.remove_comment_attachment`."""
    _get_decision_in_project(db, project_id, decision_id)
    comment = db.get(DecisionComment, comment_id)
    if comment is None or comment.decision_id != decision_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may remove its attachments.")
    link = db.scalar(
        select(DecisionCommentFile).where(DecisionCommentFile.comment_id == comment.id, DecisionCommentFile.file_id == file_id)
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this comment.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        # Unlike `routers.requirements.remove_comment_attachment` (which
        # plain-deletes the `FileAsset` row without freeing its storage
        # backend bytes), this uses `delete_file` so the underlying object
        # is actually removed, not just its metadata row — a same-shape
        # improvement kept local to this module rather than editing that
        # unrelated core file as part of this phase. **Decided by: Agent.**
        delete_file(db, asset)
    db.commit()
