"""
Module: modules.stakeholders.long_text

Which long free-text columns of this module's tables hold Markdown, and which stay plain text and why. Wired into
`ModuleDefinition.markdown_fields` and `plain_text_fields`; `tests/test_long_text_inventory.py` fails for a long-text
column of these tables that is in neither.

Design decisions:
- Markdown is the default reading; a column stays plain only for a stated reason.
- A comment or short note is bounded by `NOTE_LIMIT`, a described record by the default limit.

Dependencies: this module's models and `modules.registry` (the declaration shapes).
"""

from __future__ import annotations

from app.modules.registry import MarkdownField, markdown_columns
from app.modules.stakeholders.models import (
    Engagement,
    EngagementComment,
    EngagementPrompt,
    PersonaComment,
    PersonaVersion,
    ResearchFinding,
    StakeholderComment,
    StakeholderGroup,
    StakeholderNeedComment,
    StakeholderNeedVersion,
    StakeholderVersion,
)
from app.services.long_text_core import _CHANGE_NOTE, NOTE_LIMIT

MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *markdown_columns(EngagementPrompt, "prompt", "response_notes"),
    *markdown_columns(Engagement, "purpose", "summary", "notes"),
    *markdown_columns(PersonaVersion,
        "description", "goals", "needs", "behaviours", "context_environment", "skills_proficiency", "frequency_of_use", "constraints",
    ),
    *markdown_columns(ResearchFinding, "description"),
    *markdown_columns(StakeholderGroup, "description"),
    *markdown_columns(StakeholderNeedVersion, "description", "rationale"),
    *markdown_columns(StakeholderVersion,
        "description", "interests", "responsibilities", "goals_needs", "priorities", "constraints", "workflows_scenarios", "contact_info",
        "availability_constraints",
    ),
    *markdown_columns(EngagementComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(PersonaComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(StakeholderComment, "body", limit=NOTE_LIMIT),
    *markdown_columns(StakeholderNeedComment, "body", limit=NOTE_LIMIT),
)

PLAIN_TEXT_FIELDS: dict[str, str] = {
    "persona_versions.change_note": _CHANGE_NOTE,
    "stakeholder_need_versions.change_note": _CHANGE_NOTE,
    "stakeholder_versions.change_note": _CHANGE_NOTE,
}
