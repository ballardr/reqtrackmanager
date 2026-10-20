"""
Module: modules.stakeholders.search

`ArtefactSearchProvider`s for the six Stakeholders & Personas artefact types (persona,
stakeholder, stakeholder need, stakeholder group, engagement, research finding), so the
global search finds them by code, title, tags and the fields declared here.

Responsibilities:
- Declare, per type, the columns the search reads and the free-text fields it may match.

Design decisions:
- Opt-in fields: a stakeholder's contact details and availability are personal data and
  are never matched; nothing else is searchable unless listed here.
- Personas, stakeholders and groups may be organisation-owned; the search finds those only
  through a project that is allowed to see them (`organization_owned`), so a persona hidden
  from a project is not found from it.
- A research finding has no page of its own; a hit opens its engagement.

Dependencies: this module's models and enums; `services.search_core` (builders).
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, cast, literal, null

from app.modules.registry import ArtefactSearchProvider, SearchColumns, SearchField
from app.modules.stakeholders.enums import NeedStatus, PersonaStatus, StakeholderStatus
from app.modules.stakeholders.models import (
    Engagement,
    EngagementComment,
    Persona,
    PersonaComment,
    PersonaVersion,
    ResearchFinding,
    Stakeholder,
    StakeholderComment,
    StakeholderGroup,
    StakeholderNeed,
    StakeholderNeedComment,
    StakeholderNeedVersion,
    StakeholderVersion,
)
from app.services.search_core import comments_of, humanise_labels, versioned_provider


def _no_status() -> object:
    """A NULL status: engagements, findings and groups have no lifecycle."""
    return cast(null(), String)


def _never_archived() -> object:
    """A constant false archive flag: these records are deleted, not archived."""
    return literal(False, type_=Boolean)


def _project_record(model, title, fields, **extra) -> ArtefactSearchProvider:
    """Provider for a project-only record with no versions, status or archive flag."""
    open_owner_type = extra.pop("open_owner_type", None)
    comments = extra.pop("comments", None)
    return ArtefactSearchProvider(
        from_clause=model.__table__,
        columns=SearchColumns(
            id=model.id, project_id=model.project_id, code=model.unique_code, title=title, status=_no_status(),
            is_archived=_never_archived(), updated_at=model.updated_at, **extra,
        ),
        fields=fields,
        open_owner_type=open_owner_type,
        comments=comments,
    )


SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    "persona": versioned_provider(
        Persona, PersonaVersion, "persona_id", title=PersonaVersion.name, organization_owned=True,
        comments=comments_of(PersonaComment, PersonaComment.persona_id),
        status_labels=humanise_labels(PersonaStatus),
        fields=(
            SearchField("description", "Description", PersonaVersion.description),
            SearchField("role_title", "Role title", PersonaVersion.role_title),
            SearchField("goals", "Goals", PersonaVersion.goals),
            SearchField("needs", "Needs", PersonaVersion.needs),
            SearchField("behaviours", "Behaviours", PersonaVersion.behaviours),
            SearchField("context_environment", "Context and environment", PersonaVersion.context_environment),
            SearchField("skills_proficiency", "Skills and proficiency", PersonaVersion.skills_proficiency),
            SearchField("frequency_of_use", "Frequency of use", PersonaVersion.frequency_of_use),
            SearchField("constraints", "Constraints", PersonaVersion.constraints),
        ),
    ),
    "stakeholder": versioned_provider(
        Stakeholder, StakeholderVersion, "stakeholder_id", title=StakeholderVersion.name, organization_owned=True,
        comments=comments_of(StakeholderComment, StakeholderComment.stakeholder_id),
        status_labels=humanise_labels(StakeholderStatus),
        fields=(
            SearchField("description", "Description", StakeholderVersion.description),
            SearchField("role", "Role", StakeholderVersion.role),
            SearchField("organisation_group", "Organisation group", StakeholderVersion.organisation_group),
            SearchField("interests", "Interests", StakeholderVersion.interests),
            SearchField("responsibilities", "Responsibilities", StakeholderVersion.responsibilities),
            SearchField("goals_needs", "Goals and needs", StakeholderVersion.goals_needs),
            SearchField("priorities", "Priorities", StakeholderVersion.priorities),
            SearchField("constraints", "Constraints", StakeholderVersion.constraints),
            SearchField("workflows_scenarios", "Workflows and scenarios", StakeholderVersion.workflows_scenarios),
        ),
    ),
    "stakeholder_need": versioned_provider(
        StakeholderNeed, StakeholderNeedVersion, "need_id", title=StakeholderNeedVersion.name,
        comments=comments_of(StakeholderNeedComment, StakeholderNeedComment.need_id),
        status_labels=humanise_labels(NeedStatus),
        fields=(
            SearchField("description", "Description", StakeholderNeedVersion.description),
            SearchField("rationale", "Rationale", StakeholderNeedVersion.rationale),
        ),
    ),
    "stakeholder_group": ArtefactSearchProvider(
        from_clause=StakeholderGroup.__table__,
        columns=SearchColumns(
            id=StakeholderGroup.id, project_id=StakeholderGroup.project_id, code=StakeholderGroup.unique_code,
            title=StakeholderGroup.name, status=_no_status(), is_archived=_never_archived(),
            updated_at=StakeholderGroup.updated_at, organization_id=StakeholderGroup.organization_id,
        ),
        fields=(SearchField("description", "Description", StakeholderGroup.description),),
        organization_owned=True,
    ),
    "engagement": _project_record(
        Engagement, Engagement.title,
        (
            SearchField("purpose", "Purpose", Engagement.purpose),
            SearchField("summary", "Summary", Engagement.summary),
            SearchField("notes", "Notes", Engagement.notes),
        ),
        comments=comments_of(EngagementComment, EngagementComment.engagement_id),
    ),
    "research_finding": _project_record(
        ResearchFinding, ResearchFinding.title, (SearchField("description", "Description", ResearchFinding.description),),
        owner_id=ResearchFinding.engagement_id, open_owner_type="engagement",
    ),
}
