"""Module: schemas.notification — request/response models for notifications (Pelion v2, C-N-01..05)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationOut(BaseModel):
    """A notification. `target_kinds` says where opening it leads (ordered, the first kind whose data it carries
    wins; the browser resolves them in `modules/notificationTargets.ts`)."""

    model_config = {"from_attributes": True}

    id: UUID
    type: str
    title: str
    body: str
    project_id: UUID | None
    entity_type: str | None
    entity_id: str | None
    created_at: datetime
    read_at: datetime | None

    target_kinds: list[str] = []


class NotificationDetailOut(NotificationOut):
    """One notification with whether its subject is still reachable by the recipient (`subject_available`)."""

    subject_available: bool = True


class NotificationPreferenceOut(BaseModel):
    """Effective delivery preference for one notification type. `label` is set
    for a module-declared type (core types are labelled by the frontend)."""

    type: str
    label: str | None = None
    ui_enabled: bool
    email_enabled: bool


class NotificationPreferenceUpdate(BaseModel):
    ui_enabled: bool
    email_enabled: bool
