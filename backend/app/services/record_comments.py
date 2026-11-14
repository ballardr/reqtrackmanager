"""
Module: services.record_comments

The generic comments of records of any registered artefact type that opts in through
`ModuleDefinition.record_comments`: ordinary comments on a record and pinned threads on its drawing.

Responsibilities:
- Read a record's comments and pins together in a fixed number of statements (`read_thread`), with each author's
  display name and what the viewer may do with each row.
- Add a comment, a reply, or a comment that opens a new pin; edit one's own comment; delete a comment or a whole
  thread; resolve, reopen, move and re-anchor a pin; attach an existing ordinary comment to the drawing
  (`add_comment`, `edit_comment`, `delete_comment`, `delete_pin`, `update_pin`, `pin_comment`).
- Validate a pin's position and anchor against the type's provider (`check_pin`).
- Clear a record's comments when the record is deleted (`forget_record_comments`).

Design decisions:
- Reading and commenting follow the record's visibility (the caller passes a record already opened through
  `services.tags.require_visible_record`) and the project view right, as the module-local comments of Decisions and
  Strategies do. Editing a comment is the author only; deleting a comment, deleting a thread and moving a pin are the
  author (of the comment or of the pin) or a holder of `manage` on the record's type.
- Comments are saved at once and never under a record's version lock: they are review conversation about a record,
  not part of it.
- Every mutation is an audit event against the record carrying ids and counts only, never the text.
- A record owned by an organisation stores `organization_id` instead of `project_id`; the caller supplies which.

External dependencies: `models.record_comment`, `models.user`, `services.audit`, `modules.registry` (providers).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.record_comment import PIN_ANCHOR_KINDS, RecordComment, RecordCommentPin
from app.models.user import User
from app.modules.registry import RecordCommentProvider, get_record_comment_providers
from app.services.audit import log_event
from app.services.link_graph import ArtefactResolver

#: Most comments one record may hold, a guard against a runaway client rather than a working limit.
MAX_COMMENTS_PER_RECORD = 5000
#: Longest comment body.
MAX_COMMENT_LENGTH = 5000
#: Longest anchor key (the column's width).
MAX_ANCHOR_KEY_LENGTH = 80


@dataclass(frozen=True)
class PinSpec:
    """Where a pin sits: a free spot (`none`) or a box or line of the drawing (`node`, `edge`) and its position."""

    anchor_kind: str
    anchor_key: str | None
    x: float
    y: float


@dataclass(frozen=True)
class CommentRow:
    """A comment with its author's name and what the viewer may do with it."""

    comment: RecordComment
    author_display_name: str
    can_edit: bool
    can_delete: bool


@dataclass(frozen=True)
class PinRow:
    """A pin with the number of comments in its thread, the resolver's name and what the viewer may do with it."""

    pin: RecordCommentPin
    comment_count: int
    resolved_by_display_name: str | None
    can_move: bool
    can_delete: bool


@dataclass(frozen=True)
class Thread:
    """Everything the comments of one record hold: the comments in order and the pins."""

    comments: list[CommentRow]
    pins: list[PinRow]


def provider_or_404(artefact_type: str) -> RecordCommentProvider:
    """The provider of a type that has generic comments.

    Raises:
        HTTPException: 404 when the type has none (unregistered, or its comments are its own tables)."""
    provider = get_record_comment_providers().get(artefact_type)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    return provider


def can_manage(resolver: ArtefactResolver, artefact_type: str) -> bool:
    """Whether the user holds `manage` on the type in the request project (deleting another person's comment or
    moving their pin)."""
    return resolver.holds(artefact_type, "manage")


def _owner(project: Project, owner_project_id: uuid.UUID | None) -> dict[str, uuid.UUID | None]:
    """The owner columns for a record: its project, or the organisation for an organisation-owned record."""
    if owner_project_id is None:
        return {"project_id": None, "organization_id": project.organization_id}
    return {"project_id": owner_project_id, "organization_id": None}


def check_pin(
    db: Session, provider: RecordCommentProvider, project: Project, record_id: uuid.UUID, spec: PinSpec,
) -> None:
    """Validates a pin's position and anchor.

    Raises:
        HTTPException: 422 for a non-finite position, an anchor kind the type does not offer, a key on a free pin or no
            key on an anchored one, a key longer than the column, or a key the provider does not recognise."""
    if not (math.isfinite(spec.x) and math.isfinite(spec.y)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A comment position must be a finite number.")
    if spec.anchor_kind not in PIN_ANCHOR_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown comment anchor.")
    if spec.anchor_kind == "none":
        if spec.anchor_key is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A free comment has no anchor key.")
        return
    key = spec.anchor_key
    if spec.anchor_kind not in provider.anchor_kinds:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This record cannot anchor a comment there.")
    if not key or len(key) > MAX_ANCHOR_KEY_LENGTH:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A comment anchor needs a key.")
    if provider.validate_anchor is None or not provider.validate_anchor(db, project.id, record_id, spec.anchor_kind, key):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That item is not on this record.")


def _allows_pins(provider: RecordCommentProvider) -> bool:
    """Whether the type's records have a drawing a comment can be pinned on."""
    return bool(provider.anchor_kinds)


def read_thread(
    db: Session, artefact_type: str, record_id: uuid.UUID, *, viewer_id: uuid.UUID, manager: bool,
) -> Thread:
    """The record's comments and pins with names and the viewer's rights, in three statements however many rows.

    Args:
        db: Active session (read only).
        artefact_type: The commented type.
        record_id: The commented record (already opened by the caller).
        viewer_id: The user reading; decides `can_edit`, `can_delete` and `can_move`.
        manager: Whether the viewer holds `manage` on the type (`can_manage`)."""
    comments = list(
        db.scalars(
            select(RecordComment)
            .where(RecordComment.artefact_type == artefact_type, RecordComment.record_id == record_id)
            .order_by(RecordComment.created_at, RecordComment.id)
        ).all()
    )
    pins = list(
        db.scalars(
            select(RecordCommentPin)
            .where(RecordCommentPin.artefact_type == artefact_type, RecordCommentPin.record_id == record_id)
            .order_by(RecordCommentPin.created_at, RecordCommentPin.id)
        ).all()
    )
    user_ids = {c.author_id for c in comments if c.author_id} | {p.resolved_by for p in pins if p.resolved_by}
    names = (
        {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    )
    counts: dict[uuid.UUID, int] = {}
    for comment in comments:
        if comment.pin_id is not None:
            counts[comment.pin_id] = counts.get(comment.pin_id, 0) + 1
    return Thread(
        comments=[
            CommentRow(
                comment=c,
                author_display_name=names.get(c.author_id, "Unknown user") if c.author_id else "Unknown user",
                can_edit=c.author_id == viewer_id,
                can_delete=manager or c.author_id == viewer_id,
            )
            for c in comments
        ],
        pins=[
            PinRow(
                pin=p, comment_count=counts.get(p.id, 0),
                resolved_by_display_name=names.get(p.resolved_by) if p.resolved_by else None,
                can_move=manager or p.created_by == viewer_id, can_delete=manager or p.created_by == viewer_id,
            )
            for p in pins
        ],
    )


def _audit(
    db: Session, project: Project, actor_id: uuid.UUID, artefact_type: str, record_id: uuid.UUID, action: str,
    detail: dict[str, str | int | bool],
) -> None:
    """Writes one audit event against the record: ids and counts, never the comment text."""
    log_event(
        db, entity_type=artefact_type, entity_id=record_id, action=action, actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id, detail=detail,
    )


def _pin_in(db: Session, artefact_type: str, record_id: uuid.UUID, pin_id: uuid.UUID) -> RecordCommentPin:
    """The pin of this record (404 for another record's, so ids never cross records)."""
    pin = db.get(RecordCommentPin, pin_id)
    if pin is None or pin.artefact_type != artefact_type or pin.record_id != record_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment thread not found.")
    return pin


def _comment_in(db: Session, artefact_type: str, record_id: uuid.UUID, comment_id: uuid.UUID) -> RecordComment:
    """The comment of this record (404 for another record's)."""
    comment = db.get(RecordComment, comment_id)
    if comment is None or comment.artefact_type != artefact_type or comment.record_id != record_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    return comment


def add_comment(
    db: Session, *, project: Project, owner_project_id: uuid.UUID | None, user: User, artefact_type: str,
    record_id: uuid.UUID, body: str, pin_id: uuid.UUID | None = None, new_pin: PinSpec | None = None,
) -> RecordComment:
    """Adds a comment: an ordinary one, a reply in an existing thread (`pin_id`), or the first of a new pin
    (`new_pin`). The caller commits.

    Raises:
        HTTPException: 404 for an unknown thread; 422 when both a thread and a new pin are given, the type has no
            drawing, the pin is invalid (`check_pin`) or the record already holds `MAX_COMMENTS_PER_RECORD`."""
    provider = provider_or_404(artefact_type)
    if pin_id is not None and new_pin is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Reply to a thread or start one, not both.")
    total = db.scalar(
        select(func.count()).select_from(RecordComment)
        .where(RecordComment.artefact_type == artefact_type, RecordComment.record_id == record_id)
    ) or 0
    if total >= MAX_COMMENTS_PER_RECORD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This record has reached its comment limit.")
    owner = _owner(project, owner_project_id)
    pin: RecordCommentPin | None = None
    if pin_id is not None:
        pin = _pin_in(db, artefact_type, record_id, pin_id)
    elif new_pin is not None:
        if not _allows_pins(provider):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This record has no drawing to comment on.")
        check_pin(db, provider, project, record_id, new_pin)
        pin = RecordCommentPin(
            **owner, artefact_type=artefact_type, record_id=record_id, anchor_kind=new_pin.anchor_kind,
            anchor_key=new_pin.anchor_key, x=new_pin.x, y=new_pin.y, created_by=user.id,
        )
        db.add(pin)
        db.flush()
    comment = RecordComment(
        **owner, artefact_type=artefact_type, record_id=record_id, pin_id=pin.id if pin else None,
        author_id=user.id, body=body,
    )
    db.add(comment)
    db.flush()
    _audit(db, project, user.id, artefact_type, record_id, "comment_added", {
        "comment_id": str(comment.id), "pinned": pin is not None, "reply": pin_id is not None,
    })
    return comment


def edit_comment(
    db: Session, *, project: Project, user: User, artefact_type: str, record_id: uuid.UUID, comment_id: uuid.UUID,
    body: str,
) -> RecordComment:
    """Replaces the body of the user's own comment. The caller commits.

    Raises:
        HTTPException: 404 for an unknown comment, 403 when someone else wrote it."""
    provider_or_404(artefact_type)
    comment = _comment_in(db, artefact_type, record_id, comment_id)
    if comment.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = body
    comment.edited_at = datetime.now(UTC)
    _audit(db, project, user.id, artefact_type, record_id, "comment_edited", {"comment_id": str(comment.id)})
    return comment


def delete_comment(
    db: Session, *, project: Project, user: User, manager: bool, artefact_type: str, record_id: uuid.UUID,
    comment_id: uuid.UUID,
) -> None:
    """Deletes a comment (its author or a manager); the last comment of a thread takes the pin with it. The caller
    commits.

    Raises:
        HTTPException: 404 for an unknown comment, 403 for another person's comment without `manage`."""
    provider_or_404(artefact_type)
    comment = _comment_in(db, artefact_type, record_id, comment_id)
    if not (manager or comment.author_id == user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author or a manager may delete it.")
    pin_id = comment.pin_id
    db.delete(comment)
    db.flush()
    emptied = False
    if pin_id is not None and not db.scalar(select(func.count()).select_from(RecordComment).where(RecordComment.pin_id == pin_id)):
        db.execute(delete(RecordCommentPin).where(RecordCommentPin.id == pin_id))
        emptied = True
    _audit(db, project, user.id, artefact_type, record_id, "comment_deleted", {
        "comment_id": str(comment_id), "thread_removed": emptied,
    })


def delete_pin(
    db: Session, *, project: Project, user: User, manager: bool, artefact_type: str, record_id: uuid.UUID,
    pin_id: uuid.UUID,
) -> None:
    """Deletes a whole pinned thread (the pin's creator or a manager). The caller commits.

    Raises:
        HTTPException: 404 for an unknown thread, 403 for someone else's thread without `manage`."""
    provider_or_404(artefact_type)
    pin = _pin_in(db, artefact_type, record_id, pin_id)
    if not (manager or pin.created_by == user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the thread's author or a manager may delete it.")
    removed = db.scalar(select(func.count()).select_from(RecordComment).where(RecordComment.pin_id == pin_id)) or 0
    db.delete(pin)
    _audit(db, project, user.id, artefact_type, record_id, "comment_thread_deleted", {
        "pin_id": str(pin_id), "comments": removed,
    })


def update_pin(
    db: Session, *, project: Project, user: User, manager: bool, artefact_type: str, record_id: uuid.UUID,
    pin_id: uuid.UUID, spec: PinSpec | None = None, resolved: bool | None = None,
) -> RecordCommentPin:
    """Moves or re-anchors a pin (its creator or a manager) and/or resolves or reopens its thread (anyone who can
    comment). The caller commits.

    Raises:
        HTTPException: 404 for an unknown thread; 403 when moving someone else's pin without `manage`; 422 for an
            invalid position or anchor."""
    provider = provider_or_404(artefact_type)
    pin = _pin_in(db, artefact_type, record_id, pin_id)
    if spec is not None:
        if not (manager or pin.created_by == user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the thread's author or a manager may move it.")
        check_pin(db, provider, project, record_id, spec)
        pin.anchor_kind, pin.anchor_key, pin.x, pin.y = spec.anchor_kind, spec.anchor_key, spec.x, spec.y
        _audit(db, project, user.id, artefact_type, record_id, "comment_pin_moved", {
            "pin_id": str(pin.id), "anchor_kind": spec.anchor_kind,
        })
    if resolved is not None and resolved != (pin.resolved_at is not None):
        pin.resolved_at = datetime.now(UTC) if resolved else None
        pin.resolved_by = user.id if resolved else None
        _audit(db, project, user.id, artefact_type, record_id,
               "comment_thread_resolved" if resolved else "comment_thread_reopened", {"pin_id": str(pin.id)})
    return pin


def pin_comment(
    db: Session, *, project: Project, owner_project_id: uuid.UUID | None, user: User, manager: bool,
    artefact_type: str, record_id: uuid.UUID, comment_id: uuid.UUID, spec: PinSpec,
) -> RecordCommentPin:
    """Places an ordinary comment on the drawing (its author or a manager), opening a thread of one. The caller
    commits.

    Raises:
        HTTPException: 404 for an unknown comment; 403 for another person's comment without `manage`; 422 when the
            comment is already in a thread, the type has no drawing or the pin is invalid."""
    provider = provider_or_404(artefact_type)
    comment = _comment_in(db, artefact_type, record_id, comment_id)
    if not (manager or comment.author_id == user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author or a manager may pin it.")
    if comment.pin_id is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That comment is already on the drawing.")
    if not _allows_pins(provider):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This record has no drawing to comment on.")
    check_pin(db, provider, project, record_id, spec)
    pin = RecordCommentPin(
        **_owner(project, owner_project_id), artefact_type=artefact_type, record_id=record_id,
        anchor_kind=spec.anchor_kind, anchor_key=spec.anchor_key, x=spec.x, y=spec.y, created_by=comment.author_id,
    )
    db.add(pin)
    db.flush()
    comment.pin_id = pin.id
    _audit(db, project, user.id, artefact_type, record_id, "comment_pinned", {
        "comment_id": str(comment.id), "pin_id": str(pin.id),
    })
    return pin


@dataclass(frozen=True)
class AnchoredThread:
    """A pinned thread on another record's drawing that is anchored to a box or line: the record it sits on (named by
    the record's own label), the pin and its comments in order."""

    record_type: str
    record_id: uuid.UUID
    record_label: str
    pin: PinRow
    comments: list[CommentRow]


def anchored_threads(
    db: Session, resolver: ArtefactResolver, project: Project, record_id: uuid.UUID, *, viewer_id: uuid.UUID,
) -> list[AnchoredThread]:
    """The pinned threads, across drawings of the project, anchored to a box or line that is `record_id` (a thread on a
    drawing the viewer cannot open is left out). Read in a fixed number of statements, the drawings' labels through
    the resolver.

    Args:
        db: Active session (read only).
        resolver: The viewer's resolver for `project` (decides which drawings they may open).
        project: The request project; only its drawings are read.
        record_id: The element or connection the pins are anchored to.
        viewer_id: The user reading; decides each comment's rights (always read-only here, so they are false).
    """
    pins = list(db.scalars(
        select(RecordCommentPin)
        .where(
            RecordCommentPin.project_id == project.id, RecordCommentPin.anchor_key == str(record_id),
            RecordCommentPin.anchor_kind != "none", RecordCommentPin.artefact_type.in_(list(get_record_comment_providers())),
        )
        .order_by(RecordCommentPin.created_at, RecordCommentPin.id)
    ))
    if not pins:
        return []
    by_type: dict[str, set[uuid.UUID]] = {}
    for pin in pins:
        by_type.setdefault(pin.artefact_type, set()).add(pin.record_id)
    resolver.resolve(by_type)
    pins = [p for p in pins if resolver.visible((p.artefact_type, p.record_id)) is not None]
    if not pins:
        return []
    comments = list(db.scalars(
        select(RecordComment).where(RecordComment.pin_id.in_([p.id for p in pins]))
        .order_by(RecordComment.created_at, RecordComment.id)
    ))
    user_ids = {c.author_id for c in comments if c.author_id} | {p.resolved_by for p in pins if p.resolved_by}
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    rows: dict[uuid.UUID, list[CommentRow]] = {}
    for comment in comments:
        assert comment.pin_id is not None
        rows.setdefault(comment.pin_id, []).append(CommentRow(
            comment=comment, author_display_name=names.get(comment.author_id, "Unknown user") if comment.author_id else "Unknown user",
            can_edit=False, can_delete=False,
        ))
    out: list[AnchoredThread] = []
    for pin in pins:
        summary = resolver.visible((pin.artefact_type, pin.record_id))
        assert summary is not None
        out.append(AnchoredThread(
            record_type=pin.artefact_type, record_id=pin.record_id, record_label=summary.label,
            pin=PinRow(
                pin=pin, comment_count=len(rows.get(pin.id, ())),
                resolved_by_display_name=names.get(pin.resolved_by) if pin.resolved_by else None,
                can_move=False, can_delete=False,
            ),
            comments=rows.get(pin.id, []),
        ))
    return out


def forget_record_comments(db: Session, artefact_type: str, record_id: uuid.UUID) -> None:
    """Removes every comment and pin of a record being deleted (no foreign key reaches a record, so a delete path
    calls this beside `forget_record_placements`). Does not commit."""
    db.execute(delete(RecordComment).where(RecordComment.artefact_type == artefact_type, RecordComment.record_id == record_id))
    db.execute(
        delete(RecordCommentPin).where(RecordCommentPin.artefact_type == artefact_type, RecordCommentPin.record_id == record_id)
    )
