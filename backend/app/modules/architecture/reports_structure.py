"""
Module: modules.architecture.reports_structure

The structural reports: AR3 Interface list (the connection table), AR4 Element breakdown (the element tree) and AR5
Unconnected elements (elements nothing connects to, and elements no diagram shows).

Design decisions (Decided by: Agent):
- **The interface list is the connection table with both ends named.** A port is named after its element
  (`ELM-003 Encoder (Port A)`); an end the reported project does not own is "Shared element" (`report_support`).
- **Linked requirements** are the requirements linked to the connection in either direction, by code.
- **The breakdown is the project's own parent chain** in tree order (a parent, then its children by code); the
  `Level` column carries the depth because a report cell is plain text, and `Parent` names the parent's code. An
  `element` parameter limits it to that element and everything below.
- **Unconnected means no live connection on the element or on anything below it** (a container whose children connect
  is connected through them), the same roll-up the boundary report reads. **Not on a diagram** means placed on no
  diagram that is not archived or retired.
- Archived records are left out; retired and rejected connections do not count as connecting.

Dependencies: `report_support`, this module's models, `app.services.report_framework`, `app.services.principals`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.modules.architecture.labels import INACTIVE_STATUSES, record_status_label
from app.modules.architecture.models import (
    ArchitectureConnectionType,
    ArchitectureDiagram,
    ArchitectureDiagramPlacement,
    ArchitectureElement,
    ArchitectureElementType,
    ArchitecturePort,
)
from app.modules.architecture.report_support import (
    chain_of,
    element_text,
    find_element,
    live_connections,
    project_elements,
)
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_SUBCOMPONENT_KEY,
    DIAGRAM_ARTEFACT_TYPE,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_SUBCOMPONENT_KEY,
)
from app.modules.registry import ReportDefinition, ReportParamDefinition, ReportPartDefinition
from app.services.principals import principal_labels, principal_text
from app.services.report_framework import ReportContext, ReportMetric, ReportResult, ReportSection

MODULE_KEY = ARCHITECTURE_MODULE_KEY
REQUIREMENT_TYPE = "requirement"
_CLIP = 120

INTERFACE_COLUMNS = ["Connection", "Name", "Type", "Protocol", "From", "To", "Direction", "Status", "Requirements", "Project"]
BREAKDOWN_COLUMNS = ["Level", "Element", "Type", "Status", "Owner", "Parent", "Children", "Project"]
ELEMENT_COLUMNS = ["Element", "Name", "Type", "Status", "Parent", "Project"]


def _type_names(db: Session, elements: dict[uuid.UUID, ArchitectureElement]) -> dict[uuid.UUID, str]:
    """The element type names the project's elements use, by type id."""
    if not elements:
        return {}
    return {t.id: t.name for t in db.scalars(select(ArchitectureElementType).where(
        ArchitectureElementType.id.in_({e.element_type_id for e in elements.values()})
    ))}


def collect_interface_list(db: Session, req: ReportContext) -> ReportResult:
    """AR3 — every live connection with its two ends, type, protocol and linked requirements.

    Args:
        db: Database session.
        req: The request; `element` (a code or name) keeps connections with that element as an end, `type` keeps one
            connection type by name.

    Returns:
        The report; `data` is `{"connections": int, "with_requirement": int}`.
    """
    projects = req.eligible(db, CONNECTION_SUBCOMPONENT_KEY)
    only_type = (req.params.get("type") or "").strip().casefold()
    wanted = (req.params.get("element") or "").strip()
    rows: list[list[str]] = []
    with_requirement = 0
    for project in projects:
        elements = project_elements(db, project.id)
        focus = find_element(elements, wanted) if wanted else None
        if wanted and focus is None:
            continue
        connections = [
            c for c in live_connections(db, project.id)
            if focus is None or focus.id in (c.source_element_id, c.target_element_id)
        ]
        types = {t.id: t for t in db.scalars(select(ArchitectureConnectionType).where(
            ArchitectureConnectionType.id.in_({c.connection_type_id for c in connections})
        ))} if connections else {}
        connections = [c for c in connections if not only_type or types[c.connection_type_id].name.casefold() == only_type]
        port_ids = {p for c in connections for p in (c.source_port_id, c.target_port_id) if p is not None}
        ports = {p.id: p for p in db.scalars(select(ArchitecturePort).where(ArchitecturePort.id.in_(port_ids)))} if port_ids else {}
        by_connection: dict[uuid.UUID, list[uuid.UUID]] = {}
        if connections:
            ids = {c.id for c in connections}
            for link in db.scalars(select(ArtefactLink).where(
                ((ArtefactLink.source_type == CONNECTION_ARTEFACT_TYPE) & ArtefactLink.source_id.in_(ids)
                 & (ArtefactLink.target_type == REQUIREMENT_TYPE))
                | ((ArtefactLink.target_type == CONNECTION_ARTEFACT_TYPE) & ArtefactLink.target_id.in_(ids)
                   & (ArtefactLink.source_type == REQUIREMENT_TYPE))
            )):
                connection_id, requirement_id = (
                    (link.source_id, link.target_id) if link.source_type == CONNECTION_ARTEFACT_TYPE else (link.target_id, link.source_id)
                )
                by_connection.setdefault(connection_id, []).append(requirement_id)
        codes = {
            r.id: req.code(r.unique_code, r.project_id)
            for r in db.scalars(select(Requirement).where(Requirement.id.in_({i for v in by_connection.values() for i in v})))
        } if by_connection else {}

        def end(element_id: uuid.UUID, port_id: uuid.UUID | None, elements=elements, ports=ports, project_id=project.id) -> str:
            text = element_text(req, project_id, elements, element_id)
            port = ports.get(port_id) if port_id is not None else None
            return f"{text} ({port.name})" if port is not None else text

        for c in connections:
            kind = types[c.connection_type_id]
            linked = sorted({codes[i] for i in by_connection.get(c.id, []) if i in codes})
            with_requirement += 1 if linked else 0
            rows.append([
                req.code(c.unique_code, project.id), c.name[:_CLIP], kind.name, c.protocol[:_CLIP],
                end(c.source_element_id, c.source_port_id), end(c.target_element_id, c.target_port_id),
                "One-way" if kind.directional else "Two-way", record_status_label(c.status), ", ".join(linked), project.name,
            ])
    result = ReportResult(
        key="ar3", title="Interface list", scope_label=req.scope_label, generated_at=datetime.now(UTC),
        notes=[req.scope_note, "Connections that are archived, retired or rejected are left out."],
        sections=[ReportSection("connections", "Connections", INTERFACE_COLUMNS, rows)],
        eligible_projects=len(projects),
    )
    result.metrics = [ReportMetric("Connections", len(rows)), ReportMetric("With a linked requirement", with_requirement)]
    result.data = {"connections": len(rows), "with_requirement": with_requirement}
    return result


def _tree_order(elements: dict[uuid.UUID, ArchitectureElement], root_ids: list[uuid.UUID]) -> list[tuple[int, ArchitectureElement]]:
    """Depth-first `(level, element)` pairs from `root_ids`, children by code (cycle-safe)."""
    children: dict[uuid.UUID | None, list[ArchitectureElement]] = {}
    for e in elements.values():
        children.setdefault(e.parent_id, []).append(e)
    for kids in children.values():
        kids.sort(key=lambda e: e.unique_code)
    out: list[tuple[int, ArchitectureElement]] = []
    seen: set[uuid.UUID] = set()

    def walk(element: ArchitectureElement, level: int) -> None:
        if element.id in seen:
            return
        seen.add(element.id)
        out.append((level, element))
        for kid in children.get(element.id, []):
            walk(kid, level + 1)

    for root in root_ids:
        walk(elements[root], 0)
    return out


def collect_element_breakdown(db: Session, req: ReportContext) -> ReportResult:
    """AR4 — the element tree, parents before their children, with each element's type, status and owner.

    Args:
        db: Database session.
        req: The request; `element` (a code or name) limits the tree to that element and everything below it.

    Returns:
        The report; `data` is `{"elements": int, "deepest": int}` (levels start at 1).
    """
    projects = req.eligible(db, ELEMENT_SUBCOMPONENT_KEY)
    wanted = (req.params.get("element") or "").strip()
    rows: list[list[str]] = []
    deepest = 0
    for project in projects:
        elements = project_elements(db, project.id)
        if wanted:
            focus = find_element(elements, wanted)
            roots = [focus.id] if focus is not None else []
        else:
            roots = [e.id for e in elements.values() if e.parent_id is None or e.parent_id not in elements]
            roots.sort(key=lambda i: elements[i].unique_code)
        ordered = _tree_order(elements, roots)
        labels = principal_labels(db, [(e.owner_type, e.owner_id) for _, e in ordered if e.owner_type and e.owner_id])
        names = _type_names(db, elements)
        child_count: dict[uuid.UUID, int] = {}
        for e in elements.values():
            if e.parent_id is not None:
                child_count[e.parent_id] = child_count.get(e.parent_id, 0) + 1
        for level, e in ordered:
            deepest = max(deepest, level + 1)
            parent = elements.get(e.parent_id) if e.parent_id is not None else None
            owner = labels.get((e.owner_type, e.owner_id)) if e.owner_type and e.owner_id else None
            rows.append([
                str(level + 1), f"{req.code(e.unique_code, project.id)} {e.name}".strip(), names.get(e.element_type_id, ""),
                record_status_label(e.status), principal_text(owner), req.code(parent.unique_code, project.id) if parent else "",
                str(child_count.get(e.id, 0)), project.name,
            ])
    result = ReportResult(
        key="ar4", title="Element breakdown", scope_label=req.scope_label, generated_at=datetime.now(UTC),
        notes=[req.scope_note, "Each element follows its parent; Level 1 is an element with no parent."],
        sections=[ReportSection("tree", "Elements", BREAKDOWN_COLUMNS, rows)], eligible_projects=len(projects),
    )
    result.metrics = [ReportMetric("Elements", len(rows)), ReportMetric("Levels", deepest)]
    result.data = {"elements": len(rows), "deepest": deepest}
    return result


def collect_unconnected_elements(db: Session, req: ReportContext) -> ReportResult:
    """AR6 — elements nothing connects to, and elements no diagram shows.

    Args:
        db: Database session.
        req: The request; no parameters.

    Returns:
        The report; `data` is `{"unconnected": int, "not_on_a_diagram": int}`.
    """
    projects = req.eligible(db, ELEMENT_SUBCOMPONENT_KEY)
    unconnected: list[list[str]] = []
    undrawn: list[list[str]] = []
    for project in projects:
        elements = project_elements(db, project.id)
        names = _type_names(db, elements)
        parents = {i: e.parent_id for i, e in elements.items()}
        connected: set[uuid.UUID] = set()
        for c in live_connections(db, project.id):
            for end in (c.source_element_id, c.target_element_id):
                connected.update(chain_of(parents, end))
        placed = set(db.scalars(
            select(ArchitectureDiagramPlacement.element_id).join(
                ArchitectureDiagram, ArchitectureDiagram.id == ArchitectureDiagramPlacement.diagram_id
            ).where(
                ArchitectureDiagram.project_id == project.id, ArchitectureDiagram.is_archived.is_(False),
                ArchitectureDiagram.status.not_in(INACTIVE_STATUSES),
            )
        ))

        def row(e: ArchitectureElement, project=project, elements=elements, names=names) -> list[str]:
            parent = elements.get(e.parent_id) if e.parent_id is not None else None
            return [
                req.code(e.unique_code, project.id), e.name, names.get(e.element_type_id, ""), record_status_label(e.status),
                req.code(parent.unique_code, project.id) if parent else "", project.name,
            ]

        live = [e for e in elements.values() if e.status not in INACTIVE_STATUSES]
        unconnected += [row(e) for e in live if e.id not in connected]
        undrawn += [row(e) for e in live if e.id not in placed]
    result = ReportResult(
        key="ar6", title="Unconnected elements", scope_label=req.scope_label, generated_at=datetime.now(UTC),
        notes=[
            req.scope_note,
            "An element is unconnected when neither it nor anything below it is an end of a live connection; retired and "
            "rejected elements are left out.",
        ],
        sections=[
            ReportSection("unconnected", "Elements with no connection", ELEMENT_COLUMNS, unconnected, gap=True),
            ReportSection("undrawn", "Elements on no diagram", ELEMENT_COLUMNS, undrawn, gap=True),
        ],
        eligible_projects=len(projects),
    )
    result.metrics = [
        ReportMetric("Elements with no connection", len(unconnected), gap=True),
        ReportMetric("Elements on no diagram", len(undrawn), gap=True),
    ]
    result.data = {"unconnected": len(unconnected), "not_on_a_diagram": len(undrawn)}
    return result


_ELEMENT = ReportParamDefinition(
    "element", "string", label="Element", description="Only the element with this code (for example ELM-003) or name.",
)
_TYPE = ReportParamDefinition("type", "string", label="Connection type", description="Only connections of the type with this name.")
_RECORDS = (ELEMENT_ARTEFACT_TYPE, CONNECTION_ARTEFACT_TYPE)

DEFINITIONS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        "ar3", "interface-list", "Interface list",
        "Every connection with its two ends, type, protocol, direction and linked requirements.",
        collect_interface_list, subcomponent=CONNECTION_SUBCOMPONENT_KEY, params=(_ELEMENT, _TYPE),
        parts=(ReportPartDefinition("connections", "Connections"),), record_types=(*_RECORDS, REQUIREMENT_TYPE),
    ),
    ReportDefinition(
        "ar4", "element-breakdown", "Element breakdown", "The element tree: each element under its parent, with type, status and owner.",
        collect_element_breakdown, subcomponent=ELEMENT_SUBCOMPONENT_KEY, params=(_ELEMENT,),
        parts=(ReportPartDefinition("tree", "Elements"),), record_types=(ELEMENT_ARTEFACT_TYPE,),
    ),
    ReportDefinition(
        "ar6", "unconnected-elements", "Unconnected elements", "Elements with no connection and elements that no diagram shows.",
        collect_unconnected_elements, subcomponent=ELEMENT_SUBCOMPONENT_KEY,
        parts=(ReportPartDefinition("unconnected", "Elements with no connection"), ReportPartDefinition("undrawn", "Elements on no diagram")),
        record_types=(ELEMENT_ARTEFACT_TYPE, DIAGRAM_ARTEFACT_TYPE),
    ),
)
