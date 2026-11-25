"""
Module: modules.product_feedback.long_text

Declares which long free-text columns hold Markdown and which stay plain and
why, wired into `ModuleDefinition.markdown_fields`/`plain_text_fields`
(`tests/test_long_text_inventory.py` fails for an undeclared column). A
request's description holds equations; the decline reason, comments and notes
do not. Dependencies: this module's models, `modules.registry`.
"""

from __future__ import annotations

from app.modules.product_feedback.models import (
    EnhancementRequestComment,
    EnhancementRequestInformed,
    EnhancementRequestMerge,
    EnhancementRequestVersion,
)
from app.modules.registry import MarkdownField, MarkdownImages, markdown_columns
from app.services.long_text_core import _CHANGE_NOTE, NOTE_LIMIT

MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *markdown_columns(
        EnhancementRequestVersion, "description", math=True,
        images=MarkdownImages("enhancement_request", EnhancementRequestVersion.request_id),
    ),
    *markdown_columns(EnhancementRequestVersion, "decline_reason", limit=NOTE_LIMIT),
    *markdown_columns(EnhancementRequestComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(EnhancementRequestInformed, "note", limit=NOTE_LIMIT),
    *markdown_columns(EnhancementRequestMerge, "note", limit=NOTE_LIMIT),
)

PLAIN_TEXT_FIELDS: dict[str, str] = {
    "enhancement_request_versions.change_note": _CHANGE_NOTE,
}
