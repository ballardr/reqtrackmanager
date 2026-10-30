"""
Module: modules.decisions.record_attachments

The files attached to this module's records, for a custom report's record-images block
(`ModuleDefinition.record_attachments`).

Responsibilities:
- Name the decision's file-link table and record column.

Design decisions:
- Only a record's own attachments are listed, never a comment thread's files.
- A type whose attachments may show or concern identifiable people is not offered, and says so in
  `NO_RECORD_ATTACHMENTS`.

Dependencies: this module's file-link models, `modules.registry` (the provider type).
"""

from __future__ import annotations

from app.modules.decisions.models import DecisionFile
from app.modules.registry import RecordAttachmentProvider

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    "decision": RecordAttachmentProvider(DecisionFile, DecisionFile.decision_id),
}

NO_RECORD_ATTACHMENTS: dict[str, str] = {}
