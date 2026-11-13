"""
Module: modules.architecture.report_fields

The `ReportFieldProvider`s for the module's artefact types, so custom report layouts can print and
group elements, connections and diagrams.

Responsibilities:
- Declare the fields a layout may use: the searchable text fields, an element's owner (a principal)
  and a connection's protocol.

Design decisions:
- An element's owner is a user or a group, shown by name.

Dependencies: this module's models and search declarations; `services.report_fields` (builders).
"""

from __future__ import annotations

from app.modules.architecture.models import ArchitectureElement
from app.modules.architecture.search import SEARCH_PROVIDERS
from app.modules.architecture.service import CONNECTION_ARTEFACT_TYPE, DIAGRAM_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE
from app.modules.registry import ReportFieldProvider
from app.services.report_fields import from_search, principal_field

REPORT_FIELDS: dict[str, ReportFieldProvider] = {
    ELEMENT_ARTEFACT_TYPE: from_search(
        SEARCH_PROVIDERS[ELEMENT_ARTEFACT_TYPE],
        principal_field("owner", "Owner", ArchitectureElement.owner_type, ArchitectureElement.owner_id),
        core_fields=("description", "display_note", "owner"),
    ),
    CONNECTION_ARTEFACT_TYPE: from_search(
        SEARCH_PROVIDERS[CONNECTION_ARTEFACT_TYPE], core_fields=("description", "protocol"),
    ),
    DIAGRAM_ARTEFACT_TYPE: from_search(SEARCH_PROVIDERS[DIAGRAM_ARTEFACT_TYPE], core_fields=("description",)),
}
