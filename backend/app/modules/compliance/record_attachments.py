"""
Module: modules.compliance.record_attachments

The files attached to this module's records, for a custom report's record-images block
(`ModuleDefinition.record_attachments`).

Responsibilities:
- Name the evidence record's file-link table and record column, and say why the other compliance types print none.

Design decisions:
- Only a record's own attachments are listed, never a comment thread's files.
- A type whose attachments may show or concern identifiable people is not offered, and says so in
  `NO_RECORD_ATTACHMENTS`.

Dependencies: this module's file-link models, `modules.registry` (the provider type).
"""

from __future__ import annotations

from app.modules.compliance.models import ComplianceEvidenceFile
from app.modules.registry import RecordAttachmentProvider

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    "compliance_evidence": RecordAttachmentProvider(ComplianceEvidenceFile, ComplianceEvidenceFile.evidence_id),
}

NO_RECORD_ATTACHMENTS: dict[str, str] = {
    "compliance_requirement": "A standard's requirement has no attachments of its own; evidence files are attached to the evidence record.",
    "project_compliance_requirement": "A project's requirement has no attachments of its own; evidence files are attached to the evidence record.",
    "compliance_required_action_assessment": "An assessment has no attachments of its own; evidence files are attached to the evidence record.",
}
