"""
Module: modules.decisions.record_attachments

Names the decision's file-link table and record column for a custom report's
record-images block (`ModuleDefinition.record_attachments`). Only a record's
own attachments are listed, never a comment thread's; a type whose attachments
may show identifiable people is declared in `NO_RECORD_ATTACHMENTS`.
"""

from __future__ import annotations

from app.modules.decisions.models import DecisionFile
from app.modules.registry import RecordAttachmentProvider

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    "decision": RecordAttachmentProvider(DecisionFile, DecisionFile.decision_id),
}

NO_RECORD_ATTACHMENTS: dict[str, str] = {}
