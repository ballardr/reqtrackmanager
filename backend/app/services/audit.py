"""
Module: services.audit

Central helper for writing audit trail entries (C-A-01, C-A-03, C-A-05) and
login events (C-A-07). Every router that mutates organisational or project
structure calls `log_event` so the audit trail is consistent instead of
being reimplemented ad hoc per endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, LoginEvent


def log_event(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID | str,
    action: str,
    actor_id: UUID | None,
    organization_id: UUID | None = None,
    project_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    """Writes a single audit event row.

    Args:
        db: An active database session (event is added but not committed;
            callers commit as part of their own transaction).
        entity_type: Short entity name, e.g. "project", "requirement".
        entity_id: Primary key of the affected entity.
        action: What happened, e.g. "created", "updated", "approved".
        actor_id: The acting user, or None for system-initiated actions.
        organization_id: Owning organisation, if applicable.
        project_id: Owning project, if applicable.
        detail: Optional structured detail such as changed fields.

    Returns:
        The AuditEvent instance that was added to the session.
    """
    event = AuditEvent(
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        actor_id=actor_id,
        organization_id=organization_id,
        project_id=project_id,
        detail=detail,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    return event


def log_login(
    db: Session,
    *,
    user_id: UUID | None,
    email_attempted: str,
    ip_address: str,
    success: bool,
) -> LoginEvent:
    """Writes a login attempt event (C-A-07).

    Args:
        db: An active database session.
        user_id: The matched user id, if the email resolved to a user.
        email_attempted: The email address supplied at login.
        ip_address: The client IP address.
        success: Whether authentication succeeded.

    Returns:
        The LoginEvent instance that was added to the session.
    """
    event = LoginEvent(
        user_id=user_id,
        email_attempted=email_attempted,
        ip_address=ip_address,
        location=None,
        success=success,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    return event
