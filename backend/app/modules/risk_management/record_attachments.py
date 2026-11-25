"""
Module: modules.risk_management.record_attachments

Names the risk's file-link table and record column for a custom report's
record-images block (`ModuleDefinition.record_attachments`). Only a record's
own attachments are listed, never a comment thread's.
"""

from __future__ import annotations

from app.modules.registry import RecordAttachmentProvider
from app.modules.risk_management.models import RiskFile

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    "risk": RecordAttachmentProvider(RiskFile, RiskFile.risk_id),
}

NO_RECORD_ATTACHMENTS: dict[str, str] = {}
