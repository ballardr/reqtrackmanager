"""
Module: routers.record_comments

The generic record comments API under `/projects/{project_id}/artefacts/{artefact_type}/{record_id}`: ordinary
comments on a record and pinned threads on its drawing, for every type a module opted in
(`ModuleDefinition.record_comments`).

Authorisation: any project member who can open the record may read and comment (a record the caller cannot open is
a 404, never a 403, as for the Links panel); editing is the author only; deleting another person's comment and
moving their pin need `manage` on the type. Comments are saved at once and are not under the record's version lock.
Rules and audit are in `services.record_comments`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.record_comments import (
    AnchoredThreadOut,
    AnchoredThreadsOut,
    CommentCreate,
    CommentPinRequest,
    CommentUpdate,
    PinIn,
    PinUpdate,
    RecordCommentOut,
    RecordCommentPinOut,
    RecordThreadOut,
)
from app.services import record_comments as comments
from app.services.link_graph import ArtefactResolver
from app.services.lookups import project_or_404
from app.services.rbac import require_project_view
from app.services.tags import require_visible_record

router = APIRouter(prefix="/api/v1/projects/{project_id}/artefacts/{artefact_type}/{record_id}", tags=["record-comments"])


def _spec(pin: PinIn) -> comments.PinSpec:
    """The service's pin position from the request body."""
    return comments.PinSpec(anchor_kind=pin.anchor_kind, anchor_key=pin.anchor_key, x=pin.x, y=pin.y)


def _open(
    db: Session, project_id: UUID, user: User, artefact_type: str, record_id: UUID,
) -> tuple[Project, ArtefactResolver, UUID | None]:
    """The project, resolver and owning project id of a record with generic comments that the caller can open.

    Raises:
        HTTPException: 404 when the type has no generic comments or the record is not visible here."""
    comments.provider_or_404(artefact_type)
    project = project_or_404(db, project_id)
    resolver = ArtefactResolver(db, project, user.id)
    return project, resolver, require_visible_record(resolver, project, artefact_type, record_id)


def _thread_out(
    db: Session, resolver: ArtefactResolver, user: User, artefact_type: str, record_id: UUID,
) -> RecordThreadOut:
    """The record's comments and pins as the response, with the viewer's rights."""
    manager = comments.can_manage(resolver, artefact_type)
    thread = comments.read_thread(db, artefact_type, record_id, viewer_id=user.id, manager=manager)
    return RecordThreadOut(
        comments=[_comment_out(r) for r in thread.comments],
        pins=[_pin_out(r) for r in thread.pins],
        can_pin=bool(comments.provider_or_404(artefact_type).anchor_kinds),
        can_manage=manager,
    )


def _pin_out(row: comments.PinRow) -> RecordCommentPinOut:
    """One pin as the response."""
    pin = row.pin
    return RecordCommentPinOut(
        id=pin.id, anchor_kind=pin.anchor_kind, anchor_key=pin.anchor_key, x=pin.x, y=pin.y,
        comment_count=row.comment_count, resolved=pin.resolved_at is not None, resolved_at=pin.resolved_at,
        resolved_by_display_name=row.resolved_by_display_name, can_move=row.can_move, can_delete=row.can_delete,
    )


def _comment_out(r: comments.CommentRow) -> RecordCommentOut:
    """One comment as the response."""
    return RecordCommentOut(
        id=r.comment.id, pin_id=r.comment.pin_id, author_id=r.comment.author_id, author_display_name=r.author_display_name,
        body=r.comment.body, created_at=r.comment.created_at, edited_at=r.comment.edited_at, can_edit=r.can_edit,
        can_delete=r.can_delete,
    )


@router.get("/anchored-comments", response_model=AnchoredThreadsOut)
def get_anchored_comments(
    project_id: UUID, artefact_type: str, record_id: UUID, current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> AnchoredThreadsOut:
    """The pinned threads on the project's drawings that are anchored to this box or line, each linking to its drawing,
    for the record's own page (read-only). Works for any registered type the caller can open; a type that is never an
    anchor simply has none."""
    project = project_or_404(db, project_id)
    resolver = ArtefactResolver(db, project, current_user.id)
    require_visible_record(resolver, project, artefact_type, record_id)
    found = comments.anchored_threads(db, resolver, project, record_id, viewer_id=current_user.id)
    return AnchoredThreadsOut(threads=[
        AnchoredThreadOut(
            record_type=t.record_type, record_id=t.record_id, record_label=t.record_label, pin=_pin_out(t.pin),
            comments=[_comment_out(c) for c in t.comments],
        )
        for t in found
    ])


@router.get("/comments", response_model=RecordThreadOut)
def get_record_comments(
    project_id: UUID, artefact_type: str, record_id: UUID, current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> RecordThreadOut:
    """The record's ordinary comments, pinned threads and pins, in a fixed number of statements."""
    _, resolver, _ = _open(db, project_id, current_user, artefact_type, record_id)
    return _thread_out(db, resolver, current_user, artefact_type, record_id)


@router.post("/comments", response_model=RecordThreadOut, status_code=status.HTTP_201_CREATED)
def add_record_comment(
    project_id: UUID, artefact_type: str, record_id: UUID, payload: CommentCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordThreadOut:
    """Adds a comment (ordinary, a reply, or the first of a new pin) and returns the record's whole thread, so a
    client redraws from one answer."""
    project, resolver, owner = _open(db, project_id, current_user, artefact_type, record_id)
    comments.add_comment(
        db, project=project, owner_project_id=owner, user=current_user, artefact_type=artefact_type,
        record_id=record_id, body=payload.body, pin_id=payload.pin_id,
        new_pin=_spec(payload.pin) if payload.pin else None,
    )
    db.commit()
    return _thread_out(db, resolver, current_user, artefact_type, record_id)


@router.patch("/comments/{comment_id}", response_model=RecordThreadOut)
def edit_record_comment(
    project_id: UUID, artefact_type: str, record_id: UUID, comment_id: UUID, payload: CommentUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordThreadOut:
    """Edits the caller's own comment."""
    project, resolver, _ = _open(db, project_id, current_user, artefact_type, record_id)
    comments.edit_comment(
        db, project=project, user=current_user, artefact_type=artefact_type, record_id=record_id,
        comment_id=comment_id, body=payload.body,
    )
    db.commit()
    return _thread_out(db, resolver, current_user, artefact_type, record_id)


@router.delete("/comments/{comment_id}", response_model=RecordThreadOut)
def delete_record_comment(
    project_id: UUID, artefact_type: str, record_id: UUID, comment_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordThreadOut:
    """Deletes a comment (the author's own, or any with `manage`); the last comment of a thread removes the thread."""
    project, resolver, _ = _open(db, project_id, current_user, artefact_type, record_id)
    comments.delete_comment(
        db, project=project, user=current_user, manager=comments.can_manage(resolver, artefact_type),
        artefact_type=artefact_type, record_id=record_id, comment_id=comment_id,
    )
    db.commit()
    return _thread_out(db, resolver, current_user, artefact_type, record_id)


@router.post("/comments/{comment_id}/pin", response_model=RecordThreadOut)
def pin_record_comment(
    project_id: UUID, artefact_type: str, record_id: UUID, comment_id: UUID, payload: CommentPinRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordThreadOut:
    """Places an ordinary comment on the record's drawing."""
    project, resolver, owner = _open(db, project_id, current_user, artefact_type, record_id)
    comments.pin_comment(
        db, project=project, owner_project_id=owner, user=current_user,
        manager=comments.can_manage(resolver, artefact_type), artefact_type=artefact_type, record_id=record_id,
        comment_id=comment_id, spec=_spec(payload.pin),
    )
    db.commit()
    return _thread_out(db, resolver, current_user, artefact_type, record_id)


@router.patch("/comment-pins/{pin_id}", response_model=RecordThreadOut)
def update_record_comment_pin(
    project_id: UUID, artefact_type: str, record_id: UUID, pin_id: UUID, payload: PinUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordThreadOut:
    """Moves or re-anchors a pin, and/or resolves or reopens its thread."""
    project, resolver, _ = _open(db, project_id, current_user, artefact_type, record_id)
    comments.update_pin(
        db, project=project, user=current_user, manager=comments.can_manage(resolver, artefact_type),
        artefact_type=artefact_type, record_id=record_id, pin_id=pin_id,
        spec=_spec(payload.pin) if payload.pin else None, resolved=payload.resolved,
    )
    db.commit()
    return _thread_out(db, resolver, current_user, artefact_type, record_id)


@router.delete("/comment-pins/{pin_id}", response_model=RecordThreadOut)
def delete_record_comment_pin(
    project_id: UUID, artefact_type: str, record_id: UUID, pin_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordThreadOut:
    """Deletes a whole thread with its pin."""
    project, resolver, _ = _open(db, project_id, current_user, artefact_type, record_id)
    comments.delete_pin(
        db, project=project, user=current_user, manager=comments.can_manage(resolver, artefact_type),
        artefact_type=artefact_type, record_id=record_id, pin_id=pin_id,
    )
    db.commit()
    return _thread_out(db, resolver, current_user, artefact_type, record_id)
