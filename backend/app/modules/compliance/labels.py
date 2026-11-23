"""
Module: modules.compliance.labels

Sentence-cased labels for this module's enum wire values, read by `modules.compliance.reports` for the PDF and CSV
reports. They live here, not in the core `app.services.labels` (which holds only core enums), so the module owns its
display concerns; the frontend's equivalent maps in `frontend/src/modules/compliance/types.ts` are kept in sync manually
because the two are in different languages.

Casing follows the Australian Government Style Manual's minimal capitalisation (capitalise only the first word), as
`app.services.labels` does.
"""

from __future__ import annotations

COMPLIANCE_STANDARD_VERSION_STATUS_LABEL: dict[str, str] = {
    "draft": "Draft",
    "published": "Published",
    "retired": "Retired",
}

COMPLIANCE_STATUS_LABEL: dict[str, str] = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "compliant": "Compliant",
    "non_compliant": "Non-compliant",
    "blocked": "Blocked",
    "pending_review": "Pending review",
    "rejected": "Rejected",
}

COMPLIANCE_APPLICABILITY_LABEL: dict[str, str] = {
    "applicable": "Applicable",
    "not_applicable": "Not applicable",
}

COMPLIANCE_APPLICABILITY_SOURCE_LABEL: dict[str, str] = {
    "explicit": "Explicit",
    "inherited": "Inherited",
    "overridden": "Overridden",
}

COMPLIANCE_APPROVAL_STATE_LABEL: dict[str, str] = {
    "not_assessed": "Not assessed",
    "assessed": "Assessed",
    "pending_approval": "Pending approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "requires_reassessment": "Requires re-assessment",
}

COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL: dict[str, str] = {
    "no_expiry": "No expiry",
    "valid": "Valid",
    "expiring_soon": "Expiring soon",
    "expired": "Expired",
}

# Mirrors `COMPLIANCE_EVIDENCE_VALIDITY_STATE_TONE` in `frontend/src/modules/compliance/types.ts` by hand (a test pins it).
COMPLIANCE_EVIDENCE_VALIDITY_STATE_TONE: dict[str, str] = {
    "no_expiry": "muted",
    "valid": "accent",
    "expiring_soon": "warning",
    "expired": "danger",
}

COMPLIANCE_REVIEW_STATUS_LABEL: dict[str, str] = {
    "scheduled": "Scheduled",
    "completed": "Completed",
}

COMPLIANCE_REVIEW_OUTCOME_LABEL: dict[str, str] = {
    "satisfactory": "Satisfactory",
    "action_required": "Action required",
    "unsatisfactory": "Unsatisfactory",
}

COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL: dict[str, str] = {
    "upcoming": "Upcoming",
    "due": "Due",
    "overdue": "Overdue",
}

COMPLIANCE_OVERALL_STATE_LABEL: dict[str, str] = {
    "compliant": "Compliant",
    "non_compliant": "Non-compliant",
    "in_progress": "In progress",
    "not_applicable": "Not applicable",
}


def compliance_standard_version_status_label(value: str) -> str:
    return COMPLIANCE_STANDARD_VERSION_STATUS_LABEL.get(value, value)


def compliance_status_label(value: str) -> str:
    return COMPLIANCE_STATUS_LABEL.get(value, value)


def compliance_applicability_label(value: str) -> str:
    return COMPLIANCE_APPLICABILITY_LABEL.get(value, value)


def compliance_applicability_source_label(value: str) -> str:
    return COMPLIANCE_APPLICABILITY_SOURCE_LABEL.get(value, value)


def compliance_approval_state_label(value: str) -> str:
    return COMPLIANCE_APPROVAL_STATE_LABEL.get(value, value)


def compliance_evidence_validity_state_label(value: str) -> str:
    return COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL.get(value, value)


def compliance_review_status_label(value: str) -> str:
    return COMPLIANCE_REVIEW_STATUS_LABEL.get(value, value)


def compliance_review_outcome_label(value: str | None) -> str:
    return COMPLIANCE_REVIEW_OUTCOME_LABEL.get(value, value) if value else ""


def compliance_review_schedule_state_label(value: str | None) -> str:
    return COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL.get(value, value) if value else ""


def compliance_overall_state_label(value: str) -> str:
    return COMPLIANCE_OVERALL_STATE_LABEL.get(value, value)
