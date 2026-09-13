"""
Module: modules.compliance.labels

Human-readable, sentence-cased labels for this module's own enum wire values
— read by `modules.compliance.reports` when rendering the PDF/CSV compliance
reports. Split out of the core `app.services.labels` (which still holds only
`REQUIREMENT_STATUS_LABEL`, core's own enum) so this module owns every one of
its own display concerns, not just its data/service/router/schema layers —
the same "modules are self-contained" principle `resolve_file_owner_
project_id` (`app.modules.registry`) already applies to file-ownership
resolution. Mirrors the frontend's equivalent maps in
`frontend/src/modules/compliance/types.ts`; kept in sync by hand since the
two run in different languages, not generated from one shared source.

Casing follows the Australian Government Style Manual's "minimal
capitalisation" rule (sentence case: capitalise only the first word), the
same convention `app.services.labels` uses for core enums.
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
