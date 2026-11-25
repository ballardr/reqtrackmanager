"""
Module: modules.compliance.long_text

Which long free-text columns of this module's tables hold Markdown, and which stay plain text and why. Wired into
`ModuleDefinition.markdown_fields` and `plain_text_fields`; `tests/test_long_text_inventory.py` fails for a long-text
column of these tables that is in neither.

Design decisions:
- Markdown is the default reading; a column stays plain only for a stated reason.
- A comment or short note is bounded by `NOTE_LIMIT`, a described record by the default limit.

Dependencies: this module's models and `modules.registry` (the declaration shapes).
"""

from __future__ import annotations

from app.modules.compliance.models import (
    ComplianceEvidence,
    ComplianceEvidenceRevalidation,
    ComplianceRequiredAction,
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ComplianceRequirementMapping,
    ComplianceReview,
    ComplianceStandard,
    ComplianceStandardDefaultExclusion,
    ComplianceStandardVersion,
    ProjectComplianceRequirement,
)
from app.modules.registry import MarkdownField, MarkdownImages, markdown_columns
from app.services.long_text_core import _CHANGE_NOTE, NOTE_LIMIT

MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *markdown_columns(
        ComplianceEvidence, "description", "notes", images=MarkdownImages("compliance_evidence", ComplianceEvidence.id),
    ),
    *markdown_columns(ComplianceEvidenceRevalidation, "justification", limit=NOTE_LIMIT),
    *markdown_columns(ComplianceRequiredActionAssessment, "notes", limit=NOTE_LIMIT),
    *markdown_columns(ComplianceRequiredAction, "description"),
    *markdown_columns(ComplianceRequirementMapping, "notes", limit=NOTE_LIMIT),
    *markdown_columns(ComplianceRequirement, "description", "reasoning"),
    *markdown_columns(ComplianceRequirement, "last_clarification_note", limit=NOTE_LIMIT),
    *markdown_columns(ComplianceReview, "notes", limit=NOTE_LIMIT),
    *markdown_columns(ComplianceStandardDefaultExclusion, "reason", limit=NOTE_LIMIT),
    *markdown_columns(ComplianceStandardVersion, "summary"),
    *markdown_columns(ComplianceStandard, "description"),
    *markdown_columns(ProjectComplianceRequirement, "justification", "notes", "decision_note", limit=NOTE_LIMIT),
)

PLAIN_TEXT_FIELDS: dict[str, str] = {
    "compliance_standard_versions.change_note": _CHANGE_NOTE,
}
