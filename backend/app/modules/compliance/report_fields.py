"""
Module: modules.compliance.report_fields

The `ReportFieldProvider`s for Compliance's four artefact types, so custom report layouts can print and
group clauses, evidence, a project's requirements and action assessments.

Responsibilities:
- Declare, per type, the text fields (from the search declaration) and the typed fields: evidence issue and
  expiry dates, an assessment's due date and completion flag.

Design decisions:
- A clause and a project requirement have no code of their own; their search declaration shows the clause
  reference in the code column and the report fields inherit that.
- Opt-in only; joins and identity columns come from the search declaration.

Dependencies: this module's models; `services.report_fields` (builders).
"""

from __future__ import annotations

from app.modules.compliance.models import ComplianceEvidence, ComplianceRequiredActionAssessment
from app.modules.compliance.search import SEARCH_PROVIDERS
from app.modules.registry import ReportFieldProvider
from app.services.report_fields import bool_field, date_field, from_search

REPORT_FIELDS: dict[str, ReportFieldProvider] = {
    "compliance_requirement": from_search(SEARCH_PROVIDERS["compliance_requirement"]),
    "compliance_evidence": from_search(
        SEARCH_PROVIDERS["compliance_evidence"],
        date_field("issued_date", "Issued", ComplianceEvidence.issued_date),
        date_field("expiry_date", "Expires", ComplianceEvidence.expiry_date),
    ),
    "project_compliance_requirement": from_search(SEARCH_PROVIDERS["project_compliance_requirement"]),
    "compliance_required_action_assessment": from_search(
        SEARCH_PROVIDERS["compliance_required_action_assessment"],
        date_field("due_date", "Due date", ComplianceRequiredActionAssessment.due_date),
        bool_field("is_completed", "Completed", ComplianceRequiredActionAssessment.is_completed),
    ),
}
