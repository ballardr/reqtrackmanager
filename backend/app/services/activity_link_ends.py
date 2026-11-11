"""
Module: services.activity_link_ends

The two records a link event joins, for the project History page and the record Activity aside.

Responsibilities:
- Read the ends of a link audit event from its `detail` (`link_ends`), one reader per event entity type: the
  generic `artefact_link` and the older requirement families here, a module's families through
  `ModuleDefinition.activity_link_ends`.
- Resolve a page of link events to labelled, visibility-checked ends (`attach_link_ends`) with one resolver
  lookup per record type, never one per entry.

Design decisions:
- An end the viewer cannot open keeps its type and loses its identity, label and project (the id of a record the
  viewer may not see is never returned), so the event still reads "a Decision" rather than disappearing. A record
  deleted since the event is indistinguishable from a hidden one and is shown the same way.
- Readers return ids and types only; labels always come from current state through `ArtefactResolver`, so a
  renamed record shows its current title on every row.
- A core file never names a module's detail keys: a module family without a reader shows no ends.

External dependencies: `services.link_graph.ArtefactResolver` (visibility), `modules.registry` (module readers).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ArtefactType
from app.models.project import Project
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.registry import (
    ActivityLinkEnds,
    ActivityLinkEndsReader,
    get_activity_link_ends,
    get_artefact_type_label,
)
from app.schemas.changes import ChangeEntryOut, LinkedRecordOut
from app.services.link_graph import ArtefactResolver

GENERIC_LINK_EVENT_TYPE = "artefact_link"


def _uuid(value: Any) -> uuid.UUID | None:
    """A UUID from an audit detail value, else `None`."""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _generic_ends(detail: dict[str, Any]) -> ActivityLinkEnds | None:
    """`artefact_link` events: both ends and the link type are in the detail."""
    source_id, target_id = _uuid(detail.get("source_id")), _uuid(detail.get("target_id"))
    source_type, target_type = detail.get("source_type"), detail.get("target_type")
    if source_id is None or target_id is None or not isinstance(source_type, str) or not isinstance(target_type, str):
        return None
    return ActivityLinkEnds((source_type, source_id), (target_type, target_id), link_type_id=_uuid(detail.get("link_type_id")))


def _requirement_link_ends(detail: dict[str, Any]) -> ActivityLinkEnds | None:
    """`requirement_link` events: a requirement to a requirement."""
    source_id, target_id = _uuid(detail.get("source_requirement_id")), _uuid(detail.get("target_requirement_id"))
    if source_id is None or target_id is None:
        return None
    requirement = ArtefactType.REQUIREMENT.value
    return ActivityLinkEnds((requirement, source_id), (requirement, target_id), link_type_id=_uuid(detail.get("link_type_id")))


def _requirement_action_link_ends(detail: dict[str, Any]) -> ActivityLinkEnds | None:
    """`requirement_action_link` events: an action to the requirement it was linked to."""
    action_id, requirement_id = _uuid(detail.get("action_id")), _uuid(detail.get("requirement_id"))
    if action_id is None or requirement_id is None:
        return None
    return ActivityLinkEnds(
        (ArtefactType.REQUIREMENT_ACTION.value, action_id), (ArtefactType.REQUIREMENT.value, requirement_id),
    )


#: The readers of the core event types; a module's are merged in by `readers`.
CORE_LINK_ENDS: dict[str, ActivityLinkEndsReader] = {
    GENERIC_LINK_EVENT_TYPE: _generic_ends,
    "requirement_link": _requirement_link_ends,
    "requirement_action_link": _requirement_action_link_ends,
}


def readers() -> dict[str, ActivityLinkEndsReader]:
    """Every event entity type with a reader: the core ones overlaid with each registered module's."""
    return {**CORE_LINK_ENDS, **get_activity_link_ends()}


def link_ends(entity_type: str, detail: dict[str, Any] | None, known: dict[str, ActivityLinkEndsReader] | None = None) -> ActivityLinkEnds | None:
    """The ends of one link event.

    Args:
        entity_type: The audit event's entity type.
        detail: The audit event's detail.
        known: The map from `readers()`, passed by a caller reading many events.

    Returns:
        The ends, or `None` when the type has no reader or the detail does not name two records.
    """
    reader = (known if known is not None else readers()).get(entity_type)
    return reader(detail) if reader is not None and detail else None


def attach_link_ends(db: Session, project: Project, viewer_id: uuid.UUID, entries: list[ChangeEntryOut]) -> None:
    """Fills `linked_records` and `link_type_label` on the link events among `entries`, in place.

    Args:
        db: An active database session (read only).
        project: The project whose History is read.
        viewer_id: The viewer; an end is named only when the viewer may open it (the Links panel's rule).
        entries: A page of entries; entries that are not link events are left untouched.
    """
    known = readers()
    found: list[tuple[ChangeEntryOut, ActivityLinkEnds]] = []
    wanted: dict[str, set[uuid.UUID]] = {}
    for entry in entries:
        ends = link_ends(entry.entity_type, entry.detail, known)
        if ends is None:
            continue
        found.append((entry, ends))
        for artefact_type, artefact_id in (ends.source, ends.target):
            wanted.setdefault(artefact_type, set()).add(artefact_id)
    if not found:
        return
    resolver = ArtefactResolver(db, project, viewer_id, include_related=True)
    resolver.resolve(wanted)
    link_type_ids = {ends.link_type_id for _, ends in found if ends.link_type_id is not None}
    names = dict(db.execute(
        select(RequirementLinkTypeDefinition.id, RequirementLinkTypeDefinition.forward_name)
        .where(RequirementLinkTypeDefinition.id.in_(link_type_ids))
    ).tuples().all()) if link_type_ids else {}
    for entry, ends in found:
        entry.linked_records = [
            _linked_record(resolver, role, end) for role, end in (("source", ends.source), ("target", ends.target))
        ]
        entry.link_type_label = ends.link_type_label or (names.get(ends.link_type_id) if ends.link_type_id else None)


def _linked_record(resolver: ArtefactResolver, role: str, end: tuple[str, uuid.UUID]) -> LinkedRecordOut:
    """One end of a link event; identity, label and project only when the viewer may open the record."""
    artefact_type, artefact_id = end
    summary = resolver.visible(end)
    out = LinkedRecordOut(role=role, entity_type=artefact_type, entity_type_label=get_artefact_type_label(artefact_type))
    if summary is not None:
        out.entity_id = artefact_id
        out.label = summary.label
        out.project_id = summary.project_id
        out.project_name = resolver.project_name(summary.project_id)
    return out
