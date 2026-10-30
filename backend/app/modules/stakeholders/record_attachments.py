"""
Module: modules.stakeholders.record_attachments

The files attached to this module's records, for a custom report's record-images block
(`ModuleDefinition.record_attachments`).

Responsibilities:
- Name the file-link table and record column of the persona and the stakeholder need, and say why the other types print none.

Design decisions:
- Only a record's own attachments are listed, never a comment thread's files.
- A type whose attachments may show or concern identifiable people is not offered, and says so in
  `NO_RECORD_ATTACHMENTS`.

Dependencies: this module's file-link models, `modules.registry` (the provider type).
"""

from __future__ import annotations

from app.modules.registry import RecordAttachmentProvider
from app.modules.stakeholders.models import PersonaFile, StakeholderNeedFile

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    "persona": RecordAttachmentProvider(PersonaFile, PersonaFile.persona_id),
    "stakeholder_need": RecordAttachmentProvider(StakeholderNeedFile, StakeholderNeedFile.need_id),
}

NO_RECORD_ATTACHMENTS: dict[str, str] = {
    "stakeholder": "Attachments to a stakeholder may show or concern an identifiable person, so a report never prints them.",
    "engagement": "Attachments to an engagement record contact with identifiable people, so a report never prints them.",
    "stakeholder_group": "A stakeholder group has no attachments of its own.",
    "research_finding": "A research finding has no attachments of its own.",
}
