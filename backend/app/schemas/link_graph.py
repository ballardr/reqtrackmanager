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
    """One visible record in the graph."""

    type: str
    id: UUID
    type_label: str
    label: str
    status: str | None
    is_archived: bool
    depth: int


class LinkGraphEdge(BaseModel):
    """One link between two included nodes, oriented in the direction the
    traversal reached it (`from` is the node nearer the root).

    `phrase` reads from the `from` node's side (the link type's forward name
    when `outgoing`, its reverse name otherwise); `None` for an untyped link.
    `outgoing` is true when `from` is the link's stored source."""

    id: UUID
    from_type: str
    from_id: UUID
    to_type: str
    to_id: UUID
    link_type_id: UUID | None
    phrase: str | None
    flow: LinkGraphFlow
    outgoing: bool


class LinkGraphOut(BaseModel):
    """The graph around `root`.

    `truncated` is true when the node cap stopped the traversal early.
    `hidden_count` counts distinct linked records not shown (no access, another
    project, a disabled module, or no longer existing); `unavailable_count`
    counts linked records of a type no installed module can display. Neither
    is ever traversed through."""

    root: LinkGraphNode
    nodes: list[LinkGraphNode]
    edges: list[LinkGraphEdge]
    truncated: bool
    hidden_count: int
    unavailable_count: int
