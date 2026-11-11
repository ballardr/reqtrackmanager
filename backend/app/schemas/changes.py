"""Module: schemas.changes — response model for the project changes-over-time view (C-A-10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class LinkedRecordOut(BaseModel):
    """One end of a link event; the identity fields stay empty when the viewer cannot open the record."""

    role: str
    """`source` (the end the relationship is read from) or `target`."""
    entity_type: str
    entity_type_label: str
    entity_id: UUID | None = None
    label: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    """The record's project, set only when the viewer can open it."""


class ChangeEntryOut(BaseModel):
    """One entry in the unified project change timeline."""

    timestamp: datetime
    entity_type: str
    entity_id: str
    action: str
    actor_id: UUID | None
    actor_display_name: str | None = None
    detail: dict[str, Any] | None = None
    kind: str = "other"
    """How the record changed (`services.activity_kinds`): created, edited, status, links, tags, access, comments, deleted or other."""
    record_label: str | None = None
    """The record's code and title when it is of a registered type the viewer may see (requirements and change requests carry theirs in `detail`)."""
    linked_records: list[LinkedRecordOut] = []
    """The two records a link event joins, source first (empty for any other event); `services.activity_link_ends`."""
    link_type_label: str | None = None
    """The relationship's forward name for a link event whose link type is known."""


class RecordActivityOut(BaseModel):
    """One page of a single record's activity timeline (newest first)."""

    entries: list[ChangeEntryOut]
    has_more: bool = False
