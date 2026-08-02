"""Module: schemas.changes — response model for the project changes-over-time view (C-A-10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ChangeEntryOut(BaseModel):
    """One entry in the unified project change timeline."""

    timestamp: datetime
    entity_type: str
    entity_id: str
    action: str
    actor_id: UUID | None
    actor_display_name: str | None = None
    detail: dict[str, Any] | None = None
