"""
Module: services.record_activity

The activity timeline of one artefact (any registered type), for the aside's Activity tab.

Responsibilities:
- Merge the record's own audit events, its version history (requirements and change requests,
  whose edits are versions rather than plain audit rows) and the link events that touch it.
- Authorise exactly as the Links panel does: the record must be a visible record of the project
  (module enabled, the type's `view` permission held, `services.link_graph.ArtefactResolver`),
  and a link event is shown only when the record at its other end is also visible, so the
  timeline never reveals a record the viewer could not open.
- Strip secret-looking keys from event `detail` before it leaves the server.

Design decisions:
- Types follow the audit convention (`entity_type` == the artefact type, `entity_id` == the
  record id), so a new module type needs no registration here. Link events are matched on the
  record id appearing in the event's `detail`, which covers the generic `artefact_link` events
  and the older per-pair link tables with one rule.
- Discussion comments stay out of requirement and change request timelines (they have their own
  thread), as in the project history.

External dependencies: `services.changes` (version-derived entries), `services.link_graph`
(visibility), `services.audit`'s `AuditEvent` rows.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.project import Project
from app.models.user import User
from app.modules.registry import get_all_registered_artefact_types, get_artefact_type_label
from app.schemas.changes import ChangeEntryOut, RecordActivityOut
from app.services.changes import attach_actor_names, get_project_changes
from app.services.link_graph import ArtefactResolver

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

#: Types whose edits are versions: their timeline comes from `get_project_changes`.
_VERSIONED_TYPES = frozenset({"requirement", "change_request"})
_SECRET_KEY = re.compile(r"password|secret|token|hash|api_key|totp", re.IGNORECASE)
_GENERIC_LINK = "artefact_link"


def _scrub(value: Any) -> Any:
    """Returns `value` with every dict key that looks like a secret removed, recursively."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if not _SECRET_KEY.search(str(k))}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _entry(event: AuditEvent, *, detail: dict[str, Any] | None) -> ChangeEntryOut:
    """Builds the timeline entry for one audit event."""
    return ChangeEntryOut(
        timestamp=event.created_at, entity_type=event.entity_type, entity_id=event.entity_id,
        action=event.action, actor_id=event.actor_id, detail=detail,
    )


def _own_events(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> list[ChangeEntryOut]:
    """The audit events written against the record itself."""
    events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_type == artefact_type, AuditEvent.entity_id == str(artefact_id)
        )
    ).all()
    return [_entry(e, detail=_scrub(e.detail) if e.detail else None) for e in events]


def _generic_link_entries(
    db: Session, resolver: ArtefactResolver, project: Project, artefact_type: str, artefact_id: uuid.UUID,
) -> list[ChangeEntryOut]:
    """Generic link events touching the record whose other end the viewer can see.

    The detail gains `other_type`, `other_label` and `direction` (`"outgoing"` when the record is
    the source) so the UI can say what was linked without a second request."""
    events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_type == _GENERIC_LINK, AuditEvent.project_id == project.id,
            or_(
                AuditEvent.detail["source_id"].astext == str(artefact_id),
                AuditEvent.detail["target_id"].astext == str(artefact_id),
            ),
        )
    ).all()
    candidates: list[tuple[AuditEvent, str, uuid.UUID, str]] = []
    wanted: dict[str, set[uuid.UUID]] = {}
    for event in events:
        detail = event.detail or {}
        outgoing = detail.get("source_id") == str(artefact_id) and detail.get("source_type") == artefact_type
        incoming = detail.get("target_id") == str(artefact_id) and detail.get("target_type") == artefact_type
        if not (outgoing or incoming):
            continue
        side = "target" if outgoing else "source"
        try:
            other_id = uuid.UUID(str(detail.get(f"{side}_id")))
        except ValueError:
            continue
        other_type = str(detail.get(f"{side}_type"))
        wanted.setdefault(other_type, set()).add(other_id)
        candidates.append((event, other_type, other_id, "outgoing" if outgoing else "incoming"))
    resolver.resolve(wanted)
    entries: list[ChangeEntryOut] = []
    for event, other_type, other_id, direction in candidates:
        other = resolver.visible((other_type, other_id))
        if other is None:
            continue
        detail = _scrub(event.detail or {})
        detail.update({
            "other_type": other_type, "other_type_label": get_artefact_type_label(other_type),
            "other_label": other.label, "direction": direction,
        })
        entries.append(_entry(event, detail=detail))
    return entries


def _legacy_link_entries(
    db: Session, project: Project, artefact_id: uuid.UUID,
) -> list[ChangeEntryOut]:
    """Events of the older per-pair link tables (`*_link` other than the generic one) that name the record."""
    events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_type.like("%\\_link", escape="\\"), AuditEvent.entity_type != _GENERIC_LINK,
            or_(
                AuditEvent.project_id == project.id,
                (AuditEvent.project_id.is_(None)) & (AuditEvent.organization_id == project.organization_id),
            ),
            cast(AuditEvent.detail, String).contains(str(artefact_id)),
        )
    ).all()
    return [_entry(e, detail=_scrub(e.detail) if e.detail else None) for e in events]


def get_record_activity(
    db: Session, *, project: Project, user: User, artefact_type: str, artefact_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE, offset: int = 0,
) -> RecordActivityOut:
    """One page of the activity timeline of a record, newest first.

    Args:
        db: An active database session.
        project: The project the page is opened in.
        user: The viewer (their visibility rules apply to the record and to every link end).
        artefact_type: A registered artefact type.
        artefact_id: The record's id.
        limit: Page size, capped at `MAX_PAGE_SIZE`.
        offset: Entries to skip.

    Returns:
        The page and whether more entries follow.

    Raises:
        HTTPException: 404 when the type is unregistered or the record is not visible to the viewer
            in this project (the two cases are indistinguishable, as for the Links panel).
    """
    if artefact_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    resolver = ArtefactResolver(db, project, user.id, include_related=True)
    resolver.resolve({artefact_type: {artefact_id}})
    summary = resolver.visible((artefact_type, artefact_id))
    # A related (ancestor/descendant) project's record is reachable through the resolver for link
    # display; its own timeline is opened from that project, never through this one.
    if summary is None or (summary.project_id is not None and summary.project_id != project.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")

    if artefact_type in _VERSIONED_TYPES:
        entries = get_project_changes(
            db, project.id, since=None, until=None, include_comments=False,
            entity_type=artefact_type, entity_id=artefact_id,
        )
        for entry in entries:
            if entry.detail:
                entry.detail = _scrub(entry.detail)
    else:
        entries = _own_events(db, artefact_type, artefact_id)
    entries += _generic_link_entries(db, resolver, project, artefact_type, artefact_id)
    entries += _legacy_link_entries(db, project, artefact_id)

    attach_actor_names(db, [e for e in entries if e.actor_display_name is None])
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    size = max(1, min(limit, MAX_PAGE_SIZE))
    page = entries[offset:offset + size]
    return RecordActivityOut(entries=page, has_more=len(entries) > offset + size)
