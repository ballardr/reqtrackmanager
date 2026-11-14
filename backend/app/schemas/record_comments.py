"""
Module: schemas.record_comments

Request and response models for the generic record comments API (`routers.record_comments`): ordinary comments on a
record and pinned threads on its drawing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.record_comments import MAX_ANCHOR_KEY_LENGTH, MAX_COMMENT_LENGTH

AnchorKind = Literal["none", "node", "edge"]


def _clean_body(value: str) -> str:
    """Trims a comment body and refuses an empty one."""
    value = value.strip()
    if not value:
        raise ValueError("A comment cannot be empty.")
    return value


class PinIn(BaseModel):
    """Where a pin sits: a free spot (`none`, no key) or a box or line (`node`, `edge`, with its key)."""

    anchor_kind: AnchorKind = "none"
    anchor_key: str | None = Field(None, max_length=MAX_ANCHOR_KEY_LENGTH)
    x: float
    y: float


class CommentCreate(BaseModel):
    """A new comment: ordinary (neither field), a reply (`pin_id`) or the first of a new pin (`pin`)."""

    body: str = Field(max_length=MAX_COMMENT_LENGTH)
    pin_id: uuid.UUID | None = None
    pin: PinIn | None = None

    _body = field_validator("body")(_clean_body)


class CommentUpdate(BaseModel):
    """The new body of one's own comment."""

    body: str = Field(max_length=MAX_COMMENT_LENGTH)

    _body = field_validator("body")(_clean_body)


class PinUpdate(BaseModel):
    """A pin change: a new position or anchor (`pin`), and/or `resolved` true or false; absent fields are unchanged."""

    pin: PinIn | None = None
    resolved: bool | None = None


class CommentPinRequest(BaseModel):
    """Places an existing ordinary comment on the drawing."""

    pin: PinIn


class RecordCommentOut(BaseModel):
    """One comment with its author's name and what the viewer may do with it."""

    id: uuid.UUID
    pin_id: uuid.UUID | None
    author_id: uuid.UUID | None
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None
    can_edit: bool
    can_delete: bool


class RecordCommentPinOut(BaseModel):
    """One pinned thread: its place, its state and what the viewer may do with it."""

    id: uuid.UUID
    anchor_kind: str
    anchor_key: str | None
    x: float
    y: float
    comment_count: int
    resolved: bool
    resolved_at: datetime | None
    resolved_by_display_name: str | None
    can_move: bool
    can_delete: bool


class RecordThreadOut(BaseModel):
    """Everything a record's comments hold, and whether the viewer may place pins at all."""

    comments: list[RecordCommentOut]
    pins: list[RecordCommentPinOut]
    can_pin: bool = Field(description="True when the record has a drawing a comment can be pinned on.")
    can_manage: bool = Field(description="True when the viewer may delete others' comments and move their pins.")


class AnchoredThreadOut(BaseModel):
    """A pinned thread on another record's drawing that is anchored to this record, for reading only."""

    record_type: str
    record_id: uuid.UUID
    record_label: str
    pin: RecordCommentPinOut
    comments: list[RecordCommentOut]


class AnchoredThreadsOut(BaseModel):
    """The pinned threads on drawings of the project that are anchored to a record."""

    threads: list[AnchoredThreadOut]
