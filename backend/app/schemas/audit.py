"""
Module: schemas.audit

Read-only response model for `AuditEvent` (`app.models.audit`). Until now,
`AuditEvent` was write-only from the API's perspective — every router calls
`services.audit.log_event` to record a mutation, but nothing ever read one
back over HTTP. The Compliance Module's Phase 7 project-compliance-
assessment history endpoints (docs/compliance-module-plan.md Phase 7,
docs/Compliance_Module_Requirements.md §8/§11/§16 — "view compliance
history") are the first real caller, so this schema lives here, generically,
rather than under `app.modules.compliance`, so a future core or module
feature needing the same "show me this entity's own audit trail" shape
doesn't have to duplicate it.
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
