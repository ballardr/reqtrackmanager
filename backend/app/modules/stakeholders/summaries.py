"""
Module: modules.stakeholders.summaries

`ArtefactSummaryProvider`s for Personas, Stakeholders, Stakeholder Needs, Stakeholder Groups,
Engagements and Research Findings, so
core (the artefact link graph) can label and visibility-check them as link
targets without importing the models.

Responsibilities:
- Build an `ArtefactSummary` (name, status, archived flag, owner) per record
  from its current version, with the type (Persona, Stakeholder) or status (Need)
  facet the link finder's browse level reads.
- Offer a one-query batch lookup scoped to a viewing project
  (`get_many_in_project`) that applies this module's visibility rules.

Design decisions:
- An Engagement and a Finding are project-only and never archived, so a project sees exactly its own.
- A Persona or Stakeholder is visible to a project when the project owns it,
  or its organisation owns it and the project has not hidden it
  (`service.hidden_persona_ids` / `hidden_stakeholder_ids`, which already walk
  ancestor projects). A Need is project-only.
- Org-owned records carry `project_id=None` and their `organization_id`, so a
  plain project-equality check never mistakes one for a project's own.

Dependencies: this module's own models and `service`; `modules.registry` for
the summary dataclasses; core `Project` for the viewing project's organisation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.registry import ArtefactSummary, ArtefactSummaryProvider, BrowseLevel
from app.modules.stakeholders.models import (
    Engagement,
    Persona,
    PersonaTypeDefinition,
    PersonaVersion,
    ProjectPersonaType,
    ProjectStakeholderType,
    ResearchFinding,
    Stakeholder,
    StakeholderGroup,
    StakeholderNeed,
    StakeholderNeedVersion,
    StakeholderTypeDefinition,
    StakeholderVersion,
)
from app.modules.stakeholders.service import hidden_persona_ids, hidden_stakeholder_ids
from app.services.summary_facets import status_facet, two_tier_type_facets

ARTEFACT_TYPE_LABELS: dict[str, str] = {
    "persona": "Persona",
    "stakeholder": "Stakeholder",
    "stakeholder_need": "Stakeholder need",
    "stakeholder_group": "Stakeholder group",
    "engagement": "Engagement",
    "research_finding": "Research finding",
}

ENGAGEMENT_CHANNEL_LABELS: dict[str, str] = {
    "email": "Email", "call": "Call", "meeting": "Meeting", "workshop": "Workshop", "interview": "Interview",
    "focus_group": "Focus group", "usability_test": "Usability test", "survey": "Survey",
}


def _provider(
    model: Any, version_model: Any, fk_name: str, hidden_ids: Callable[[Session, UUID], set[UUID]] | None,
    type_models: tuple[Any, Any] | None, levels: tuple[BrowseLevel, ...],
) -> ArtefactSummaryProvider:
    """Provider for a versioned record (`Persona`, `Stakeholder`, `StakeholderNeed`).

    Args:
        model: The record model (has `id`, `project_id`, `is_archived`, and
            `organization_id` when `hidden_ids` is given).
        version_model: Its version model (has `name`, `status`, `valid_to`, and
            `org_type_id`/`project_type_id` when `type_models` is given).
        fk_name: The version model's foreign-key attribute to the record.
        hidden_ids: `(db, project_id) -> ids` of org-owned records hidden from
            the project; `None` for a project-only record type.
        type_models: `(organisation type model, project type model)` for a typed record
            (gives the `type` facet); `None` for one classified by status alone.
        levels: The type's finder levels, matching the facets built here.

    Returns:
        The provider.
    """
    fk = getattr(version_model, fk_name)
    org_owned = hidden_ids is not None

    def build(db: Session, pairs: Sequence[Any]) -> list[ArtefactSummary]:
        types = (
            two_tier_type_facets(
                db, type_models[0], type_models[1],
                org_type_ids=[v.org_type_id for _, v in pairs], project_type_ids=[v.project_type_id for _, v in pairs],
            )
            if type_models is not None else {}
        )
        out = []
        for row, version in pairs:
            facets = {"status": status_facet(version.status.value)}
            if type_models is not None:
                facets["type"] = (
                    types.get(("org", version.org_type_id)) or types.get(("project", version.project_type_id)) or ("", "")
                )
            out.append(ArtefactSummary(
                id=row.id, project_id=row.project_id, organization_id=getattr(row, "organization_id", None),
                label=version.name, status=version.status.value, is_archived=row.is_archived, facets=facets,
            ))
        return out

    def query(*conditions: Any):
        return select(model, version_model).join(version_model, fk == model.id).where(
            version_model.valid_to.is_(None), *conditions
        )

    def get(db: Session, record_id: UUID) -> ArtefactSummary | None:
        pair = db.execute(query(model.id == record_id)).first()
        return None if pair is None else build(db, [pair])[0]

    def visible_conditions(db: Session, project_id: UUID) -> Any:
        if not org_owned:
            return model.project_id == project_id
        organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
        return or_(model.project_id == project_id, model.organization_id == organization_id)

    def visible(db: Session, project_id: UUID, pairs: Sequence[Any]) -> list[ArtefactSummary]:
        hidden = hidden_ids(db, project_id) if hidden_ids is not None else set()
        return build(db, [p for p in pairs if p[0].id not in hidden])

    def list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
        pairs = db.execute(query(visible_conditions(db, project_id), model.is_archived.is_(False))).all()
        return sorted(visible(db, project_id, pairs), key=lambda s: s.label.lower())

    def get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
        pairs = db.execute(query(model.id.in_(ids), visible_conditions(db, project_id))).all()
        return visible(db, project_id, pairs)

    return ArtefactSummaryProvider(
        get=get, list_for_project=list_for_project, get_many_in_project=get_many_in_project, browse_levels=levels,
    )


def _group_provider() -> ArtefactSummaryProvider:
    """Provider for Stakeholder Groups: a project sees its organisation's groups and its own (no
    hiding, no ancestor fallback — addendum 3, item 27); the finder narrows by scope."""
    scope_labels = {"organization": "Organisation", "project": "Project"}

    def build(rows: Sequence[StakeholderGroup]) -> list[ArtefactSummary]:
        return [
            ArtefactSummary(
                id=g.id, project_id=g.project_id, organization_id=g.organization_id, label=g.name,
                facets={"scope": (g.scope.value, scope_labels[g.scope.value])},
            )
            for g in rows
        ]

    def get(db: Session, group_id: UUID) -> ArtefactSummary | None:
        group = db.get(StakeholderGroup, group_id)
        return None if group is None else build([group])[0]

    def conditions(db: Session, project_id: UUID) -> Any:
        organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
        return or_(StakeholderGroup.project_id == project_id, StakeholderGroup.organization_id == organization_id)

    def list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
        rows = db.scalars(select(StakeholderGroup).where(conditions(db, project_id))).all()
        return sorted(build(rows), key=lambda s: s.label.lower())

    def get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
        return build(db.scalars(select(StakeholderGroup).where(StakeholderGroup.id.in_(ids), conditions(db, project_id))).all())

    return ArtefactSummaryProvider(
        get=get, list_for_project=list_for_project, get_many_in_project=get_many_in_project,
        browse_levels=(BrowseLevel("scope", "Scope"),),
    )


def _project_record_provider(
    model: Any, label_of: Callable[[Any], str], facets_of: Callable[[Session, Sequence[Any]], list[dict[str, tuple[str, str]]]],
    levels: tuple[BrowseLevel, ...], order_by: Any,
) -> ArtefactSummaryProvider:
    """Provider for a project-only record without versions or lifecycle (Engagement, Research Finding).

    `facets_of(db, rows)` returns one facet mapping per row, so a facet that needs another table
    (a finding's engagement) is loaded in one query for the batch."""

    def build(db: Session, rows: Sequence[Any]) -> list[ArtefactSummary]:
        facets = facets_of(db, rows)
        return [
            ArtefactSummary(id=r.id, project_id=r.project_id, label=label_of(r), facets=f)
            for r, f in zip(rows, facets, strict=True)
        ]

    def get(db: Session, record_id: UUID) -> ArtefactSummary | None:
        row = db.get(model, record_id)
        return None if row is None else build(db, [row])[0]

    def list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
        return build(db, db.scalars(select(model).where(model.project_id == project_id).order_by(order_by)).all())

    def get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
        return build(db, db.scalars(select(model).where(model.id.in_(ids), model.project_id == project_id)).all())

    return ArtefactSummaryProvider(
        get=get, list_for_project=list_for_project, get_many_in_project=get_many_in_project, browse_levels=levels,
    )


def _engagement_facets(db: Session, rows: Sequence[Engagement]) -> list[dict[str, tuple[str, str]]]:
    return [{"channel": (e.channel.value, ENGAGEMENT_CHANNEL_LABELS[e.channel.value])} for e in rows]


def _finding_facets(db: Session, rows: Sequence[ResearchFinding]) -> list[dict[str, tuple[str, str]]]:
    """A finding's facet is the engagement it came from."""
    titles = {
        e.id: e.title for e in db.scalars(select(Engagement).where(Engagement.id.in_({f.engagement_id for f in rows})))
    } if rows else {}
    return [{"engagement": (str(f.engagement_id), titles.get(f.engagement_id, ""))} for f in rows]


ARTEFACT_SUMMARY_PROVIDERS: dict[str, ArtefactSummaryProvider] = {
    "persona": _provider(
        Persona, PersonaVersion, "persona_id", hidden_persona_ids, (PersonaTypeDefinition, ProjectPersonaType),
        (BrowseLevel("type", "Persona type"),),
    ),
    "stakeholder": _provider(
        Stakeholder, StakeholderVersion, "stakeholder_id", hidden_stakeholder_ids,
        (StakeholderTypeDefinition, ProjectStakeholderType), (BrowseLevel("type", "Stakeholder type"),),
    ),
    "stakeholder_need": _provider(
        StakeholderNeed, StakeholderNeedVersion, "need_id", None, None, (BrowseLevel("status", "Status"),)
    ),
    "stakeholder_group": _group_provider(),
    "engagement": _project_record_provider(
        Engagement, lambda e: f"{e.unique_code} {e.title}", _engagement_facets, (BrowseLevel("channel", "Channel"),),
        Engagement.engagement_date.desc(),
    ),
    "research_finding": _project_record_provider(
        ResearchFinding, lambda f: f"{f.unique_code} {f.title}", _finding_facets, (BrowseLevel("engagement", "Engagement"),),
        ResearchFinding.created_at.desc(),
    ),
}
