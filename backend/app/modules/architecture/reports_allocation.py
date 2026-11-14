"""
Module: modules.architecture.reports_allocation

Report AR2 Allocation coverage: how far the requirements are allocated to elements, and what is left to decide.

Sections: requirements with no allocated element (with the elements suggested for each), elements no requirement is
allocated to, connections no requirement is linked to, and leaf elements with no owner.

Design decisions (Decided by: Agent):
- **One source of truth.** The requirement and element figures come from `allocation.coverage_gaps`, the function the
  overview tiles and the Allocation screens read, so a report cannot disagree with the screen.
- **A requirement counts once however many elements it names;** archived requirements, archived elements and retired
  elements are left out, as they are on the screens.
- Neutral wording, as for AR1: nothing is called a defect; every table is a gap table so a summary pack can re-list it.
- A leaf element is one with no child; an element is owned when it names a user or a group.

Dependencies: `allocation`, `report_support`, this module's models, `app.services.report_framework`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.relationship import ArtefactLink
from app.modules.architecture import allocation
from app.modules.architecture.labels import record_status_label
from app.modules.architecture.models import ArchitectureConnection, ArchitectureElementType
from app.modules.architecture.report_support import live_connections, project_elements
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_SUBCOMPONENT_KEY,
)
from app.modules.registry import ReportDefinition, ReportPartDefinition
from app.services.report_framework import ReportContext, ReportMetric, ReportResult, ReportSection

MODULE_KEY = ARCHITECTURE_MODULE_KEY
REQUIREMENT_COLUMNS = ["Requirement", "Name", "Status", "Suggested elements", "Project"]
ELEMENT_COLUMNS = ["Element", "Name", "Type", "Status", "Project"]
CONNECTION_COLUMNS = ["Connection", "Name", "Status", "Project"]


def _requirement_linked_connections(db: Session, connection_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The connections (of `connection_ids`) that have a requirement linked, in either direction."""
    if not connection_ids:
        return set()
    linked: set[uuid.UUID] = set()
    for link in db.scalars(select(ArtefactLink).where(
        ((ArtefactLink.source_type == CONNECTION_ARTEFACT_TYPE) & ArtefactLink.source_id.in_(connection_ids)
         & (ArtefactLink.target_type == allocation.REQUIREMENT_TYPE))
        | ((ArtefactLink.target_type == CONNECTION_ARTEFACT_TYPE) & ArtefactLink.target_id.in_(connection_ids)
           & (ArtefactLink.source_type == allocation.REQUIREMENT_TYPE))
    )):
        linked.add(link.source_id if link.source_type == CONNECTION_ARTEFACT_TYPE else link.target_id)
    return linked


def collect_allocation_coverage(db: Session, req: ReportContext) -> ReportResult:
    """AR2 — the allocation gaps of each reported project.

    Args:
        db: Database session.
        req: The request; no parameters.

    Returns:
        The report; `data` is the totals `requirements`, `unallocated_requirements`, `elements`, `unallocated_elements`,
        `connections`, `unlinked_connections`, `unowned_leaf_elements` and `suggestions`.
    """
    projects = req.eligible(db, ELEMENT_SUBCOMPONENT_KEY)
    requirement_rows: list[list[str]] = []
    element_rows: list[list[str]] = []
    connection_rows: list[list[str]] = []
    owner_rows: list[list[str]] = []
    totals = {"requirements": 0, "elements": 0, "connections": 0, "suggestions": 0}
    for project in projects:
        gaps = allocation.coverage_gaps(db, project)
        totals["requirements"] += gaps.requirements
        totals["elements"] += gaps.elements
        totals["suggestions"] += len(gaps.suggestions)
        suggested: dict[uuid.UUID, list[str]] = {}
        for pair in gaps.suggestions:
            suggested.setdefault(pair.requirement.id, []).append(req.code(pair.element.unique_code, project.id))
        for r in gaps.unallocated_requirements:
            requirement_rows.append([
                req.code(r.unique_code, project.id), r.name, r.status.replace("_", " ").capitalize(),
                ", ".join(suggested.get(r.id, [])), project.name,
            ])
        elements = project_elements(db, project.id)
        type_names = {t.id: t.name for t in db.scalars(select(ArchitectureElementType).where(
            ArchitectureElementType.id.in_({e.element_type_id for e in elements.values()})
        ))} if elements else {}
        for ref in gaps.unallocated_elements:
            element_rows.append([
                req.code(ref.unique_code, project.id), ref.name, type_names.get(elements[ref.id].element_type_id, ""),
                record_status_label(ref.status), project.name,
            ])
        parents = {e.parent_id for e in elements.values() if e.parent_id is not None}
        for e in elements.values():
            if e.id not in parents and e.owner_id is None:
                owner_rows.append([
                    req.code(e.unique_code, project.id), e.name, type_names.get(e.element_type_id, ""),
                    record_status_label(e.status), project.name,
                ])
        connections: list[ArchitectureConnection] = live_connections(db, project.id)
        totals["connections"] += len(connections)
        linked = _requirement_linked_connections(db, {c.id for c in connections})
        connection_rows += [
            [req.code(c.unique_code, project.id), c.name, record_status_label(c.status), project.name]
            for c in connections if c.id not in linked
        ]
    result = ReportResult(
        key="ar2", title="Allocation coverage", scope_label=req.scope_label, generated_at=datetime.now(UTC),
        notes=[
            req.scope_note,
            "A requirement is allocated when it is linked to at least one element; suggestions come from an element's "
            "place in the requirement's component and become allocations only when accepted.",
        ],
        sections=[
            ReportSection("requirements", "Requirements with no allocated element", REQUIREMENT_COLUMNS, requirement_rows, gap=True),
            ReportSection("elements", "Elements with no requirement", ELEMENT_COLUMNS, element_rows, gap=True),
            ReportSection("connections", "Connections with no requirement", CONNECTION_COLUMNS, connection_rows, gap=True),
            ReportSection("unowned", "Leaf elements with no owner", ELEMENT_COLUMNS, owner_rows, gap=True),
        ],
        eligible_projects=len(projects),
    )
    result.metrics = [
        ReportMetric("Requirements", totals["requirements"]),
        ReportMetric("Requirements not allocated", len(requirement_rows), gap=True),
        ReportMetric("Elements", totals["elements"]),
        ReportMetric("Elements with no requirement", len(element_rows), gap=True),
        ReportMetric("Connections with no requirement", len(connection_rows), gap=True),
        ReportMetric("Leaf elements with no owner", len(owner_rows), gap=True),
        ReportMetric("Suggested allocations", totals["suggestions"]),
    ]
    result.data = {
        "requirements": totals["requirements"], "unallocated_requirements": len(requirement_rows),
        "elements": totals["elements"], "unallocated_elements": len(element_rows),
        "connections": totals["connections"], "unlinked_connections": len(connection_rows),
        "unowned_leaf_elements": len(owner_rows), "suggestions": totals["suggestions"],
    }
    return result


DEFINITION = ReportDefinition(
    "ar2", "allocation-coverage", "Allocation coverage",
    "Requirements with no allocated element, elements and connections with no requirement, and leaf elements with no owner.",
    collect_allocation_coverage, subcomponent=ELEMENT_SUBCOMPONENT_KEY,
    parts=(
        ReportPartDefinition("requirements", "Requirements with no allocated element"),
        ReportPartDefinition("elements", "Elements with no requirement"),
        ReportPartDefinition("connections", "Connections with no requirement"),
        ReportPartDefinition("unowned", "Leaf elements with no owner"),
    ),
    record_types=(allocation.REQUIREMENT_TYPE, ELEMENT_ARTEFACT_TYPE, CONNECTION_ARTEFACT_TYPE),
)
