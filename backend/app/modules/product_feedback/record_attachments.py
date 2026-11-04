"""
Module: modules.product_feedback.record_attachments

The files attached to this module's records, for a custom report's record-images block
(`ModuleDefinition.record_attachments`).

Responsibilities:
- Name the request's file-link table and record column.

Design decisions:
- Only a record's own attachments are listed, never a comment thread's files.

Dependencies: this module's file-link models, `modules.registry` (the provider type).
"""

from __future__ import annotations

from app.modules.product_feedback.models import EnhancementRequestFile
from app.modules.registry import RecordAttachmentProvider

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    "enhancement_request": RecordAttachmentProvider(EnhancementRequestFile, EnhancementRequestFile.request_id),
}

NO_RECORD_ATTACHMENTS: dict[str, str] = {}
