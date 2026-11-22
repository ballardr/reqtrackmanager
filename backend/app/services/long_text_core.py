"""
Module: services.long_text_core

Which long free-text columns of the core tables hold Markdown, and which stay plain text and why.

Responsibilities:
- Declare, for every long-text column of a core table (a `Text` column, or a string of 1,000 characters or more), either a
  `MarkdownField` or a reason it stays plain text. A module declares its own tables' columns on its
  `ModuleDefinition` (`markdown_fields`, `plain_text_fields`); nothing here names a module's table.
- Feed the inventory (`scripts/generate_long_text_inventory.py`) and the write-time limits (`services.markdown_fields`).

Design decisions:
- A new long-text column is a failing test (`tests/test_long_text_inventory.py`) until it is declared here or on its
  module, the same way a new record type is for search.
- Markdown is the default reading. A column stays plain only for a reason of the kind below: text drawn inside a
  shape or printed in a fixed layout (a footer line), configuration text shown in a picker or tooltip (one line, no
  block formatting), a version's one-line change note (listed in histories, audit events and notifications), or a
  system-generated message.
- A requirement's description, reasoning and clarification, a change request's proposed copies and reason, and the
  descriptive fields of the other record types (decisions, feedback, open questions, pain points) hold equations, so
  they are `math=True`. Comments, one-line notes and text entered through a shared comment or checklist control (a
  decision note, a vote's comment, a decline reason, a task) stay without.

Dependencies: the core models and `modules.registry` (the declaration shapes).
"""

from __future__ import annotations

from app.models.announcement import Announcement
from app.models.change_request import (
    ChangeRequest,
    ChangeRequestProposedLink,
    ChangeRequestTask,
    ChangeRequestVersion,
    ChangeRequestVote,
    ReviewComment,
)
from app.models.project import StageReviewResponse
from app.models.record_comment import RecordComment
from app.models.requirement import RequirementReview, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.modules.registry import MarkdownField, markdown_columns

#: Comments and short notes are bounded lower than a described record.
NOTE_LIMIT = 20_000

CORE_MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *markdown_columns(Announcement, "body"),
    *markdown_columns(RequirementVersion, "reasoning", "clarification", "description", math=True),
    *markdown_columns(RequirementAction, "description"),
    *markdown_columns(RequirementReview, "comment", limit=NOTE_LIMIT),
    *markdown_columns(
        ChangeRequestVersion, "proposed_reasoning", "proposed_clarification", "proposed_description", math=True,
    ),
    *markdown_columns(ChangeRequestVersion, "proposed_action_description"),
    *markdown_columns(ChangeRequestVersion, "reason", limit=NOTE_LIMIT, math=True),
    *markdown_columns(ChangeRequestProposedLink, "outcome_reason", limit=NOTE_LIMIT),
    *markdown_columns(ChangeRequestTask, "description"),
    *markdown_columns(ChangeRequestVote, "comment", limit=NOTE_LIMIT),
    *markdown_columns(ChangeRequest, "decision_note", limit=NOTE_LIMIT),
    *markdown_columns(ReviewComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(StageReviewResponse, "comment", limit=NOTE_LIMIT),
    *markdown_columns(RecordComment, "body", limit=NOTE_LIMIT),
)

_CHANGE_NOTE = "A version's one-line change note, listed in version histories, audit events and notifications."
_PICKER = "Configuration text shown in pickers and tooltips, which cannot draw block formatting."

CORE_PLAIN_TEXT_FIELDS: dict[str, str] = {
    "notifications.body": "System-generated message text, shown in the bell, the list and an email as plain text.",
    "organizations.report_footer_text": "A line printed in a report's page footer, which is fixed plain text.",
    "organizations.email_footer_address": "The address block printed in the footer of every email, which is plain text.",
    "server_settings.email_footer_address": "The address block printed in the footer of every email, which is plain text.",
    "policy_document_versions.change_note": _CHANGE_NOTE,
    "requirement_versions.change_note": _CHANGE_NOTE,
    "projects.summary": (
        "Shown in project cards, pickers and the project header, which are one-line plain-text surfaces; limited to "
        "2,000 characters."
    ),
    "custom_role_definitions.description": _PICKER,
    "module_role_definitions.description": _PICKER + " Defined in the module's code.",
    "report_layouts.description": _PICKER,
    "report_packs.description": _PICKER,
    "report_snippets.description": _PICKER,
    "scoring_custom_axes.description": _PICKER,
    "scoring_levels.description": _PICKER,
}
