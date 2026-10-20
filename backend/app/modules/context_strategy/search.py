"""
Module: modules.context_strategy.search

`ArtefactSearchProvider`s for the five Context & Strategy artefact types, so the global
search finds Strategies, Future States, Pain Points, Guiding Principles and Open Questions
by code, title, tags and the fields declared here.

Responsibilities:
- Declare, per type, the columns the search reads and the free-text fields it may match.

Design decisions:
- Opt-in fields: only the listed text columns are searchable; nothing else on these
  tables is matched.
- Strategies, Future States and Guiding Principles may be organisation-owned. An organisation-owned one is
  not shown by any project, so it is gated the way its organisation-level list is: any member of the
  organisation where the module's matching sub-component is on (`organization_subcomponent`), and it opens
  at its organisation page.

Dependencies: this module's models and labels; `services.search_core` (builders).
"""

from __future__ import annotations

from sqlalchemy import func

from app.modules.context_strategy.labels import LIFECYCLE_STATUS_LABEL, OPEN_QUESTION_STATUS_LABEL, PAIN_POINT_STATUS_LABEL
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateComment,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleComment,
    GuidingPrincipleVersion,
    OpenQuestion,
    OpenQuestionComment,
    PainPoint,
    PainPointComment,
    Strategy,
    StrategyComment,
    StrategyVersion,
)
from app.modules.registry import ArtefactSearchProvider, SearchColumns, SearchField
from app.services.search_core import comments_of, versioned_provider

_QUESTION_TITLE_CHARS = 120


def _simple_provider(model, title, status_labels, fields, comments) -> ArtefactSearchProvider:
    """Provider for an unversioned, project-only record (`PainPoint`, `OpenQuestion`)."""
    return ArtefactSearchProvider(
        from_clause=model.__table__,
        columns=SearchColumns(
            id=model.id, project_id=model.project_id, code=model.unique_code, title=title, status=model.status,
            is_archived=model.is_archived, updated_at=model.updated_at,
        ),
        fields=fields,
        status_labels=status_labels,
        comments=comments,
    )


SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    "strategy": versioned_provider(
        Strategy, StrategyVersion, "strategy_id", title=StrategyVersion.title, organization_subcomponent="strategy",
        comments=comments_of(StrategyComment, StrategyComment.strategy_id),
        status_labels=LIFECYCLE_STATUS_LABEL,
        fields=(
            SearchField("objective", "Objective", StrategyVersion.objective),
            SearchField("current_state", "Current state", StrategyVersion.current_state),
            SearchField("desired_future_state", "Desired future state", StrategyVersion.desired_future_state),
            SearchField("rationale", "Rationale", StrategyVersion.rationale),
            SearchField("expected_outcomes", "Expected outcomes", StrategyVersion.expected_outcomes),
            SearchField("constraints", "Constraints", StrategyVersion.constraints),
            SearchField("measures_of_success", "Measures of success", StrategyVersion.measures_of_success),
        ),
    ),
    "future_state": versioned_provider(
        FutureState, FutureStateVersion, "future_state_id", title=FutureStateVersion.title,
        organization_subcomponent="future_state",
        comments=comments_of(FutureStateComment, FutureStateComment.future_state_id),
        status_labels=LIFECYCLE_STATUS_LABEL,
        fields=(
            SearchField("current_state", "Current state", FutureStateVersion.current_state),
            SearchField("desired_state", "Desired state", FutureStateVersion.desired_state),
            SearchField("outcomes", "Outcomes", FutureStateVersion.outcomes),
            SearchField("success_measures", "Success measures", FutureStateVersion.success_measures),
            SearchField("constraints", "Constraints", FutureStateVersion.constraints),
            SearchField("assumptions", "Assumptions", FutureStateVersion.assumptions),
        ),
    ),
    "guiding_principle": versioned_provider(
        GuidingPrinciple, GuidingPrincipleVersion, "guiding_principle_id", title=GuidingPrincipleVersion.name,
        organization_subcomponent="guiding_principle",
        comments=comments_of(GuidingPrincipleComment, GuidingPrincipleComment.guiding_principle_id),
        status_labels=LIFECYCLE_STATUS_LABEL,
        fields=(
            SearchField("principle_statement", "Principle statement", GuidingPrincipleVersion.principle_statement),
            SearchField("rationale", "Rationale", GuidingPrincipleVersion.rationale),
        ),
    ),
    "pain_point": _simple_provider(
        PainPoint, PainPoint.title, PAIN_POINT_STATUS_LABEL,
        (
            SearchField("description", "Description", PainPoint.description),
            SearchField("source", "Source", PainPoint.source),
            SearchField("impact", "Impact", PainPoint.impact),
            SearchField("evidence", "Evidence", PainPoint.evidence),
        ),
        comments_of(PainPointComment, PainPointComment.pain_point_id),
    ),
    "open_question": _simple_provider(
        OpenQuestion, func.left(OpenQuestion.question, _QUESTION_TITLE_CHARS), OPEN_QUESTION_STATUS_LABEL,
        (
            SearchField("question", "Question", OpenQuestion.question),
            SearchField("context", "Context", OpenQuestion.context),
            SearchField("evidence", "Evidence", OpenQuestion.evidence),
        ),
        comments_of(OpenQuestionComment, OpenQuestionComment.open_question_id),
    ),
}
