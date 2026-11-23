"""
Module: modules.risk_management.search

The `ArtefactSearchProvider` for `risk`: the columns the search reads (from the
current version) and the opt-in text fields (statement, cause, event,
consequence, acceptance criteria; not review notes or treatment text).
Dependencies: this module's models and labels; `services.search_core`.
"""

from __future__ import annotations

from app.modules.registry import ArtefactSearchProvider, SearchField
from app.modules.risk_management.labels import RISK_STATUS_LABEL
from app.modules.risk_management.models import Risk, RiskComment, RiskVersion
from app.services.search_core import comments_of, versioned_provider

SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    "risk": versioned_provider(
        Risk, RiskVersion, "risk_id", title=RiskVersion.title, status_labels=RISK_STATUS_LABEL,
        comments=comments_of(RiskComment, RiskComment.risk_id),
        fields=(
            SearchField("statement", "Statement", RiskVersion.statement, markdown=True),
            SearchField("cause", "Cause", RiskVersion.cause, markdown=True),
            SearchField("risk_event", "Risk event", RiskVersion.risk_event, markdown=True),
            SearchField("consequence", "Consequence", RiskVersion.consequence, markdown=True),
            SearchField("acceptance_criteria", "Acceptance criteria", RiskVersion.acceptance_criteria, markdown=True),
        ),
    ),
}
