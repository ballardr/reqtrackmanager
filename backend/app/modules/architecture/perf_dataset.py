"""
Module: modules.architecture.perf_dataset

The dataset generators for the `architecture_element` and `architecture_connection` artefact types:
project elements in a tree with ports, and connections between them, with tags and places, links to
earlier types, and the audit events the application writes.

Responsibilities:
- Write `architecture_elements`, `architecture_ports`, `architecture_connections`, tags, places, cross-type
  links and "created" audit events, and the project's sequence counters.

Design decisions:
- Elements form a tree at most four levels deep (a share are roots); ports sit on most elements and a
  connection joins two elements, on a port each when both have one. Connections are generated after elements
  (`order`), so their ends exist.
- Only project-owned records are generated. Organisation-owned elements, collections and grants are not (a
  profile's unit is the project); the visibility resolver's cost is covered by the scaling-shape guard instead.

Dependencies: `perf_dataset.records`, this module's models and service constants.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.modules.architecture.enums import PortDirection, RecordStatus
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureConnectionType,
    ArchitectureElement,
    ArchitectureElementType,
    ArchitecturePort,
)
from app.modules.architecture.service import (
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_CODE_PREFIX,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_CODE_PREFIX,
)
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import PerfProjectContext
from app.services.perf_dataset.records import RecordBatch, add_tags, created_at, link_to_earlier, pick_weighted

#: Deepest generated tree level (a root is 1); the application allows more.
_GENERATED_DEPTH = 4
_STATUS_MIX = ((RecordStatus.ACTIVE, 0.6), (RecordStatus.DRAFT, 0.3), (RecordStatus.RETIRED, 0.1))
_PORT_NAMES = ("Main", "Control", "Data", "Power", "Debug", "Status")


def _type_ids(
    ctx: PerfProjectContext, model: type[ArchitectureElementType] | type[ArchitectureConnectionType],
) -> list[uuid.UUID]:
    """The ids of the organisation's default rows of a vocabulary (every generated project offers them)."""
    return list(ctx.db.scalars(select(model.id).where(model.organization_id == ctx.organization_uuid)))


def generate_elements(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's elements, their ports and everything hanging off them.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(ELEMENT_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    types = _type_ids(ctx, ArchitectureElementType)
    connection_types = _type_ids(ctx, ArchitectureConnectionType)
    if count == 0 or not types:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, ELEMENT_ARTEFACT_TYPE, ELEMENT_CODE_PREFIX, ArchitectureElement)
    depths: dict[uuid.UUID, int] = {}
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        parent = None
        if batch.ids and rng.random() < 0.7:
            candidate = rng.choice(batch.ids)
            if depths[candidate] < _GENERATED_DEPTH:
                parent = candidate
        record_id = batch.new_id()
        depths[record_id] = depths[parent] + 1 if parent else 1
        status = pick_weighted(rng, _STATUS_MIX)
        archived = rng.random() < 0.03
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.5 else None
        name = textgen.title(rng)
        batch.add(
            {
                "id": record_id, "name": name, "description": textgen.paragraphs(rng, empty_chance=0.2, short_max=3),
                "element_type_id": rng.choice(types), "parent_id": parent,
                "owner_type": "user" if owner else None, "owner_id": owner, "status": status.value, "version": 1,
                "is_archived": archived, "archived_at": created if archived else None,
                "archived_by": creator if archived else None,
            },
            creator=creator, at=created, title=name, detail={"status": status.value},
        )
        for order in range(rng.choice((0, 1, 1, 2, 3))):
            batch.satellite(ArchitecturePort, {
                "id": batch.new_id(), "element_id": record_id, "name": _PORT_NAMES[order],
                "direction": rng.choice(list(PortDirection)).value,
                "connection_type_id": rng.choice(connection_types) if connection_types and rng.random() < 0.8 else None,
                "sort_order": order, "created_at": created, "updated_at": created,
            })
    batch.write()
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, [("requirement", 0.4), ("risk", 0.1), ("decision", 0.1)])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}


def generate_connections(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's connections between the elements `generate_elements` wrote.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(CONNECTION_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    elements = ctx.shared.get(ELEMENT_ARTEFACT_TYPE, [])
    types = _type_ids(ctx, ArchitectureConnectionType)
    if count == 0 or len(elements) < 2 or not types:
        return {}
    start = dict(ctx.counts)
    ports: dict[uuid.UUID, list[uuid.UUID]] = {}
    for port_id, element_id in ctx.db.execute(
        select(ArchitecturePort.id, ArchitecturePort.element_id).where(ArchitecturePort.element_id.in_(elements))
    ):
        ports.setdefault(element_id, []).append(port_id)
    batch = RecordBatch.start(ctx, CONNECTION_ARTEFACT_TYPE, CONNECTION_CODE_PREFIX, ArchitectureConnection)
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        source, target = rng.sample(elements, 2)
        status = pick_weighted(rng, _STATUS_MIX)
        archived = rng.random() < 0.03
        batch.add(
            {
                "name": textgen.title(rng) if rng.random() < 0.7 else "", "connection_type_id": rng.choice(types),
                "source_element_id": source, "source_port_id": rng.choice(ports[source]) if ports.get(source) else None,
                "target_element_id": target, "target_port_id": rng.choice(ports[target]) if ports.get(target) else None,
                "protocol": rng.choice(("v1", "v2", "9600 baud", "TLS 1.3", "")),
                "description": textgen.paragraphs(rng, empty_chance=0.3, short_max=2), "status": status.value,
                "version": 1, "is_archived": archived, "archived_at": created if archived else None,
                "archived_by": creator if archived else None,
            },
            creator=creator, at=created, title="connection", detail={"status": status.value},
        )
    batch.write()
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, [("requirement", 0.3), ("risk", 0.05)])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}
