"""
Module: services.record_attachments_core

The files attached to the core artefact types, as `RecordAttachmentProvider`s, for a report's record-images block.

Responsibilities:
- Name each core type's file-link table and record column (requirement and requirement action), and give the reason a
  core type's attachments are not printable (a change request has no direct attachments).

Design decisions:
- Core types register through the same mechanism as module types, in core code because core owns them; a module's
  types are registered by the module (`ModuleDefinition.record_attachments`), never listed here.
- Comment-thread files are not record attachments: a discussion is not the record's own content.

Dependencies: the core file-link models, `modules.registry` (the provider type).
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
