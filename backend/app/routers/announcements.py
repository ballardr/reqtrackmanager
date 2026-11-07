"""
Module: routers.announcements

Announcements (scheduled plain-text messages):
- `/api/v1/system/announcements`: server administrators manage platform-wide messages.
- `/api/v1/orgs/{id}/announcements`: organisation administrators manage that organisation's messages.
- `GET /api/v1/announcements/login`: public, rate-limited; active login-flagged messages for a login page.
- `GET /api/v1/announcements/active`: signed-in banner; server-wide plus the reader's organisation.

Authorisation: scope is enforced in `services.announcements` (a message of another scope is a 404). The public
read returns only the fields a reader needs (never the author or an organisation id).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, get_current_user
from app.models.announcement import Announcement
from app.models.enums import OrgRole
from app.models.user import User
from app.schemas.announcements import (
    AnnouncementIn,
    AnnouncementOut,
    AnnouncementReaderOut,
    AnnouncementSendOut,
    AnnouncementsOut,
)
from app.services import announcements as service
from app.services.announcements import Scope
from app.services.rbac import require_org_role, require_server_admin

system_router = APIRouter(prefix="/api/v1/system/announcements", tags=["announcements"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/announcements", tags=["announcements"])
reader_router = APIRouter(prefix="/api/v1/announcements", tags=["announcements"])

_org_admin = require_org_role(OrgRole.ORG_ADMIN)


def _out(row: Announcement, now: datetime) -> AnnouncementOut:
    """The administrator view of one message, with its status at `now`."""
    return AnnouncementOut(
        id=row.id, organization_id=row.organization_id, title=row.title, body=row.body, severity=row.severity,
        starts_at=row.starts_at, ends_at=row.ends_at, show_on_login=row.show_on_login, status=service.status_of(row, now),
        notified_at=row.notified_at, notified_count=row.notified_count, created_at=row.created_at, updated_at=row.updated_at,
    )


def _list(db: Session, organization_id: UUID | None) -> AnnouncementsOut:
    now = datetime.now(UTC)
    return AnnouncementsOut(items=[_out(r, now) for r in service.list_scope(db, organization_id)])


def _create(db: Session, organization_id: UUID | None, body: AnnouncementIn, actor: User) -> AnnouncementOut:
    row = service.create(
        db, organization_id=organization_id, actor=actor, title=body.title, body=body.body, severity=body.severity,
        starts_at=body.starts_at, ends_at=body.ends_at, show_on_login=body.show_on_login,
    )
    db.commit()
    return _out(row, datetime.now(UTC))


def _replace(db: Session, organization_id: UUID | None, announcement_id: UUID, body: AnnouncementIn, actor: User) -> AnnouncementOut:
    row = service.get_in_scope(db, announcement_id, organization_id)
    service.replace(
        db, row, actor=actor, title=body.title, body=body.body, severity=body.severity, starts_at=body.starts_at,
        ends_at=body.ends_at, show_on_login=body.show_on_login,
    )
    db.commit()
    return _out(row, datetime.now(UTC))


def _delete(db: Session, organization_id: UUID | None, announcement_id: UUID, actor: User) -> Response:
    service.delete(db, service.get_in_scope(db, announcement_id, organization_id), actor)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _send(db: Session, organization_id: UUID | None, announcement_id: UUID, actor: User) -> AnnouncementSendOut:
    row = service.send_notification(db, announcement_id, organization_id, actor)
    db.commit()
    assert row.notified_at is not None and row.notified_count is not None
    return AnnouncementSendOut(notified_count=row.notified_count, notified_at=row.notified_at)


# --- server-wide ----------------------------------------------------------------------------------------


@system_router.get("", response_model=AnnouncementsOut)
def list_server_announcements(current_user: User = Depends(require_server_admin), db: Session = Depends(get_db)) -> AnnouncementsOut:
    """The platform-wide messages."""
    return _list(db, None)


@system_router.post("", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED)
def create_server_announcement(
    body: AnnouncementIn, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> AnnouncementOut:
    """Creates a platform-wide message."""
    return _create(db, None, body, current_user)


@system_router.put("/{announcement_id}", response_model=AnnouncementOut)
def replace_server_announcement(
    announcement_id: UUID, body: AnnouncementIn, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> AnnouncementOut:
    """Replaces a platform-wide message's fields."""
    return _replace(db, None, announcement_id, body, current_user)


@system_router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server_announcement(
    announcement_id: UUID, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> Response:
    """Deletes a platform-wide message."""
    return _delete(db, None, announcement_id, current_user)


@system_router.post("/{announcement_id}/notify", response_model=AnnouncementSendOut)
def send_server_announcement(
    announcement_id: UUID, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> AnnouncementSendOut:
    """Sends a platform-wide message once as a notification to every active user."""
    return _send(db, None, announcement_id, current_user)


# --- organisation ---------------------------------------------------------------------------------------


@org_router.get("", response_model=AnnouncementsOut)
def list_org_announcements(
    organization_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> AnnouncementsOut:
    """The organisation's messages."""
    return _list(db, organization_id)


@org_router.post("", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED)
def create_org_announcement(
    organization_id: UUID, body: AnnouncementIn, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> AnnouncementOut:
    """Creates a message for the organisation."""
    return _create(db, organization_id, body, current_user)


@org_router.put("/{announcement_id}", response_model=AnnouncementOut)
def replace_org_announcement(
    organization_id: UUID, announcement_id: UUID, body: AnnouncementIn,
    current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> AnnouncementOut:
    """Replaces one of the organisation's messages."""
    return _replace(db, organization_id, announcement_id, body, current_user)


@org_router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_announcement(
    organization_id: UUID, announcement_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> Response:
    """Deletes one of the organisation's messages."""
    return _delete(db, organization_id, announcement_id, current_user)


@org_router.post("/{announcement_id}/notify", response_model=AnnouncementSendOut)
def send_org_announcement(
    organization_id: UUID, announcement_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> AnnouncementSendOut:
    """Sends one of the organisation's messages once as a notification to its active members."""
    return _send(db, organization_id, announcement_id, current_user)


# --- readers --------------------------------------------------------------------------------------------


def _reader_out(pairs: list[tuple[Announcement, Scope]]) -> list[AnnouncementReaderOut]:
    return [
        AnnouncementReaderOut(id=r.id, title=r.title, body=r.body, severity=r.severity, scope=scope)
        for r, scope in pairs
    ]


@reader_router.get("/login", response_model=list[AnnouncementReaderOut])
def get_login_announcements(
    organization_slug: str | None = Query(default=None, max_length=100),
    client_ip: str = Depends(get_client_ip), db: Session = Depends(get_db),
) -> list[AnnouncementReaderOut]:
    """Public: active messages flagged for the login pages (unauthenticated, rate-limited per address).

    With `organization_slug`, the organisation's own flagged messages are included; an unknown slug returns the
    server-wide messages only.
    """
    service.enforce_public_rate_limit(client_ip)
    return _reader_out(service.login_messages(db, organization_slug))


@reader_router.get("/active", response_model=list[AnnouncementReaderOut])
def get_active_announcements(
    organization_id: UUID | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> list[AnnouncementReaderOut]:
    """The banner messages for the signed-in person: server-wide, plus those of `organization_id` when they belong to it."""
    return _reader_out(service.banner_messages(db, current_user, organization_id))
