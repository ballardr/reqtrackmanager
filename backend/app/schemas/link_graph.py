"""
Module: schemas.link_graph

Response model for the artefact link graph
(`GET /projects/{id}/artefacts/{type}/{id}/link-graph`): the records linked to
one artefact out to a few hops, with each edge's direction already resolved
against the organisation's link-type `flow` settings so no client re-derives it.
"""

from __future__ import annotations

import enum
from uuid import UUID

from pydantic import BaseModel


class LinkGraphDirection(str, enum.Enum):
    """Which stored link orientations a traversal follows: `outgoing` (the
    artefact is the link's source), `incoming` (it is the target) or `both`."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class LinkGraphFlow(str, enum.Enum):
    """Where an edge's `to` node sits relative to its `from` node:
    `upstream` (where `from` comes from), `downstream` (what depends on
    `from`) or `related` (no direction: symmetric, unclassified or untyped)."""

    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    RELATED = "related"


class LinkGraphNode(BaseModel):
    """One visible record in the graph. `project_id`/`project_name` say which project
    it belongs to (always one the viewer can open; `None` for an organisation-owned
    record), so a node from a parent or child project can be labelled."""

    type: str
    id: UUID
    type_label: str
    label: str
    status: str | None
    is_archived: bool
    depth: int
    project_id: UUID | None = None
    project_name: str | None = None


class LinkGraphEdge(BaseModel):
    """One link between two included nodes, oriented in the direction the
    traversal reached it (`from` is the node nearer the root).

    `phrase` reads from the `from` node's side (the link type's forward name
    when `outgoing`, its reverse name otherwise); `None` for an untyped link.
    `outgoing` is true when `from` is the link's stored source. `cross_project` marks
    a link between a project and its ancestor/descendant; `nesting_permitted` is false
    when such a link no longer satisfies its link type's nesting scope (kept, flagged).
    `dedicated` marks a link managed by its own action: a type with a dedicated endpoint
    (e.g. Supersedes) or an untyped structural link (action membership). It is shown but
    cannot be removed through the generic endpoint."""

    id: UUID
    from_type: str
    from_id: UUID
    to_type: str
    to_id: UUID
    link_type_id: UUID | None
    phrase: str | None
    flow: LinkGraphFlow
    outgoing: bool
    cross_project: bool = False
    nesting_permitted: bool = True
    dedicated: bool = False


class LinkGraphOut(BaseModel):
    """The graph around `root`.

    `truncated` is true when the node cap stopped the traversal early.
    `hidden_count` counts distinct linked records not shown (no access, another
    project, a disabled module, or no longer existing); `unavailable_count`
    counts linked records of a type no installed module can display. Neither
    is ever traversed through. `can_link` is whether the caller may add or remove
    links on the root directly now (`link` or `manage` on its type in the request
    project, in any state; or, for a core record that is not approved, a stakeholder,
    project administrator or manager role). `can_propose` is whether they may link it
    at all, including by proposing a link on a change request once it is approved. A
    client uses both to hide controls that would only answer 403."""

    root: LinkGraphNode
    nodes: list[LinkGraphNode]
    edges: list[LinkGraphEdge]
    truncated: bool
    hidden_count: int
    unavailable_count: int
    can_link: bool = False
    can_propose: bool = False
