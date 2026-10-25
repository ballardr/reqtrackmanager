"""
Module: modules.context_strategy.report_fields

The `ReportFieldProvider`s for Context & Strategy's five artefact types, so custom report layouts can
print and group Strategies, Future States, Pain Points, Guiding Principles and Open Questions.

Responsibilities:
- Declare, per type, the text fields (from the search declaration) and the typed fields: priority,
  time horizon, owner, dates and flags.

Design decisions:
- An owner is a principal (a user or a group), shown by name.
- A Pain Point's per-persona scores are not fields here: they are one value per persona and belong to
  the Pain Point reports, not to a flat field.

Dependencies: this module's models and enums; `services.report_fields` (builders).
"""

from __future__ import annotations

from app.modules.context_strategy.enums import (
    OpenQuestionPriority,
    PainPointPriority,
    StrategyPriority,
    StrategyTimeHorizon,
)
from app.modules.context_strategy.models import (
    FutureStateVersion,
    OpenQuestion,
    PainPoint,
    StrategyVersion,
)
from app.modules.context_strategy.search import SEARCH_PROVIDERS
from app.modules.registry import ReportFieldProvider
from app.services.report_fields import bool_field, date_field, enum_field, from_search, principal_field

REPORT_FIELDS: dict[str, ReportFieldProvider] = {
    "strategy": from_search(
        SEARCH_PROVIDERS["strategy"],
        enum_field("priority", "Priority", StrategyVersion.priority, StrategyPriority),
        enum_field("time_horizon", "Time horizon", StrategyVersion.time_horizon, StrategyTimeHorizon),
    ),
    "future_state": from_search(
        SEARCH_PROVIDERS["future_state"],
        date_field("target_date", "Target date", FutureStateVersion.target_date),
    ),
    "guiding_principle": from_search(SEARCH_PROVIDERS["guiding_principle"]),
    "pain_point": from_search(
        SEARCH_PROVIDERS["pain_point"],
        enum_field("priority", "Priority", PainPoint.priority, PainPointPriority),
        principal_field("owner", "Owner", PainPoint.owner_type, PainPoint.owner_id),
        date_field("date_identified", "Date identified", PainPoint.date_identified),
        bool_field("is_intentional", "Intentional", PainPoint.is_intentional),
    ),
    "open_question": from_search(
        SEARCH_PROVIDERS["open_question"],
        enum_field("priority", "Priority", OpenQuestion.priority, OpenQuestionPriority),
        principal_field("owner", "Owner", OpenQuestion.owner_type, OpenQuestion.owner_id),
        date_field("due_date", "Due date", OpenQuestion.due_date),
    ),
}
