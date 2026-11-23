"""
Module: modules.product_feedback.record_attachments

Names the request's file-link table and record column for a custom report's
record-images block (`ModuleDefinition.record_attachments`). Only a record's
own attachments are listed, never a comment thread's files.
"""

from __future__ import annotations

from app.modules.product_feedback.models import EnhancementRequestFile
from app.modules.registry import RecordAttachmentProvider

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    "enhancement_request": RecordAttachmentProvider(EnhancementRequestFile, EnhancementRequestFile.request_id),
}

NO_RECORD_ATTACHMENTS: dict[str, str] = {}
