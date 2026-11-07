"""
Module: services.announcements

Announcements: scheduled plain-text messages for the whole platform (written by server administrators) or for
one organisation (written by its administrators), shown on the login pages and as a banner after sign-in, with
an optional one-time send as a notification.

Responsibilities:
- Validate text and the active window; create, replace and delete a message in one scope, audited.
- Resolve which messages a reader sees: login pages (active, flagged for login), banner (active, server-wide
  plus the reader's organisation).
- Send a message once as a `SYSTEM_ANNOUNCEMENT` notification to its audience.
- Throttle the unauthenticated login-page read per client address.

Design decisions:
- Scope is enforced here, not by the caller: every lookup takes the owning `organization_id` (NULL for
  server-wide), so an organisation administrator can neither read nor change another organisation's message or
  a server-wide one (a mismatch is a 404, not a 403, so ids of other tenants are not confirmed).
- Text is stored and shown as plain text (no links or markup). Because organisation administrators are lower
  trust than the server administrator and the login page is the highest phishing risk, an organisation message
  may not contain a web address; a server-wide message may.
- Audit events carry the severity, flags and window, never the title or body; the send event carries counts.
- The send is idempotent: the row is locked and `notified_at` set in the same transaction as the fan-out.
- Fan-out is synchronous in the request and uses the ordinary `notify`, so preferences and digest mode apply;
  the sender is excluded (`actor_id`).
- Window edges are UTC instants; "active" is `starts_at <= now < ends_at`, each edge optional.

External dependencies: `services.notifications`, `services.audit`, `services.rate_limit`.
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, case, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.announcement import Announcement, AnnouncementSeverity
from app.models.notification import NotificationType
from app.models.organization import Organization, UserOrgRole
from app.models.user import User
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings
from app.services.notifications import notify
from app.services.rate_limit import RateLimiter

Scope = Literal["server", "organisation"]
Status = Literal["scheduled", "active", "ended"]

MAX_TITLE_LENGTH = 120
MAX_BODY_LENGTH = 1000
#: Most messages one scope may hold, so the banner and login page stay readable and a loop cannot fill the table.
MAX_PER_SCOPE = 50

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WEB_ADDRESS = re.compile(r"(?i)(?:https?:|ftp:|www\.)")
_SEVERITY_ORDER = case(
    (Announcement.severity == AnnouncementSeverity.CRITICAL, 0),
    (Announcement.severity == AnnouncementSeverity.WARNING, 1),
    else_=2,
)


def clean_text(title: str, body: str, *, organization_scope: bool) -> tuple[str, str]:
    """Normalises a title and body to plain text.

    Args:
        title: Heading; whitespace (including line breaks) collapses to single spaces.
        body: Message; control characters are removed, line breaks kept, outer blank space trimmed.
        organization_scope: True for an organisation's message, which may not contain a web address.

    Returns:
        The cleaned `(title, body)`.

    Raises:
        HTTPException: 422 when the title is empty after cleaning or an organisation message contains a web address.
    """
    clean_title = " ".join(_CONTROL.sub("", title).split())
    clean_body = _CONTROL.sub("", body).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean_title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A title is required.")
    if organization_scope and (_WEB_ADDRESS.search(clean_title) or _WEB_ADDRESS.search(clean_body)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "An organisation message cannot contain a web address.",
        )
    return clean_title, clean_body


def status_of(announcement: Announcement, now: datetime) -> Status:
    """`scheduled`, `active` or `ended` at `now`."""
    if announcement.starts_at is not None and announcement.starts_at > now:
        return "scheduled"
    if announcement.ends_at is not None and announcement.ends_at <= now:
        return "ended"
    return "active"


def _active(now: datetime) -> ColumnElement[bool]:
    return and_(
        or_(Announcement.starts_at.is_(None), Announcement.starts_at <= now),
        or_(Announcement.ends_at.is_(None), Announcement.ends_at > now),
    )


def _scope(organization_id: uuid.UUID | None) -> ColumnElement[bool]:
    return Announcement.organization_id.is_(None) if organization_id is None else Announcement.organization_id == organization_id


def list_scope(db: Session, organization_id: uuid.UUID | None) -> list[Announcement]:
    """Every message of one scope (server-wide when `organization_id` is None), newest first."""
    return list(db.scalars(select(Announcement).where(_scope(organization_id)).order_by(Announcement.created_at.desc())).all())


def get_in_scope(db: Session, announcement_id: uuid.UUID, organization_id: uuid.UUID | None, *, lock: bool = False) -> Announcement:
    """The message with this id in this scope.

    Raises:
        HTTPException: 404 when it does not exist or belongs to another scope.
    """
    query = select(Announcement).where(Announcement.id == announcement_id, _scope(organization_id))
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found.")
    return row


def _check_window(starts_at: datetime | None, ends_at: datetime | None) -> None:
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The end must be after the start.")


def create(
    db: Session, *, organization_id: uuid.UUID | None, actor: User, title: str, body: str, severity: AnnouncementSeverity,
    starts_at: datetime | None, ends_at: datetime | None, show_on_login: bool,
) -> Announcement:
    """Creates a message in one scope; audited, not committed.

    Raises:
        HTTPException: 422 for invalid text or window; 409 when the scope already holds `MAX_PER_SCOPE` messages.
    """
    clean_title, clean_body = clean_text(title, body, organization_scope=organization_id is not None)
    _check_window(starts_at, ends_at)
    if len(list_scope(db, organization_id)) >= MAX_PER_SCOPE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"At most {MAX_PER_SCOPE} announcements can be kept; delete an old one first.")
    row = Announcement(
        organization_id=organization_id, title=clean_title, body=clean_body, severity=severity, starts_at=starts_at,
        ends_at=ends_at, show_on_login=show_on_login, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    log_event(
        db, entity_type="announcement", entity_id=row.id, action="created", actor_id=actor.id, organization_id=organization_id,
        detail=_audit_detail(row),
    )
    return row


def replace(
    db: Session, row: Announcement, *, actor: User, title: str, body: str, severity: AnnouncementSeverity,
    starts_at: datetime | None, ends_at: datetime | None, show_on_login: bool,
) -> Announcement:
    """Replaces the editable fields of a message; audited, not committed.

    Raises:
        HTTPException: 422 for invalid text or window.
    """
    clean_title, clean_body = clean_text(title, body, organization_scope=row.organization_id is not None)
    _check_window(starts_at, ends_at)
    row.title, row.body, row.severity = clean_title, clean_body, severity
    row.starts_at, row.ends_at, row.show_on_login = starts_at, ends_at, show_on_login
    db.flush()
    log_event(
        db, entity_type="announcement", entity_id=row.id, action="updated", actor_id=actor.id,
        organization_id=row.organization_id, detail=_audit_detail(row),
    )
    return row


def delete(db: Session, row: Announcement, actor: User) -> None:
    """Deletes a message; audited, not committed."""
    log_event(
        db, entity_type="announcement", entity_id=row.id, action="deleted", actor_id=actor.id,
        organization_id=row.organization_id, detail=_audit_detail(row),
    )
    db.delete(row)


def _audit_detail(row: Announcement) -> dict[str, object]:
    """Fields safe to record: never the title or body."""
    return {
        "severity": row.severity.value, "show_on_login": row.show_on_login,
        "starts_at": row.starts_at.isoformat() if row.starts_at else None,
        "ends_at": row.ends_at.isoformat() if row.ends_at else None,
    }


def _scope_of(row: Announcement) -> Scope:
    return "server" if row.organization_id is None else "organisation"


def login_messages(db: Session, organization_slug: str | None, now: datetime | None = None) -> list[tuple[Announcement, Scope]]:
    """The active, login-flagged messages for a login page.

    Args:
        db: Session.
        organization_slug: The branded page's organisation slug, or None for the plain login page. An unknown
            slug yields the server-wide messages only, so the response does not reveal whether a slug exists.
        now: The instant to evaluate at (defaults to the current time).

    Returns:
        `(message, scope)` pairs, most severe first then newest.
    """
    now = now or datetime.now(UTC)
    org_id = db.scalar(select(Organization.id).where(Organization.slug == organization_slug)) if organization_slug else None
    owner: ColumnElement[bool] = Announcement.organization_id.is_(None) if org_id is None else or_(
        Announcement.organization_id.is_(None), Announcement.organization_id == org_id
    )
    rows = db.scalars(
        select(Announcement)
        .where(owner, Announcement.show_on_login.is_(True), _active(now))
        .order_by(_SEVERITY_ORDER, Announcement.created_at.desc())
    ).all()
    return [(r, _scope_of(r)) for r in rows]


def banner_messages(db: Session, user: User, organization_id: uuid.UUID | None, now: datetime | None = None) -> list[tuple[Announcement, Scope]]:
    """The active messages for the banner: server-wide, plus those of `organization_id` when the user belongs to it.

    A `organization_id` the user does not belong to is ignored (server-wide messages only), never an error.
    """
    now = now or datetime.now(UTC)
    owner: ColumnElement[bool] = Announcement.organization_id.is_(None)
    if organization_id is not None and db.scalar(
        select(UserOrgRole.id).where(UserOrgRole.user_id == user.id, UserOrgRole.organization_id == organization_id).limit(1)
    ):
        owner = or_(owner, Announcement.organization_id == organization_id)
    rows = db.scalars(
        select(Announcement).where(owner, _active(now)).order_by(_SEVERITY_ORDER, Announcement.created_at.desc())
    ).all()
    return [(r, _scope_of(r)) for r in rows]


def recipients(db: Session, organization_id: uuid.UUID | None) -> list[User]:
    """The active, non-archived people a message reaches: everyone (server-wide) or the organisation's members."""
    query = select(User).where(User.is_active.is_(True), User.is_archived.is_(False))
    if organization_id is not None:
        member_ids = select(UserOrgRole.user_id).where(UserOrgRole.organization_id == organization_id)
        query = query.where(User.id.in_(member_ids))
    return list(db.scalars(query).all())


def send_notification(db: Session, announcement_id: uuid.UUID, organization_id: uuid.UUID | None, actor: User) -> Announcement:
    """Sends a message once as a notification to its audience; audited with counts, not committed.

    Args:
        db: Session.
        announcement_id: The message.
        organization_id: The caller's scope (None for server-wide).
        actor: The sender, who is not notified of their own send.

    Returns:
        The message with `notified_at` and `notified_count` set.

    Raises:
        HTTPException: 404 outside the scope; 409 when already sent or when the message has ended.
    """
    row = get_in_scope(db, announcement_id, organization_id, lock=True)
    now = datetime.now(UTC)
    if row.notified_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This announcement has already been sent as a notification.")
    if status_of(row, now) == "ended":
        raise HTTPException(status.HTTP_409_CONFLICT, "This announcement has ended and cannot be sent.")
    count = 0
    for person in recipients(db, organization_id):
        sent = notify(
            db, person, notification_type=NotificationType.SYSTEM_ANNOUNCEMENT, title=row.title, body=row.body,
            entity_type="announcement", entity_id=str(row.id), actor_id=actor.id,
        )
        count += 1 if sent is not None else 0
    row.notified_at, row.notified_count = now, count
    log_event(
        db, entity_type="announcement", entity_id=row.id, action="notified", actor_id=actor.id, organization_id=organization_id,
        detail={"recipient_count": count, "scope": "server" if organization_id is None else "organisation"},
    )
    return row


# --- organisation bundle --------------------------------------------------------------------------------

BUNDLE_KEY = "announcements"


def export_org(db: Session, organization_id: uuid.UUID) -> dict[str, list[dict[str, object]]]:
    """The organisation's messages as an `org.json` section.

    The send record (`notified_at`, `notified_count`) and the author are not carried: a send happened in the
    source deployment and an import must not mark a message as sent there. Server-wide messages are a
    deployment setting and are never part of a bundle.
    """
    return {BUNDLE_KEY: [
        {
            "title": r.title, "body": r.body, "severity": r.severity.value, "show_on_login": r.show_on_login,
            "starts_at": r.starts_at.isoformat() if r.starts_at else None,
            "ends_at": r.ends_at.isoformat() if r.ends_at else None,
        }
        for r in sorted(list_scope(db, organization_id), key=lambda a: a.created_at)
    ]}


def _instant(value: object) -> datetime | None:
    """An ISO 8601 instant with an offset, or None when absent or without one (a bare local time is ambiguous)."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def import_org(db: Session, organization_id: uuid.UUID, data: dict[str, object], actor: User, warnings: BundleImportWarnings) -> None:
    """Adds the bundle's messages to an organisation, skipping one with the same title and body already there.

    An entry that is malformed or fails the text rules (including a web address) is skipped with a warning; the
    rest are imported, never marked as sent.
    """
    raw = data.get(BUNDLE_KEY)
    existing = {(r.title, r.body) for r in list_scope(db, organization_id)}
    held = len(existing)
    for entry in raw if isinstance(raw, list) else []:
        try:
            if not isinstance(entry, dict):
                raise ValueError("not an entry")
            starts_at, ends_at = _instant(entry.get("starts_at")), _instant(entry.get("ends_at"))
            title, body = clean_text(str(entry.get("title", "")), str(entry.get("body", "")), organization_scope=True)
            _check_window(starts_at, ends_at)
            severity = AnnouncementSeverity(entry.get("severity", "information"))
        except (ValueError, HTTPException):
            warnings.add("An announcement in the bundle was not imported because it is not valid here.")
            continue
        if (title, body) in existing:
            continue
        if held >= MAX_PER_SCOPE:
            warnings.add(f"Announcements beyond the limit of {MAX_PER_SCOPE} were not imported.")
            break
        db.add(Announcement(
            organization_id=organization_id, title=title, body=body, severity=severity, starts_at=starts_at, ends_at=ends_at,
            show_on_login=bool(entry.get("show_on_login")), created_by=actor.id,
        ))
        existing.add((title, body))
        held += 1
    db.flush()


# --- public read throttle -------------------------------------------------------------------------------

_limiters: dict[tuple[int, int], RateLimiter] = {}


def enforce_public_rate_limit(client_ip: str) -> None:
    """Throttles the unauthenticated login-page read per client address (in-process, per worker).

    Raises:
        HTTPException: 429 with `Retry-After` when the bucket is empty.
    """
    cfg = get_settings()
    burst, per_minute = cfg.public_announcement_rate_limit_burst, cfg.public_announcement_rate_limit_per_minute
    limiter = _limiters.setdefault((burst, per_minute), RateLimiter(burst, per_minute / 60))
    wait = limiter.acquire(client_ip)
    if wait is not None:
        seconds = max(1, math.ceil(wait))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"Too many requests. Wait {seconds} second{'s' if seconds != 1 else ''} and try again.",
            headers={"Retry-After": str(seconds)},
        )
