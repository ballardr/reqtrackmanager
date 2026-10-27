"""
Module: modules.decisions.report_fields

The `ReportFieldProvider` for the `decision` artefact type, so custom report layouts can print and
group Decisions.

Responsibilities:
- Declare the Decision fields a layout may use: the decision record's text (from the search
  declaration), the type's name, the decision date, the owner and the decision maker.

Design decisions:
- Owner and decision maker are principals (a user or a group), shown by name.
- Opt-in only; the joins and identity columns come from the search declaration.

Dependencies: this module's models; `services.report_fields` (builders).
"""

from __future__ import annotations

from app.modules.decisions.models import Decision, DecisionTypeDefinition
from app.modules.decisions.search import SEARCH_PROVIDERS
from app.modules.registry import ReportFieldProvider
from app.services.report_fields import date_field, from_search, name_lookup_field, principal_field

REPORT_FIELDS: dict[str, ReportFieldProvider] = {
    "decision": from_search(
        SEARCH_PROVIDERS["decision"],
        name_lookup_field(
            "decision_type", "Decision type", DecisionTypeDefinition.name, DecisionTypeDefinition.id,
            Decision.decision_type_id, DecisionTypeDefinition.project_id,
        ),
        date_field("decision_date", "Decision date", Decision.decision_date),
        principal_field("owner", "Owner", Decision.owner_type, Decision.owner_id),
        principal_field("decision_maker", "Decision maker", Decision.decision_maker_type, Decision.decision_maker_id),
    ),
}
