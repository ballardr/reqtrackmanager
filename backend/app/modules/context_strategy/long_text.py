"""
Module: modules.context_strategy.long_text

Which long free-text columns of this module's tables hold Markdown, and which stay plain text and why. Wired into
`ModuleDefinition.markdown_fields` and `plain_text_fields`; `tests/test_long_text_inventory.py` fails for a long-text
column of these tables that is in neither.

Design decisions:
- Markdown is the default reading; a column stays plain only for a stated reason.
- A comment or short note is bounded by `NOTE_LIMIT`, a described record by the default limit.

Dependencies: this module's models and `modules.registry` (the declaration shapes).
"""

from __future__ import annotations

from app.modules.context_strategy.models import (
    FutureStateComment,
    FutureStateVersion,
    GuidingPrincipleComment,
    GuidingPrincipleVersion,
    OpenQuestion,
    OpenQuestionComment,
    PainPoint,
    PainPointComment,
    StrategyComment,
    StrategyVersion,
)
from app.modules.registry import MarkdownField, markdown_columns
from app.services.long_text_core import _CHANGE_NOTE, _PICKER, NOTE_LIMIT

MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *markdown_columns(FutureStateVersion, "current_state", "desired_state", "outcomes", "success_measures", "constraints", "assumptions"),
    *markdown_columns(GuidingPrincipleVersion, "principle_statement", "rationale"),
    *markdown_columns(OpenQuestion, "question", "context", "evidence"),
    *markdown_columns(PainPoint, "description", "source", "impact", "evidence"),
    *markdown_columns(StrategyVersion,
        "objective", "current_state", "desired_future_state", "rationale", "expected_outcomes", "constraints", "measures_of_success",
    ),
    *markdown_columns(FutureStateComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(GuidingPrincipleComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(OpenQuestionComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(PainPointComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(StrategyComment, "body", limit=NOTE_LIMIT),
)

PLAIN_TEXT_FIELDS: dict[str, str] = {
    "future_state_versions.change_note": _CHANGE_NOTE,
    "guiding_principle_versions.change_note": _CHANGE_NOTE,
    "strategy_versions.change_note": _CHANGE_NOTE,
    "pain_point_type_definitions.definition": _PICKER,
    "project_pain_point_types.definition_override": _PICKER,
}
