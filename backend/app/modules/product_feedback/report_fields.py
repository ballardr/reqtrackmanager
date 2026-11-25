"""
Module: modules.product_feedback.report_fields

The `ReportFieldProvider` for `enhancement_request`, so custom report layouts
can print and group requests: the description (from the search declaration) and
the owner, a principal shown by name, read from the current version.
Dependencies: this module's models; `services.report_fields`.
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
        math_fields=("description",),
        core_fields=("description", "owner"),
    ),
}
