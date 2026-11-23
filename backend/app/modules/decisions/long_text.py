"""
Module: modules.decisions.long_text

Declares which long free-text columns hold Markdown and which stay plain and
why, wired into `ModuleDefinition.markdown_fields`/`plain_text_fields`
(`tests/test_long_text_inventory.py` fails for an undeclared column).
Decision text fields hold equations and the Decision's own pictures; comments
and template prompts do neither. Dependencies: this module's models,
`modules.registry`.
"""

from __future__ import annotations

from app.modules.decisions.edits import MARKDOWN_LIMITS
from app.modules.decisions.models import (
    Decision,
    DecisionComment,
    DecisionTemplateDefinition,
)
from app.modules.registry import MarkdownField, MarkdownImages, markdown_columns
from app.services.long_text_core import _PICKER, NOTE_LIMIT

MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *(
        MarkdownField(getattr(Decision, name), limit, math=True, images=MarkdownImages("decision", Decision.id))
        for name, limit in MARKDOWN_LIMITS.items()
    ),
    *markdown_columns(DecisionComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(DecisionTemplateDefinition,
        "context_prompt", "options_considered_prompt", "chosen_option_prompt", "rationale_prompt", "consequences_prompt",
        "assumptions_prompt", "constraints_prompt",
    ),
)

PLAIN_TEXT_FIELDS: dict[str, str] = {
    "decision_template_definitions.description": _PICKER,
}
