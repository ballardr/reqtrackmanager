"""
Module: services.report_starters

Starter report layouts: ready-made document layouts an organisation starts from.

Responsibilities:
- Declare the starters (`STARTERS`): a Business Requirements Document, an Engineering Specification, a
  Review Package and Requirements by Component. A starter holds the parts about core records and its own words; every other part is contributed
  by the module whose records it shows (`ModuleDefinition.report_starter_sections`) and merged in by `order`.
- Declare the Project Workbook, the one table-family starter: a sheet per reportable record type holding its core
  detail, generated from the report field registry (`workbook_tree`).
- `missing_starter_names`: which starters an organisation lacks (the UI offers adding only when one does).
- `add_starter_layouts`: write the starters an organisation does not yet have as ordinary organisation layouts.

Design decisions:
- **A starter is a normal organisation layout once written.** It is editable, versioned, hideable and
  deletable like any other, so an organisation adapts it instead of cloning it first. The platform's copy is the
  code below; an organisation's copy never changes behind its back.
- **Written by name, never overwritten.** A starter whose name the organisation already uses (its own layout, or
  an earlier copy it edited) is skipped, so adding starters again is safe and loses no edits. A later release's
  improved starter reaches an organisation only if it removes or renames its copy first.
- **Seeded at organisation creation, and on request for an existing organisation.** An upgrade seeds nothing by
  itself (the same rule as module defaults), so an organisation that already exists asks for them
  (`POST .../report-layouts/starters`).
- **No module is named here.** Naming another module's record types or reports in a core file would be a per-module
  hand-edit; the module registers its own parts, and a new module with something to say adds a part without a core
  change. The core wraps each part in `{"module": key}` (an `if` test, `services.report_layout_tree`), so a
  project where that module is off omits the part: no heading, no "none recorded" line that would be false.
- **The workbook is derived from the registry, not listed.** One `sheet` per reportable record type, columns from its
  core fields (`ReportField.core`, plus code, title, status and tags), each module's sheets wrapped in an `if` on that
  module like the document starters' parts, so a new module's type appears with no edit here and a project where the
  module is off has no sheet. A module that declares a type declares its core fields; a test fails for a type without one.
- **A document starter's headings use the colour name `primary`, and it carries no scheme of its own.** `primary` is one
  of the built-in Branding names (the organisation's report accent), so a starter prints in the accent with no scheme anywhere
  and follows the organisation's scheme the moment it names `primary`. Tables already take the accent for their header row.
  The body font is not set, so a starter keeps each format's own text face.
- **No link types and no project vocabulary.** A starter names none, so it runs in any project and organisation.
- Prose is the author's to edit: each section opens with a line saying what it is derived from, because a
  generated document is a derived output (never the source of truth) and a reader should know where to look.

Dependencies: `modules.registry` (starter sections), `services.report_layouts` (creating a layout),
`services.report_starter_blocks` (block builders).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.report_layout import FAMILY_DOCUMENT, FAMILY_TABLE, ReportLayout
from app.modules.registry import artefact_type_module, get_artefact_type_label, get_report_field_providers, get_report_starter_sections
from app.services import report_layouts
from app.services.report_fields import core_field_keys, provider_for
from app.services.report_layouts import LayoutNameTakenError
from app.services.report_starter_blocks import (
    BUSINESS_REQUIREMENTS_DOCUMENT,
    ENGINEERING_SPECIFICATION,
    REQUIREMENTS_BY_COMPONENT,
    REVIEW_PACKAGE,
    WORKBOOK,
    fixed_columns,
    heading,
    section,
    table,
    text,
)

Node = dict[str, Any]

#: The colour name every document starter's headings use: a built-in Branding name, so it resolves with no scheme anywhere.
STARTER_HEADING_COLOUR = "primary"

STARTER_NOTE = "Starter layout: edit it freely; adding the starters again never overwrites it."


@dataclass(frozen=True)
class StarterLayout:
    """One starter.

    Attributes:
        key: Its stable key (what modules' `ReportStarterSection.starter` names).
        name: The layout name it is written under (unique within an organisation).
        description: What the layout reports (stored as the layout's description).
        orientation: `portrait` or `landscape` (a document starter; ignored by a table one).
        core_parts: The parts about core records and the document's own words, as `(order, blocks)`.
        family: `document`, or `table` for the workbook (whose tree is generated from the field registry).
    """

    key: str
    name: str
    description: str
    orientation: str
    core_parts: tuple[tuple[int, tuple[Node, ...]], ...]
    family: str = FAMILY_DOCUMENT

    @property
    def tree(self) -> dict[str, Any]:
        """The layout tree.

        A document starter is the title, then the core parts and every registered module's parts in `order`, each
        module's part wrapped in an `if` on that module so a project where it is off leaves the part out. The workbook
        is generated from the report field registry (`workbook_tree`).
        """
        if self.family == FAMILY_TABLE:
            return workbook_tree()
        parts = [(order, list(blocks)) for order, blocks in self.core_parts]
        for module_key, contributed in get_report_starter_sections(self.key):
            parts.append((contributed.order, [{
                "type": "if", "when": {"module": module_key}, "children": list(contributed.nodes),
            }]))
        nodes: list[Node] = [
            {"type": "heading", "text": "{{report_title}}"},
            text(
                "Prepared for {{project_name}} on {{generated_on}}, derived from the project's records. "
                "It is a view of them, not a separate document to maintain."
            ),
        ]
        for _order, blocks in sorted(parts, key=lambda part: part[0]):
            nodes.extend(blocks)
        return {
            "schema_version": 1, "family": FAMILY_DOCUMENT, "orientation": self.orientation, "nodes": nodes,
            "styles": {"headings": {"colour": STARTER_HEADING_COLOUR}},
        }


BUSINESS_REQUIREMENTS = StarterLayout(
    key=BUSINESS_REQUIREMENTS_DOCUMENT,
    name="Business Requirements Document",
    description=(
        "Why the work is needed and what the business expects: Pain Points, stakeholders, needs, strategy, "
        "Future State, requirements, decisions and risks."
    ),
    orientation="portrait",
    core_parts=(
        (10, section("Purpose and scope", "Replace this paragraph with the purpose and boundaries of the work. The sections below are generated.")),
        (70, section(
            "Business Requirements",
            "The requirements that meet the needs above, with their approval status.",
            table(
                "requirement",
                [("code", "Code"), ("title", "Requirement"), ("description", "Description"), ("category", "Category"), ("status", "Status")],
                empty="No requirements recorded.",
            ),
        )),
        (130, section(
            "Approval and baseline",
            "The status column in each table above is the record's approval state when this document was generated. "
            "The version of every record included is kept with the run.",
        )),
    ),
)

SPECIFICATION = StarterLayout(
    key=ENGINEERING_SPECIFICATION,
    name="Engineering Specification",
    description=(
        "What the system must do and the context it is built in: requirements by component, needs, constraints, "
        "compliance obligations, decisions and traceability coverage."
    ),
    orientation="landscape",
    core_parts=(
        (10, section("Scope and system context", "Replace this paragraph with the scope and system context.")),
        (20, (
            heading("Requirement hierarchy"),
            text("Requirements grouped by component, with their level, category and status."),
            {
                "type": "group", "source": {"record_type": "requirement"}, "by": "component", "as": "comp",
                "children": [
                    heading("{{comp.value}} ({{comp.count}})", 3),
                    {
                        "type": "table", "source": {"group": "comp", "sort": [{"field": "code"}]},
                        "columns": fixed_columns([
                            ("code", "Code"), ("title", "Requirement"), ("description", "Description"), ("level", "Level"),
                            ("category", "Category"), ("status", "Status"),
                        ]),
                        "empty_text": "No requirements.",
                    },
                ],
            },
        )),
        (30, (
            heading("Requirement types"),
            text("How many requirements each category holds."),
            {
                "type": "group", "source": {"record_type": "requirement"}, "by": "category", "as": "cat",
                "children": [text("**{{cat.value}}**: {{cat.count}}")],
            },
        )),
        (90, section(
            "Revision information",
            "Each requirement's review date and status when this document was generated. "
            "The version of every record included is kept with the run.",
            table(
                "requirement",
                [("code", "Code"), ("title", "Requirement"), ("status", "Status"), ("review_date", "Review date"), ("reviewer", "Reviewer")],
                empty="No requirements recorded.",
            ),
        )),
    ),
)

REVIEW = StarterLayout(
    key=REVIEW_PACKAGE,
    name="Review Package",
    description=(
        "What needs a person's review now: requirements awaiting review or approval, change requests, decisions "
        "awaiting approval, open questions and overdue risk reviews."
    ),
    orientation="landscape",
    core_parts=(
        (10, section(
            "Requirements awaiting review or approval",
            "Requirements still in draft or reviewed, not yet approved.",
            table(
                "requirement",
                [("code", "Code"), ("title", "Requirement"), ("status", "Status"), ("owner", "Owner"),
                 ("reviewer", "Reviewer"), ("review_date", "Review date")],
                empty="No requirements are awaiting review.",
                where=[{"field": "status", "op": "in", "value": ["draft", "reviewed"]}],
            ),
        )),
        (20, section(
            "Change requests under review",
            "Change requests submitted or in review.",
            table(
                "change_request",
                [("code", "Code"), ("title", "Change request"), ("kind", "Kind"), ("status", "Status"), ("submitted_at", "Submitted")],
                empty="No change requests are under review.",
                where=[{"field": "status", "op": "in", "value": ["submitted", "in_review"]}],
            ),
        )),
    ),
)

BY_COMPONENT = StarterLayout(
    key=REQUIREMENTS_BY_COMPONENT,
    name="Requirements by Component",
    description=(
        "Every requirement grouped by component and then category, with its reasoning, status and tags: the "
        "requirements report as a layout, ready for an introduction, chapters and appendices."
    ),
    orientation="portrait",
    core_parts=(
        (10, section("Introduction", "Replace this paragraph with the purpose and scope of the requirements below.")),
        (20, (
            {
                "type": "group", "source": {"record_type": "requirement"}, "by": "component", "as": "comp",
                "children": [
                    heading("{{comp.value}}", 2),
                    {
                        "type": "group", "source": {"group": "comp"}, "by": "category", "as": "cat",
                        "children": [
                            heading("{{cat.value}}", 3),
                            {
                                "type": "table", "source": {"group": "cat", "sort": [{"field": "code"}]},
                                "columns": fixed_columns([
                                    ("code", "ID"), ("title", "Name"), ("reasoning", "Reasoning"), ("status", "Status"), ("tags", "Tags"),
                                ]),
                                "empty_text": "No requirements.",
                            },
                        ],
                    },
                ],
            },
        )),
        (90, section("Appendices", "Replace this paragraph with any supporting material.")),
    ),
)

#: Column widths of a workbook sheet, by field key, else by field kind. Absolute (a share of the sheet would have to add up to
#: at most 100% however many core fields a type declares), and enough to read a value without opening the cell.
_SHEET_WIDTH_BY_KEY = {"code": "2.5 cm", "title": "8 cm", "status": "3 cm", "tags": "4 cm"}
_SHEET_WIDTH_BY_KIND = {"text": "12 cm", "principal": "4 cm", "date": "3 cm", "instant": "4 cm", "enum": "3 cm"}

#: Most characters of a sheet name (a spreadsheet tab).
_SHEET_NAME_LIMIT = 31


def _sheet_names(artefact_types: list[str]) -> dict[str, str]:
    """A distinct tab name per record type: its display label cut to the tab limit, numbered if two collide."""
    names: dict[str, str] = {}
    taken: set[str] = set()
    for artefact_type in artefact_types:
        base = get_artefact_type_label(artefact_type)[:_SHEET_NAME_LIMIT].strip()
        name, n = base, 1
        while name.casefold() in taken:
            n += 1
            suffix = f" {n}"
            name = base[: _SHEET_NAME_LIMIT - len(suffix)].rstrip() + suffix
        taken.add(name.casefold())
        names[artefact_type] = name
    return names


def _workbook_columns(artefact_type: str) -> list[Node]:
    """The columns of a type's sheet: code, title, status, tags, then its core fields, each with a width."""
    kinds = {f.key: f.kind for f in provider_for(artefact_type).fields}
    columns: list[Node] = []
    for key in core_field_keys(artefact_type):
        width = _SHEET_WIDTH_BY_KEY.get(key) or _SHEET_WIDTH_BY_KIND.get(kinds.get(key, ""))
        columns.append({"field": key, **({"width": width} if width else {})})
    return columns


def workbook_tree() -> dict[str, Any]:
    """The Project Workbook layout tree: a sheet of core detail per reportable record type, with a contents sheet.

    Types come from the report field registry (core first, then each module's), so a type a new module registers gets
    its sheet with no edit here. A module's sheets are each wrapped in an `if` on that module (a project where the
    module is off has no such sheet); a core type's sheet is always there.

    Returns:
        A valid table-family tree.
    """
    artefact_types = list(get_report_field_providers())
    names = _sheet_names(artefact_types)
    nodes: list[Node] = []
    for artefact_type in artefact_types:
        sheet: Node = {
            "type": "sheet", "name": names[artefact_type],
            "source": {"record_type": artefact_type, "sort": [{"field": "code"}]},
            "columns": _workbook_columns(artefact_type),
        }
        owner = artefact_type_module(artefact_type)
        nodes.append(sheet if owner is None else {"type": "if", "when": {"module": owner.key}, "children": [sheet]})
    return {"schema_version": 1, "family": FAMILY_TABLE, "contents_sheet": True, "nodes": nodes}


WORKBOOK_STARTER = StarterLayout(
    key=WORKBOOK,
    name="Project Workbook",
    description=(
        "One sheet per kind of record in the project, each listing every record's code, title, status, tags and core "
        "detail (who answers for it and what it is): the project's records in one spreadsheet."
    ),
    orientation="portrait",
    core_parts=(),
    family=FAMILY_TABLE,
)

STARTERS: tuple[StarterLayout, ...] = (BUSINESS_REQUIREMENTS, SPECIFICATION, REVIEW, BY_COMPONENT, WORKBOOK_STARTER)
"""Every starter, in the order they are written and listed."""


def missing_starter_names(db: Session, organization_id: uuid.UUID) -> list[str]:
    """Lists the starters the organisation does not have as an organisation layout (by name, case-insensitive).

    Args:
        db: Active session.
        organization_id: The organisation.

    Returns:
        The names `add_starter_layouts` would write, in `STARTERS` order; empty when every starter is present.
    """
    taken = {
        name.casefold()
        for (name,) in db.execute(
            select(ReportLayout.name).where(ReportLayout.organization_id == organization_id, ReportLayout.project_id.is_(None))
        )
    }
    return [starter.name for starter in STARTERS if starter.name.casefold() not in taken]


def add_starter_layouts(db: Session, organization_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> list[str]:
    """Writes the starters the organisation does not have yet as organisation layouts.

    Args:
        db: Active session (flushed, not committed).
        organization_id: The organisation.
        actor_id: The user who asked, or `None` at organisation creation.

    Returns:
        The names written, in `STARTERS` order; a starter whose name the organisation already uses is skipped.

    Raises:
        InvalidLayoutError: A starter tree no longer validates (a bug; caught by the tests).
    """
    written: list[str] = []
    for starter in STARTERS:
        try:
            report_layouts.create_layout(
                db, organization_id=organization_id, project_id=None, name=starter.name, description=starter.description,
                family=starter.family, tree=starter.tree, actor_id=actor_id, comment=STARTER_NOTE,
            )
        except LayoutNameTakenError:
            continue
        written.append(starter.name)
    return written


__all__ = ["STARTERS", "STARTER_NOTE", "StarterLayout", "WORKBOOK_STARTER", "add_starter_layouts", "missing_starter_names", "workbook_tree"]
