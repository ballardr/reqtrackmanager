"""
Module: schemas.announcements

Request and response shapes for announcements (`routers.announcements`).

The public and banner shapes carry only what a reader needs; neither returns the author, the owning
organisation's id or any send bookkeeping.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.announcement import AnnouncementSeverity
from app.services.announcements import MAX_BODY_LENGTH, MAX_TITLE_LENGTH, Scope, Status


class AnnouncementIn(BaseModel):
    """The editable fields of an announcement (create and replace).

    Attributes:
        title: Heading, plain text, one line.
        body: Message, plain text.
        severity: Presentation level.
        starts_at: First active instant (timezone-aware), `None` for already active.
        ends_at: First instant no longer active (timezone-aware), `None` for no end.
        show_on_login: Whether the login pages show it.
    """

    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    body: str = Field(default="", max_length=MAX_BODY_LENGTH)
    severity: AnnouncementSeverity = AnnouncementSeverity.INFORMATION
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    show_on_login: bool = False


class AnnouncementOut(BaseModel):
    """An announcement as its administrators see it.

    Attributes:
        status: `scheduled` (not yet started), `active` or `ended`, resolved on the server's clock.
        notified_at / notified_count: Set once the message has been sent as a notification.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None
    title: str
    body: str
    severity: AnnouncementSeverity
    starts_at: datetime | None
    ends_at: datetime | None
    show_on_login: bool
    status: Status
    notified_at: datetime | None
    notified_count: int | None
    created_at: datetime
    updated_at: datetime


class AnnouncementsOut(BaseModel):
    """The announcements of one scope, newest first."""

    items: list[AnnouncementOut]


class AnnouncementReaderOut(BaseModel):
    """An active announcement as a reader sees it (login page or banner).

    Attributes:
        scope: `server` for a platform-wide message, `organisation` for the reader's organisation.
    """

    id: UUID
    title: str
    body: str
    severity: AnnouncementSeverity
    scope: Scope


class AnnouncementSendOut(BaseModel):
    """The result of sending an announcement as a notification."""

    notified_count: int
    notified_at: datetime
