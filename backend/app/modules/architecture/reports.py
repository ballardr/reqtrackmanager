"""
Module: modules.architecture.reports

Report data layer for System Architecture: one project-level report, `collect_boundary_coverage`, plus the
`REPORT_DEFINITIONS` that declare it to the registry. Result shapes, scope, rendering, routes, the MCP tool and the
catalogue live in `app.services.report_framework`, so this module is a declaration and a query.

Reports, in key order: AR1 Boundary coverage (here: the connections that cross an element's boundary and the inner
connections that realise each), AR2 Allocation coverage (`reports_allocation`), AR3 Interface list, AR4 Element
breakdown and AR6 Unconnected elements (`reports_structure`), AR5 Diagram and AR7 State machines, which carry a
drawing (`reports_drawing`).

Design decisions (all Decided by: Agent unless stated):
- **Neutral wording (Decided by: User).** A connection is "Covered" or "Not covered"; nothing is called a defect or a
  warning. The "Not covered" table is flagged as a gap table only so a summary pack can re-list it.
- **A connection is outer for an element when exactly one of its ends lies inside the element** (the element itself or
  a descendant), found from the symmetric difference of the two ends' ancestor chains, so the cost is the connections
  times the tree depth however many elements there are.
- **Only elements of the reported projects are named.** An end owned by another project or the organisation (a shared
  element) is shown as "Shared element" with no code or name, so the report discloses nothing the reader's project
  access does not already cover.
- Read-only and not audit-logged (framework rule); archived and retired connections are left out.

Dependencies: `app.services.report_framework`, `app.modules.registry`, this module's models and `diagram_resolver`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.architecture.labels import INACTIVE_STATUSES
from app.modules.architecture.models import ArchitectureConnection, ArchitectureConnectionType, ArchitectureElement
from app.modules.architecture.realisations import realisations_of
from app.modules.architecture.report_support import chain_of, element_text
from app.modules.architecture.reports_allocation import DEFINITION as ALLOCATION_COVERAGE
from app.modules.architecture.reports_drawing import DEFINITIONS as DRAWING_REPORTS
from app.modules.architecture.reports_structure import DEFINITIONS as STRUCTURE_REPORTS
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_SUBCOMPONENT_KEY,
    ELEMENT_ARTEFACT_TYPE,
)
from app.modules.registry import ReportDefinition, ReportParamDefinition, ReportPartDefinition
from app.services.report_framework import ReportContext, ReportMetric, ReportResult, ReportSection, build_report_routers

MODULE_KEY = ARCHITECTURE_MODULE_KEY

COLUMNS = ["Element", "Connection", "Name", "Type", "Direction", "Outside element", "Coverage", "Realised by", "Project"]
_CLIP = 120


def collect_boundary_coverage(db: Session, req: ReportContext) -> ReportResult:
    """AR1 — the connections crossing each element's boundary and whether anything realises them.

    Args:
        db: Database session.
        req: The request; `element` (a code, such as `ELM-003`, or a name) limits the report to one element, otherwise
            every element that contains other elements is covered.

    Returns:
        The report; `data` is `{"outer": int, "covered": int, "not_covered": int}`.
    """
    projects = req.eligible(db, CONNECTION_SUBCOMPONENT_KEY)
    wanted = (req.params.get("element") or "").strip().casefold()
    outer_rows: list[list[str]] = []
    open_rows: list[list[str]] = []
    covered = 0
    for project in projects:
        elements = {
            e.id: e for e in db.scalars(select(ArchitectureElement).where(ArchitectureElement.project_id == project.id))
        }
        parents = {i: e.parent_id for i, e in elements.items()}
        connections = list(db.scalars(
            select(ArchitectureConnection).where(
                ArchitectureConnection.project_id == project.id, ArchitectureConnection.is_archived.is_(False),
                ArchitectureConnection.status.not_in(INACTIVE_STATUSES),
            ).order_by(ArchitectureConnection.unique_code)
        ))
        for_end = {e for c in connections for e in (c.source_element_id, c.target_element_id)} - set(elements)
        # An end that is another owner's element has no known parent chain here; it is its own root.
        parents.update({i: None for i in for_end})
        types = {t.id: t for t in db.scalars(select(ArchitectureConnectionType).where(
            ArchitectureConnectionType.id.in_({c.connection_type_id for c in connections})
        ))} if connections else {}
        by_id = {c.id: c for c in connections}
        realisers: dict[uuid.UUID, list[str]] = {}
        for link in realisations_of(db, by_id):
            inner = by_id.get(link.inner_connection_id)
            if inner is not None and link.outer_connection_id in by_id:
                realisers.setdefault(link.outer_connection_id, []).append(req.code(inner.unique_code, project.id))

        scopes: dict[uuid.UUID, list[tuple[ArchitectureConnection, uuid.UUID]]] = {}
        for c in connections:
            source_chain, target_chain = chain_of(parents, c.source_element_id), chain_of(parents, c.target_element_id)
            for crossed in set(source_chain) ^ set(target_chain):
                if crossed in elements:
                    scopes.setdefault(crossed, []).append((c, c.source_element_id if crossed in source_chain else c.target_element_id))
        has_children = {e.parent_id for e in elements.values() if e.parent_id is not None}
        for scope_id in sorted(scopes, key=lambda i: elements[i].unique_code):
            scope = elements[scope_id]
            if wanted:
                if wanted not in (scope.unique_code.casefold(), scope.name.casefold()):
                    continue
            elif scope_id not in has_children:
                continue
            for c, side in scopes[scope_id]:
                scope_is_source = side == c.source_element_id
                kind = types.get(c.connection_type_id)
                direction = "Two-way" if kind is None or not kind.directional else ("Output" if scope_is_source else "Input")
                outside = c.target_element_id if scope_is_source else c.source_element_id
                by = realisers.get(c.id, [])
                row = [
                    element_text(req, project.id, elements, scope_id), req.code(c.unique_code, project.id), c.name[:_CLIP],
                    kind.name if kind else "", direction, element_text(req, project.id, elements, outside),
                    "Covered" if by else "Not covered", ", ".join(by), project.name,
                ]
                outer_rows.append(row)
                if by:
                    covered += 1
                else:
                    open_rows.append(row)
    result = ReportResult(
        key="ar1", title="Boundary coverage", scope_label=req.scope_label, generated_at=datetime.now(UTC),
        notes=[
            req.scope_note,
            "An outer connection is one that crosses an element's boundary: exactly one of its ends is inside the element. "
            "It is Covered when at least one inner connection is marked as realising it.",
        ],
        sections=[
            ReportSection("outer", "Outer connections", COLUMNS, outer_rows),
            ReportSection("not_covered", "Not covered", COLUMNS, open_rows, gap=True),
        ],
        eligible_projects=len(projects),
    )
    result.metrics = [
        ReportMetric("Outer connections", len(outer_rows)),
        ReportMetric("Covered", covered),
        ReportMetric("Not covered", len(open_rows), gap=True),
    ]
    result.data = {"outer": len(outer_rows), "covered": covered, "not_covered": len(open_rows)}
    return result


_ELEMENT = ReportParamDefinition(
    "element", "string", label="Element",
    description="Only the element with this code (for example ELM-003) or name; by default every element that contains others.",
)

REPORT_DEFINITIONS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        "ar1", "boundary-coverage", "Boundary coverage",
        "For each element that contains others: the connections crossing its boundary, the inner connections that realise "
        "each, and the ones that nothing realises.",
        collect_boundary_coverage, subcomponent=CONNECTION_SUBCOMPONENT_KEY, params=(_ELEMENT,),
        parts=(ReportPartDefinition("outer", "Outer connections"), ReportPartDefinition("not_covered", "Not covered")),
        record_types=(ELEMENT_ARTEFACT_TYPE, CONNECTION_ARTEFACT_TYPE),
    ),
    ALLOCATION_COVERAGE,
    *STRUCTURE_REPORTS,
    *DRAWING_REPORTS,
)

# Project router for the module to include; there is no organisation-wide variant.
REPORT_ROUTERS = build_report_routers(MODULE_KEY, REPORT_DEFINITIONS)
