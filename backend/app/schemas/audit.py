"""
Module: schemas.audit

Read-only response model for `AuditEvent` (`app.models.audit`), for endpoints that show an entity's own audit
trail (e.g. the Compliance Module's project-compliance-assessment history). It lives here, not under
`app.modules.compliance`, so any core or module feature needing that shape reuses it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    entity_type: str
    entity_id: str
    action: str
    actor_id: UUID | None
    detail: dict[str, Any] | None
    created_at: datetime
