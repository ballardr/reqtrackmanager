"""
Module: modules.product_feedback.report_fields

The `ReportFieldProvider` for the `enhancement_request` artefact type, so custom report layouts can print and
group requests.

Responsibilities:
- Declare the request fields a layout may use: the description (from the search declaration) and the owner,
  read from the current version.

Design decisions:
- The owner is a principal (a user or a group), shown by name.

Dependencies: this module's models; `services.report_fields` (builders).
"""

from __future__ import annotations

from app.modules.product_feedback.models import EnhancementRequestVersion
from app.modules.product_feedback.search import SEARCH_PROVIDERS
from app.modules.registry import ReportFieldProvider
from app.services.report_fields import from_search, principal_field

REPORT_FIELDS: dict[str, ReportFieldProvider] = {
    "enhancement_request": from_search(
        SEARCH_PROVIDERS["enhancement_request"],
        principal_field("owner", "Owner", EnhancementRequestVersion.owner_type, EnhancementRequestVersion.owner_id),
        core_fields=("description", "owner"),
    ),
}
