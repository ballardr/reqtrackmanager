"""
Module: services.report_starter_blocks

Small builders for the layout blocks of the starter report layouts, shared by the core starters
(`services.report_starters`) and by the sections modules contribute (`ModuleDefinition.report_starter_sections`).

Responsibilities:
- Name the starters (`BUSINESS_REQUIREMENTS_DOCUMENT`, `ENGINEERING_SPECIFICATION`, `REVIEW_PACKAGE`,
  `REQUIREMENTS_BY_COMPONENT`) so a module's
  section and the core assembler agree on a key.
- Build a heading, a line of text, a table over a record type, a widget and a headed section as layout-tree dicts.

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


def heading(text: str, level: int = 2) -> Node:
    """A heading block."""
    return {"type": "heading", "level": level, "text": text}


def text(value: str) -> Node:
    """A paragraph of the author's text."""
    return {"type": "text", "text": value}


def table(
    record_type: str, columns: list[tuple[str, str]], *, empty: str, where: list[Node] | None = None, sort: str = "code",
) -> Node:
    """A table of every record of `record_type` (not archived), one `(field, heading)` per column, ordered by `sort`.

    Args:
        record_type: A reportable artefact type.
        columns: `(field key, column heading)` pairs.
        empty: What to print when there are no records.
        where: Conditions the records must meet (all of them).
        sort: The field to order by.
    """
    source: Node = {"record_type": record_type, "sort": [{"field": sort}]}
    if where:
        source["where"] = where
    return {
        "type": "table", "source": source, "empty_text": empty,
        "columns": [{"field": field, "label": label} for field, label in columns],
    }


def widget(key: str, empty: str) -> Node:
    """A widget block (one component of a module report) that prints `empty` when it has nothing to show."""
    return {"type": "widget", "key": key, "empty_text": empty}


def section(title: str, intro: str, *body: Node) -> tuple[Node, ...]:
    """A level 2 heading, one line saying what the section is derived from, then `body`."""
    return (heading(title), text(intro), *body)
