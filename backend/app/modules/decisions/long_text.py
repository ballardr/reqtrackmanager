"""
Module: modules.decisions.long_text

Which long free-text columns of this module's tables hold Markdown, and which stay plain text and why. Wired into
`ModuleDefinition.markdown_fields` and `plain_text_fields`; `tests/test_long_text_inventory.py` fails for a long-text
column of these tables that is in neither.

Design decisions:
- Markdown is the default reading; a column stays plain only for a stated reason.
- A comment or short note is bounded by `NOTE_LIMIT`, a described record by the default limit.
- A Decision's text fields hold equations (`math=True`); its comments and the template prompts (configuration text)
  do not.

Dependencies: this module's models and `modules.registry` (the declaration shapes).
"""

from __future__ import annotations

from app.modules.decisions.edits import MARKDOWN_LIMITS
from app.modules.decisions.models import (
    Decision,
    DecisionComment,
    DecisionTemplateDefinition,
)
from app.modules.registry import MarkdownField, markdown_columns
from app.services.long_text_core import _PICKER, NOTE_LIMIT

MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *(MarkdownField(getattr(Decision, name), limit, math=True) for name, limit in MARKDOWN_LIMITS.items()),
    *markdown_columns(DecisionComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(DecisionTemplateDefinition,
        "context_prompt", "options_considered_prompt", "chosen_option_prompt", "rationale_prompt", "consequences_prompt",
        "assumptions_prompt", "constraints_prompt",
    ),
)

PLAIN_TEXT_FIELDS: dict[str, str] = {
    "decision_template_definitions.description": _PICKER,
}
