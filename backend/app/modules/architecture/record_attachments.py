"""
Module: modules.architecture.record_attachments

Files attached to this module's records, for a custom report's record-images block
(`ModuleDefinition.record_attachments`).

Design decisions:
- Elements, connections and diagrams carry no file attachments, so each type gives a reason in
  `NO_RECORD_ATTACHMENTS`. The symbol library (an element type's drawing) is not an attachment.
"""

from __future__ import annotations

from app.modules.architecture.service import CONNECTION_ARTEFACT_TYPE, DIAGRAM_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE
from app.modules.registry import RecordAttachmentProvider

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {}

NO_RECORD_ATTACHMENTS: dict[str, str] = {
    ELEMENT_ARTEFACT_TYPE: "An element has no file attachments; its drawing comes from the symbol library.",
    CONNECTION_ARTEFACT_TYPE: "A connection has no file attachments.",
    DIAGRAM_ARTEFACT_TYPE: "A diagram has no file attachments; its drawing is rendered from the model (the diagram SVG).",
}
