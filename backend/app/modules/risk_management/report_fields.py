"""
Module: modules.risk_management.report_fields

The `ReportFieldProvider` for the `risk` artefact type, so custom report layouts can print and group Risks.

Responsibilities:
- Declare the Risk fields a layout may use: the risk text (from the search declaration), the treatment
  strategy, the owner and the review date, all read from the current version.

Design decisions:
- The owner is a principal (a user or a group), shown by name. Ratings are scored from the organisation's
  scoring model and are reported by the Risk module's own reports, not as raw level ids.

Dependencies: this module's models and enums; `services.report_fields` (builders).
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
    ),
}
