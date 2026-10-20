"""
Module: modules.risk_management.search

The `ArtefactSearchProvider` for the `risk` artefact type, so the global search finds
risks by code, title, tags and the risk's descriptive text.

Responsibilities:
- Declare the columns the search reads (from the risk's current version) and the free-text
  fields it may match.

Design decisions:
- Opt-in fields: the statement, cause, event, consequence and acceptance criteria only.
  Review notes and treatment text are not matched.

Dependencies: this module's models and labels; `services.search_core` (builders).
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
            SearchField("statement", "Statement", RiskVersion.statement),
            SearchField("cause", "Cause", RiskVersion.cause),
            SearchField("risk_event", "Risk event", RiskVersion.risk_event),
            SearchField("consequence", "Consequence", RiskVersion.consequence),
            SearchField("acceptance_criteria", "Acceptance criteria", RiskVersion.acceptance_criteria),
        ),
    ),
}
