"""
Module: modules.decisions.search

The `ArtefactSearchProvider` for the `decision` artefact type, so the global search finds
decisions by code, title, tags and the decision record's text.

Responsibilities:
- Declare the columns the search reads and the free-text fields it may match.

Design decisions:
- Opt-in fields: the statement and the decision-record sections (context, options,
  chosen option, rationale, consequences, assumptions, constraints) only.

Dependencies: this module's models and labels; `modules.registry` (the provider shapes).
"""

from __future__ import annotations

from app.modules.decisions.labels import DECISION_STATUS_LABEL
from app.modules.decisions.models import Decision, DecisionComment
from app.modules.registry import ArtefactSearchProvider, SearchColumns, SearchField
from app.services.search_core import comments_of

SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    "decision": ArtefactSearchProvider(
        from_clause=Decision.__table__,
        columns=SearchColumns(
            id=Decision.id, project_id=Decision.project_id, code=Decision.unique_code, title=Decision.title,
            status=Decision.status, is_archived=Decision.is_archived, updated_at=Decision.updated_at,
        ),
        fields=(
            SearchField("decision_statement", "Decision statement", Decision.decision_statement),
            SearchField("context", "Context", Decision.context),
            SearchField("options_considered", "Options considered", Decision.options_considered),
            SearchField("chosen_option", "Chosen option", Decision.chosen_option),
            SearchField("rationale", "Rationale", Decision.rationale),
            SearchField("consequences", "Consequences", Decision.consequences),
            SearchField("assumptions", "Assumptions", Decision.assumptions),
            SearchField("constraints", "Constraints", Decision.constraints),
        ),
        status_labels=DECISION_STATUS_LABEL,
        comments=comments_of(DecisionComment, DecisionComment.decision_id),
    ),
}
