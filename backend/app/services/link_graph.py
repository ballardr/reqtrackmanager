"""
Module: services.link_graph

Builds the artefact link graph: the records connected to one artefact by
`ArtefactLink` rows, out to a few hops, with every edge's direction (upstream /
downstream / related) resolved from the organisation's link-type `flow`.

Responsibilities:
- Breadth-first traversal with one batched link query per level.
- Resolve and authorise every node (this is the authorisation point for
  traversal: `services.relationships` deliberately does none).
- Resolve each edge's `flow` relative to the direction of travel.

Design decisions:
- A node is shown only if it is in the requesting project (or an org record the
  owning module makes visible there), its module/sub-component is enabled for
  the project, and the caller holds the artefact type's `view` permission
  (Fine-Grained Access Control). A failing node is counted in `hidden_count`
  and never traversed through, so paths cannot reveal that it exists.
- Core types (`requirement`, `requirement_action`) are resolved here; every
  other type goes through its module's `artefact_summary_providers` entry, so
  core never imports a module.
- A type no installed module can display counts toward `unavailable_count`
  rather than `hidden_count`, since it is a gap in display, not in access.
- The node cap (`MAX_NODES`) bounds work and response size; hitting it sets
  `truncated`.

Dependencies: `services.relationships` (link queries), `services.rbac`
(effective permissions), `modules.registry` (providers, enablement, labels).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ArtefactType, LinkFlow
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.registry import (
    ArtefactSummary,
    get_all_registered_artefact_types,
    get_artefact_summaries_in_project,
    get_artefact_type_label,
)
from app.schemas.link_graph import (
    LinkGraphDirection,
    LinkGraphEdge,
    LinkGraphFlow,
    LinkGraphNode,
    LinkGraphOut,
)
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied
from app.services.relationships import get_links_touching_many

MAX_DEPTH = 3
MAX_NODES = 150

_REQUIREMENT = ArtefactType.REQUIREMENT.value
_ACTION = ArtefactType.REQUIREMENT_ACTION.value

_Key = tuple[str, uuid.UUID]


@dataclass
class _Walk:
    """Mutable state of one traversal."""

    nodes: dict[_Key, LinkGraphNode] = field(default_factory=dict)
    edges: dict[uuid.UUID, LinkGraphEdge] = field(default_factory=dict)
    hidden: set[_Key] = field(default_factory=set)
    unavailable: set[_Key] = field(default_factory=set)
    truncated: bool = False


def _core_summaries(
    db: Session, project_id: uuid.UUID, artefact_type: str, ids: list[uuid.UUID]
) -> dict[uuid.UUID, ArtefactSummary]:
    """Summaries of the requirements / actions among `ids` that belong to `project_id`, in one query."""
    if artefact_type == _REQUIREMENT:
        rows = db.execute(
            select(Requirement, RequirementVersion)
            .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
            .where(
                Requirement.id.in_(ids), Requirement.project_id == project_id, RequirementVersion.valid_to.is_(None)
            )
        ).all()
        return {
            r.id: ArtefactSummary(
                id=r.id, project_id=r.project_id, label=f"{r.unique_code} {v.name}", status=v.status.value,
                is_archived=r.is_archived,
            )
            for r, v in rows
        }
    actions = db.scalars(
        select(RequirementAction).where(RequirementAction.id.in_(ids), RequirementAction.project_id == project_id)
    ).all()
    return {
        a.id: ArtefactSummary(
            id=a.id, project_id=a.project_id, label=f"{a.unique_code} {a.title}", status=a.outcome_status.value,
            is_archived=a.is_archived,
        )
        for a in actions
    }


def _hop_flow(flow: LinkFlow, outgoing: bool) -> LinkGraphFlow:
    """Where the neighbour sits relative to the node a hop starts from.

    `forward_is_upstream` means the link's target is upstream of its source, so
    walking source->target (`outgoing`) reaches an upstream neighbour and
    walking target->source reaches a downstream one; `forward_is_downstream`
    is the mirror; `none` is always `related`."""
    if flow is LinkFlow.NONE:
        return LinkGraphFlow.RELATED
    neighbour_upstream = (flow is LinkFlow.FORWARD_IS_UPSTREAM) == outgoing
    return LinkGraphFlow.UPSTREAM if neighbour_upstream else LinkGraphFlow.DOWNSTREAM


class _Resolver:
    """Resolves and authorises `(type, id)` pairs as visible nodes of one project, with caching."""

    _UNAVAILABLE = "unavailable"

    def __init__(self, db: Session, project: Project, user_id: uuid.UUID) -> None:
        self._db = db
        self._project = project
        self._held = get_effective_permissions(db, user_id, project_id=project.id)
        self._known: dict[_Key, ArtefactSummary | None | str] = {}

    def resolve(self, wanted: dict[str, set[uuid.UUID]]) -> None:
        """Looks up every not-yet-known id in `wanted` (grouped by type), one query per type."""
        for artefact_type, ids in wanted.items():
            todo = [i for i in ids if (artefact_type, i) not in self._known]
            if not todo:
                continue
            if not permission_satisfied(self._held, encode_permission(artefact_type, "view")):
                found: dict[uuid.UUID, ArtefactSummary] | None = {}
            elif artefact_type in (_REQUIREMENT, _ACTION):
                found = _core_summaries(self._db, self._project.id, artefact_type, todo)
            else:
                found = get_artefact_summaries_in_project(self._db, self._project.id, artefact_type, todo)
            for i in todo:
                if found is None:
                    self._known[(artefact_type, i)] = self._UNAVAILABLE
                else:
                    self._known[(artefact_type, i)] = found.get(i)

    def visible(self, key: _Key) -> ArtefactSummary | None:
        """The summary if `key` is a visible node, else `None`."""
        known = self._known.get(key)
        return known if isinstance(known, ArtefactSummary) else None

    def is_unavailable(self, key: _Key) -> bool:
        """Whether `key`'s type cannot be displayed by any installed module."""
        return self._known.get(key) == self._UNAVAILABLE


def _node(summary: ArtefactSummary, artefact_type: str, depth: int) -> LinkGraphNode:
    return LinkGraphNode(
        type=artefact_type, id=summary.id, type_label=get_artefact_type_label(artefact_type), label=summary.label,
        status=summary.status, is_archived=summary.is_archived, depth=depth,
    )


def build_link_graph(
    db: Session,
    *,
    project: Project,
    user_id: uuid.UUID,
    root_type: str,
    root_id: uuid.UUID,
    depth: int = 2,
    direction: LinkGraphDirection = LinkGraphDirection.BOTH,
) -> LinkGraphOut | None:
    """The link graph around one artefact.

    The caller must already have authorised the user as a member of `project`;
    this function authorises every record in the graph, root included.

    Args:
        db: An active database session (read-only use).
        project: The project the request is scoped to.
        user_id: The requesting user, for artefact-type view permissions.
        root_type: The root's artefact type.
        root_id: The root's id.
        depth: Hops to follow, clamped to `1..MAX_DEPTH`.
        direction: Which stored link orientations to follow at every hop.

    Returns:
        The graph, or `None` when the root's type is unregistered or the root is
        not a visible record of `project` (callers answer 404 either way).
    """
    if root_type not in get_all_registered_artefact_types():
        return None
    depth = max(1, min(depth, MAX_DEPTH))
    resolver = _Resolver(db, project, user_id)
    resolver.resolve({root_type: {root_id}})
    root_summary = resolver.visible((root_type, root_id))
    if root_summary is None:
        return None

    link_types = {
        t.id: t for t in db.scalars(
            select(RequirementLinkTypeDefinition).where(
                RequirementLinkTypeDefinition.organization_id == project.organization_id
            )
        ).all()
    }
    root = _node(root_summary, root_type, 0)
    walk = _Walk(nodes={(root_type, root_id): root})
    frontier: set[_Key] = {(root_type, root_id)}
    follow_out = direction in (LinkGraphDirection.OUTGOING, LinkGraphDirection.BOTH)
    follow_in = direction in (LinkGraphDirection.INCOMING, LinkGraphDirection.BOTH)

    for level in range(1, depth + 1):
        if not frontier:
            break
        by_type: dict[str, list[uuid.UUID]] = defaultdict(list)
        for artefact_type, artefact_id in frontier:
            by_type[artefact_type].append(artefact_id)
        links = get_links_touching_many(db, by_type, outgoing=follow_out, incoming=follow_in)

        hops: list[tuple[ArtefactLink, _Key, _Key, bool]] = []
        for link in links:
            source, target = (link.source_type, link.source_id), (link.target_type, link.target_id)
            if follow_out and source in frontier:
                hops.append((link, source, target, True))
            if follow_in and target in frontier:
                hops.append((link, target, source, False))

        wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
        for _link, _from, neighbour, _out in hops:
            wanted[neighbour[0]].add(neighbour[1])
        resolver.resolve(wanted)

        next_frontier: set[_Key] = set()
        for link, from_key, to_key, outgoing in hops:
            if link.id in walk.edges:
                continue
            summary = resolver.visible(to_key)
            if summary is None:
                (walk.unavailable if resolver.is_unavailable(to_key) else walk.hidden).add(to_key)
                continue
            if to_key not in walk.nodes:
                if len(walk.nodes) >= MAX_NODES:
                    walk.truncated = True
                    continue
                walk.nodes[to_key] = _node(summary, to_key[0], level)
                next_frontier.add(to_key)
            link_type = link_types.get(link.link_type_id) if link.link_type_id is not None else None
            phrase = None if link_type is None else (link_type.forward_name if outgoing else link_type.reverse_name)
            walk.edges[link.id] = LinkGraphEdge(
                id=link.id, from_type=from_key[0], from_id=from_key[1], to_type=to_key[0], to_id=to_key[1],
                link_type_id=link.link_type_id, phrase=phrase, outgoing=outgoing,
                flow=LinkGraphFlow.RELATED if link_type is None else _hop_flow(link_type.flow, outgoing),
            )
        frontier = next_frontier

    return LinkGraphOut(
        root=root, nodes=list(walk.nodes.values()), edges=list(walk.edges.values()), truncated=walk.truncated,
        hidden_count=len(walk.hidden), unavailable_count=len(walk.unavailable),
    )
