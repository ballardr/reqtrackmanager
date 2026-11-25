"""
Module: modules.risk_management.report_fields

The `ReportFieldProvider` for `risk`, so custom report layouts can print and
group Risks: the risk text (from the search declaration), treatment strategy,
owner (a principal shown by name) and review date, from the current version.
Ratings are reported by the module's own reports, not as level ids.
Dependencies: this module's models; `services.report_fields`.
"""

from __future__ import annotations

from app.modules.registry import ReportFieldProvider
from app.modules.risk_management.enums import TreatmentStrategy
from app.modules.risk_management.models import RiskVersion
from app.modules.risk_management.search import SEARCH_PROVIDERS
from app.services.report_fields import date_field, enum_field, from_search, principal_field

REPORT_FIELDS: dict[str, ReportFieldProvider] = {
    "risk": from_search(
        SEARCH_PROVIDERS["risk"],
        enum_field("treatment_strategy", "Treatment strategy", RiskVersion.treatment_strategy, TreatmentStrategy),
        principal_field("owner", "Owner", RiskVersion.owner_type, RiskVersion.owner_id),
        date_field("review_date", "Review date", RiskVersion.review_date),
        core_fields=("statement", "owner"),
    ),
}
