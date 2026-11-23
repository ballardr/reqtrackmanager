"""
Module: services.record_attachments_core

The files attached to the core artefact types, as `RecordAttachmentProvider`s, for a report's record-images block.

Responsibilities:
- Name each core type's file-link table and record column (requirement, requirement action) and give the reason a
  change request's attachments are not printable (it has none directly).

Design decisions:
- Core owns these types, so they register here; a module registers its types through `ModuleDefinition.record_attachments`.
- Comment-thread files are not record attachments: a discussion is not the record's own content.

Dependencies: the core file-link models, `modules.registry`.
"""

from __future__ import annotations

from app.models.file import RequirementActionFile, RequirementFile
from app.modules.registry import RecordAttachmentProvider

CORE_RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    "requirement": RecordAttachmentProvider(RequirementFile, RequirementFile.requirement_id),
    "requirement_action": RecordAttachmentProvider(RequirementActionFile, RequirementActionFile.action_id),
}

CORE_NO_RECORD_ATTACHMENTS: dict[str, str] = {
    "change_request": "A change request has no attachments of its own; files go on its discussion, which a report does not print.",
}

__all__ = ["CORE_NO_RECORD_ATTACHMENTS", "CORE_RECORD_ATTACHMENTS"]
