"""
Module: modules.decisions.search

The `ArtefactSearchProvider` for the `decision` type: the columns the search
reads (code, title, tags) and the opt-in free-text fields (statement, ADR
sections, long-form document). Dependencies: this module's models and labels;
`modules.registry`.
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
            SearchField("decision_statement", "Decision statement", Decision.decision_statement, markdown=True),
            SearchField("context", "Context", Decision.context, markdown=True),
            SearchField("options_considered", "Options considered", Decision.options_considered, markdown=True),
            SearchField("chosen_option", "Chosen option", Decision.chosen_option, markdown=True),
            SearchField("rationale", "Rationale", Decision.rationale, markdown=True),
            SearchField("consequences", "Consequences", Decision.consequences, markdown=True),
            SearchField("assumptions", "Assumptions", Decision.assumptions, markdown=True),
            SearchField("constraints", "Constraints", Decision.constraints, markdown=True),
            SearchField("document", "Document", Decision.document, markdown=True),
        ),
        status_labels=DECISION_STATUS_LABEL,
        comments=comments_of(DecisionComment, DecisionComment.decision_id),
    ),
}
