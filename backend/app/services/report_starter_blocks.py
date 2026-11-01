"""
Module: services.report_starter_blocks

Small builders for the layout blocks of the starter report layouts, shared by the core starters
(`services.report_starters`) and by the sections modules contribute (`ModuleDefinition.report_starter_sections`).

Responsibilities:
- Name the starters (`BUSINESS_REQUIREMENTS_DOCUMENT`, `ENGINEERING_SPECIFICATION`, `REVIEW_PACKAGE`,
  `REQUIREMENTS_BY_COMPONENT`, `WORKBOOK`) so a module's
  section and the core assembler agree on a key.
- Build a heading, a line of text, a table over a record type, a widget and a headed section as layout-tree dicts.
- Give a starter table fixed column widths (`fixed_columns`): a field with a usual width (a code, a status) keeps it, so the
  columns line up from one table to the next; the rest (titles) share what is left.

Design decisions:
- Pure dict builders with no imports, so a module can use them without a cycle through the services that load modules.
- A builder only shapes the tree; the layout validator (`services.report_layout_tree`) is what accepts or refuses it.

Dependencies: none.
"""

from __future__ import annotations

from typing import Any

Node = dict[str, Any]

BUSINESS_REQUIREMENTS_DOCUMENT = "business-requirements-document"
ENGINEERING_SPECIFICATION = "engineering-specification"
REVIEW_PACKAGE = "review-package"
REQUIREMENTS_BY_COMPONENT = "requirements-by-component"
WORKBOOK = "project-workbook"


def heading(text: str, level: int = 2) -> Node:
    """A heading block."""
    return {"type": "heading", "level": level, "text": text}


def text(value: str) -> Node:
    """A paragraph of the author's text."""
    return {"type": "text", "text": value}


#: The usual width of a column by field key (a share of the table); a field not listed shares what is left.
USUAL_WIDTHS: dict[str, str] = {
    "code": "12%", "status": "10%", "level": "8%", "category": "12%", "kind": "10%", "owner": "12%", "reviewer": "12%",
    "review_date": "11%", "submitted_at": "11%", "tags": "12%", "description": "30%", "reasoning": "30%",
}


def fixed_columns(pairs: list[tuple[str, str]] | list[tuple[str, str, str]]) -> list[Node]:
    """Table columns for `(field, heading)` pairs, each with its usual width (`USUAL_WIDTHS`).

    A `(field, heading, width)` triple states the width instead (`"auto"` for none).
    """
    built: list[Node] = []
    for pair in pairs:
        column: Node = {"field": pair[0], "label": pair[1]}
        width = pair[2] if len(pair) == 3 else USUAL_WIDTHS.get(pair[0])
        if width and width != "auto":
            column["width"] = width
        built.append(column)
    return built


def table(
    record_type: str, columns: list[tuple[str, str]] | list[tuple[str, str, str]], *, empty: str, where: list[Node] | None = None,
    sort: str = "code",
) -> Node:
    """A table of every record of `record_type` (not archived), one column per `(field, heading)`, ordered by `sort`.

    Args:
        record_type: A reportable artefact type.
        columns_: `(field key, column heading)` pairs, or `(field key, column heading, width)` triples (see `fixed_columns`).
        empty: What to print when there are no records.
        where: Conditions the records must meet (all of them).
        sort: The field to order by.
    """
    source: Node = {"record_type": record_type, "sort": [{"field": sort}]}
    if where:
        source["where"] = where
    return {
        "type": "table", "source": source, "empty_text": empty,
        "columns": fixed_columns(columns),
    }


def widget(key: str, empty: str) -> Node:
    """A widget block (one component of a module report) that prints `empty` when it has nothing to show."""
    return {"type": "widget", "key": key, "empty_text": empty}


def section(title: str, intro: str, *body: Node) -> tuple[Node, ...]:
    """A level 2 heading, one line saying what the section is derived from, then `body`."""
    return (heading(title), text(intro), *body)
