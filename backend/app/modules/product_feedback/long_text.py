"""
Module: modules.product_feedback.long_text

Which long free-text columns of this module's tables hold Markdown, and which stay plain text and why. Wired into
`ModuleDefinition.markdown_fields` and `plain_text_fields`; `tests/test_long_text_inventory.py` fails for a long-text
column of these tables that is in neither.

Design decisions:
- Markdown is the default reading; a column stays plain only for a stated reason.
- A comment or short note is bounded by `NOTE_LIMIT`, a described record by the default limit.
- A request's description holds equations (`math=True`); its decline reason (entered in the shared status dialog), comments and notes do not.

Dependencies: this module's models and `modules.registry` (the declaration shapes).
"""

from __future__ import annotations

from app.modules.product_feedback.models import (
    EnhancementRequestComment,
    EnhancementRequestInformed,
    EnhancementRequestMerge,
    EnhancementRequestVersion,
)
from app.modules.registry import MarkdownField, markdown_columns
from app.services.long_text_core import _CHANGE_NOTE, NOTE_LIMIT

MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *markdown_columns(EnhancementRequestVersion, "description", math=True),
    *markdown_columns(EnhancementRequestVersion, "decline_reason", limit=NOTE_LIMIT),
    *markdown_columns(EnhancementRequestComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(EnhancementRequestInformed, "note", limit=NOTE_LIMIT),
    *markdown_columns(EnhancementRequestMerge, "note", limit=NOTE_LIMIT),
)

PLAIN_TEXT_FIELDS: dict[str, str] = {
    "enhancement_request_versions.change_note": _CHANGE_NOTE,
}
