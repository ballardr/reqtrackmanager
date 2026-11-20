"""
Module: modules.architecture.long_text

Which long free-text columns of this module's tables hold Markdown, and which stay plain text and why. Wired into
`ModuleDefinition.markdown_fields` and `plain_text_fields`; `tests/test_long_text_inventory.py` fails for a long-text
column of these tables that is in neither.

Design decisions:
- Markdown is the default reading; a column stays plain only for a stated reason.
- A comment or short note is bounded by `NOTE_LIMIT`, a described record by the default limit.

Dependencies: this module's models and `modules.registry` (the declaration shapes).
"""

from __future__ import annotations

from app.modules.architecture.models import (
    ArchitectureCollection,
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureElement,
    ArchitectureState,
    ArchitectureStateMachineDiagram,
    ArchitectureTransition,
)
from app.modules.registry import MarkdownField, markdown_columns

MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *markdown_columns(ArchitectureCollection, "description"),
    *markdown_columns(ArchitectureConnection, "description"),
    *markdown_columns(ArchitectureDiagram, "purpose"),
    *markdown_columns(ArchitectureElement, "description"),
    *markdown_columns(ArchitectureStateMachineDiagram, "description"),
    *markdown_columns(ArchitectureState, "description"),
    *markdown_columns(ArchitectureTransition, "description"),
)

PLAIN_TEXT_FIELDS: dict[str, str] = {
    "architecture_diagram_notes.text": "Text drawn inside a note shape on a diagram canvas, which exports as a diagram label.",
    "architecture_states.entry_action": (
        "Behaviour text drawn inside a state shape and exported as "
        "a label of the state machine diagram, so it is plain text."
    ),
    "architecture_states.exit_action": (
        "Behaviour text drawn inside a state shape and exported as "
        "a label of the state machine diagram, so it is plain text."
    ),
    "architecture_states.activity": (
        "Behaviour text drawn inside a state shape and exported as "
        "a label of the state machine diagram, so it is plain text."
    ),
}
