"""
Module: modules.stakeholders.report_fields

The `ReportFieldProvider`s for the Stakeholders module's six artefact types, so custom report layouts can
print and group Personas, Stakeholders, Needs, Stakeholder Groups, Engagements and Research Findings.

Responsibilities:
- Declare, per type, the text fields (from the search declaration) and the typed fields that are safe to
  report: an engagement's date, a persona's weight.

Design decisions:
- Personal and consent-sensitive data is excluded by omission: no participant identity, contact detail or
  consent record is a field. An engagement's notes and summary come across only because the search already
  treats them as opt-in text.
- Opt-in only; joins and identity columns come from the search declaration.

Dependencies: this module's models; `services.report_fields` (builders).
"""

from __future__ import annotations

from app.modules.registry import ReportFieldProvider
from app.modules.stakeholders.models import Engagement, PersonaVersion
from app.modules.stakeholders.search import SEARCH_PROVIDERS
from app.services.report_fields import date_field, from_search, number_field

REPORT_FIELDS: dict[str, ReportFieldProvider] = {
    "persona": from_search(SEARCH_PROVIDERS["persona"], number_field("weight", "Weight", PersonaVersion.weight), core_fields=("description",)),
    "stakeholder": from_search(SEARCH_PROVIDERS["stakeholder"], core_fields=("description",)),
    "stakeholder_need": from_search(SEARCH_PROVIDERS["stakeholder_need"], core_fields=("description",)),
    "stakeholder_group": from_search(SEARCH_PROVIDERS["stakeholder_group"], core_fields=("description",)),
    "engagement": from_search(
        SEARCH_PROVIDERS["engagement"], date_field("engagement_date", "Engagement date", Engagement.engagement_date),
        core_fields=("purpose",),
    ),
    "research_finding": from_search(SEARCH_PROVIDERS["research_finding"], core_fields=("description",)),
}
