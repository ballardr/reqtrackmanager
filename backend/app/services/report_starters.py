"""
Module: services.report_starters

Starter report layouts: ready-made document layouts an organisation starts from.

Responsibilities:
- Declare the starters (`STARTERS`): a Business Requirements Document, an Engineering Specification and a
  Review Package. A starter holds the parts about core records and its own words; every other part is contributed
  by the module whose records it shows (`ModuleDefinition.report_starter_sections`) and merged in by `order`.
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

from sqlalchemy.orm import Session

from app.models.report_layout import FAMILY_DOCUMENT
from app.modules.registry import get_report_starter_sections
from app.services import report_layouts
from app.services.report_layouts import LayoutNameTakenError
from app.services.report_starter_blocks import (
    BUSINESS_REQUIREMENTS_DOCUMENT,
    ENGINEERING_SPECIFICATION,
    REVIEW_PACKAGE,
    heading,
    section,
    table,
    text,
)

Node = dict[str, Any]

STARTER_NOTE = "Starter layout: edit it freely; adding the starters again never overwrites it."


@dataclass(frozen=True)
class StarterLayout:
    """One starter.

    Attributes:
        key: Its stable key (what modules' `ReportStarterSection.starter` names).
        name: The layout name it is written under (unique within an organisation).
        description: What the layout reports (stored as the layout's description).
        orientation: `portrait` or `landscape`.
        core_parts: The parts about core records and the document's own words, as `(order, blocks)`.
    """

    key: str
    name: str
    description: str
    orientation: str
    core_parts: tuple[tuple[int, tuple[Node, ...]], ...]

    @property
    def tree(self) -> dict[str, Any]:
        """The layout tree: the title, then the core parts and every registered module's parts in `order`.

        A module's part is wrapped in an `if` on that module, so a project where it is off leaves the part out.
        """
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
        return {"schema_version": 1, "family": FAMILY_DOCUMENT, "orientation": self.orientation, "nodes": nodes}


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
                        "columns": [
                            {"field": "code", "label": "Code"}, {"field": "title", "label": "Requirement"},
                            {"field": "description", "label": "Description"}, {"field": "level", "label": "Level"},
                            {"field": "category", "label": "Category"}, {"field": "status", "label": "Status"},
                        ],
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

STARTERS: tuple[StarterLayout, ...] = (BUSINESS_REQUIREMENTS, SPECIFICATION, REVIEW)
"""Every starter, in the order they are written and listed."""


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
                family=FAMILY_DOCUMENT, tree=starter.tree, actor_id=actor_id, comment=STARTER_NOTE,
            )
        except LayoutNameTakenError:
            continue
        written.append(starter.name)
    return written


__all__ = ["STARTERS", "STARTER_NOTE", "StarterLayout", "add_starter_layouts"]
