"""
Module: services.report_traversal

How a custom report layout reaches records: the root records of a type, and the records linked to
a set of records ("for each requirement, its linked Pain Points").

Responsibilities:
- `root_records`: the records of one type in the report's projects that the caller may see.
- `linked_records`: for many parent records at once, the visible records of one type linked to each
  (optionally only through chosen link types, in one direction), with a per-parent count of linked
  records the caller cannot see.

Design decisions:
- **One authorisation point.** Every candidate record goes through the link graph's
  `ArtefactResolver` (project membership, module and sub-component enablement, the type's `view`
  permission in the record's own project, nesting rules). This module adds no visibility rule of its
  own, so a layout can never show a record the caller's link graph would not.
- A record that fails the resolver is **counted, never named**: `hidden` holds a number per parent,
  and a type no installed module can display is counted apart (`unavailable`), exactly as the graph does.
  A hidden record is not traversed through, so a path cannot reveal it.
- One batched link query and one resolver call per level, whatever the number of parents; work is
  bounded by `MAX_ROOTS` and `MAX_LINKED`, and hitting a cap sets `truncated` instead of failing.
- A dormant cross-project link (its two projects no longer in one ancestry line) is `unavailable`,
  not visible, as in the graph.

Dependencies: `services.link_graph` (resolver), `services.relationships` (link query),
`services.link_nesting` (liveness), `services.report_fields` (provider lookup).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.modules.registry import ArtefactSummary
from app.services.link_graph import ArtefactResolver
from app.services.link_nesting import is_link_live
from app.services.relationships import get_links_touching_many
from app.services.report_fields import provider_for

#: Most root records a layout source may read in one run.
MAX_ROOTS = 5000
#: Most linked records one traversal step may return in total (across all parents).
MAX_LINKED = 20000

Key = tuple[str, uuid.UUID]


class LinkDirection(str, Enum):
    """Which stored orientation of a link to follow from the parent record."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


@dataclass
class RootRecords:
    """The records of one type a layout starts from.

    Attributes:
        summaries: The visible records, in code then id order.
        hidden: How many candidate records the caller cannot see (counted, never named).
        unavailable: Candidates of a type no installed module can display.
        truncated: Whether `MAX_ROOTS` stopped the read.
    """

    summaries: list[ArtefactSummary] = field(default_factory=list)
    hidden: int = 0
    unavailable: int = 0
    truncated: bool = False


@dataclass
class LinkedRecords:
    """The result of one traversal step.

    Attributes:
        by_parent: `{parent: its visible linked records}`, in link creation order; every parent asked about is a key.
        hidden: `{parent: number of matching linked records the caller cannot see}`; absent means none.
        unavailable: `{parent: number of matching links that cannot be shown}` (dormant cross-project link,
            or a type no installed module can display).
        truncated: Whether `MAX_LINKED` stopped the read.
    """

    by_parent: dict[Key, list[ArtefactSummary]] = field(default_factory=dict)
    hidden: dict[Key, int] = field(default_factory=dict)
    unavailable: dict[Key, int] = field(default_factory=dict)
    truncated: bool = False


def root_records(
    db: Session,
    resolver: ArtefactResolver,
    project: Project,
    artefact_type: str,
    project_ids: Collection[uuid.UUID],
    *,
    include_archived: bool = False,
) -> RootRecords:
    """The visible records of `artefact_type` in `project_ids`.

    Args:
        db: Active session (read only).
        resolver: The caller's `ArtefactResolver` for the report's project (the authorisation point).
        project: The project the report runs for (its organisation owns organisation-level records).
        artefact_type: A reportable type.
        project_ids: The projects whose records are candidates (the report's scope).
        include_archived: Whether archived records are candidates.

    Returns:
        The visible records and the counts of those not shown.

    Raises:
        report_fields.UnknownReportFieldError: The type is not reportable.
    """
    provider = provider_for(artefact_type)
    cols = provider.columns
    scope = cols.project_id.in_(list(project_ids))
    if cols.organization_id is not None:
        scope = scope | and_(cols.project_id.is_(None), cols.organization_id == project.organization_id)
    query = select(cols.id).select_from(provider.from_clause).where(scope, *provider.where)
    if not include_archived:
        query = query.where(cols.is_archived.is_(False))
    ids = list(db.scalars(query.order_by(cols.code, cols.id).limit(MAX_ROOTS + 1)).all())
    result = RootRecords(truncated=len(ids) > MAX_ROOTS)
    ids = ids[:MAX_ROOTS]

    resolver.resolve({artefact_type: set(ids)})
    for record_id in ids:
        key = (artefact_type, record_id)
        summary = resolver.visible(key)
        if summary is not None:
            result.summaries.append(summary)
        elif resolver.is_unavailable(key):
            result.unavailable += 1
        else:
            result.hidden += 1
    return result


def linked_records(
    db: Session,
    resolver: ArtefactResolver,
    parents: Iterable[Key],
    target_type: str,
    *,
    link_type_ids: Collection[uuid.UUID] | None = None,
    direction: LinkDirection = LinkDirection.BOTH,
) -> LinkedRecords:
    """The visible `target_type` records linked to each parent, in one batched step.

    Args:
        db: Active session (read only).
        resolver: The caller's `ArtefactResolver` (the authorisation point).
        parents: The `(type, id)` records to start from; each must already be visible to the caller.
        target_type: The type of the linked records wanted; links to other types are ignored.
        link_type_ids: Follow only links of these link types; `None` follows any.
        direction: Which stored orientation to follow from the parent.

    Returns:
        The visible linked records per parent, with counts of those not shown.

    Raises:
        report_fields.UnknownReportFieldError: `target_type` is not reportable.
    """
    provider_for(target_type)
    parent_list = list(dict.fromkeys(parents))
    result = LinkedRecords(by_parent={p: [] for p in parent_list})
    if not parent_list:
        return result
    follow_out = direction in (LinkDirection.OUTGOING, LinkDirection.BOTH)
    follow_in = direction in (LinkDirection.INCOMING, LinkDirection.BOTH)
    wanted_links = None if link_type_ids is None else set(link_type_ids)

    by_type: dict[str, list[uuid.UUID]] = defaultdict(list)
    for parent_type, parent_id in parent_list:
        by_type[parent_type].append(parent_id)
    parent_set = set(parent_list)

    pairs: list[tuple[Key, Key, ArtefactLink]] = []
    for link in get_links_touching_many(db, by_type, outgoing=follow_out, incoming=follow_in):
        if wanted_links is not None and link.link_type_id not in wanted_links:
            continue
        source, target = (link.source_type, link.source_id), (link.target_type, link.target_id)
        if follow_out and source in parent_set and target[0] == target_type:
            pairs.append((source, target, link))
        if follow_in and target in parent_set and source[0] == target_type:
            pairs.append((target, source, link))

    resolver.resolve({target_type: {neighbour[1] for _parent, neighbour, _link in pairs}})
    chain_cache: dict[uuid.UUID, list[uuid.UUID]] = {}
    total = 0
    seen: set[tuple[Key, Key]] = set()
    for parent, neighbour, link in pairs:
        if (parent, neighbour) in seen:
            continue
        seen.add((parent, neighbour))
        if not is_link_live(db, link, chain_cache):
            result.unavailable[parent] = result.unavailable.get(parent, 0) + 1
            continue
        summary = resolver.visible(neighbour)
        if summary is None:
            counts = result.unavailable if resolver.is_unavailable(neighbour) else result.hidden
            counts[parent] = counts.get(parent, 0) + 1
            continue
        if total >= MAX_LINKED:
            result.truncated = True
            continue
        total += 1
        result.by_parent[parent].append(summary)
    return result


__all__ = ["MAX_LINKED", "MAX_ROOTS", "LinkDirection", "LinkedRecords", "RootRecords", "linked_records", "root_records"]
