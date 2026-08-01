"""Module: schemas.notification — request/response models for notifications (Pelion v2, C-N-01..05)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.notification import NotificationType


class NotificationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    type: NotificationType
    title: str
    body: str
    project_id: UUID | None
    entity_type: str | None
    entity_id: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationPreferenceOut(BaseModel):
    type: NotificationType
    ui_enabled: bool
    email_enabled: bool


class NotificationPreferenceUpdate(BaseModel):
    ui_enabled: bool
    email_enabled: bool
