"""
Module: modules.stakeholders.summaries

`ArtefactSummaryProvider`s for Personas, Stakeholders and Stakeholder Needs, so
core (the artefact link graph) can label and visibility-check them as link
targets without importing the models.

Responsibilities:
- Build an `ArtefactSummary` (name, status, archived flag, owner) per record
  from its current version.
- Offer a one-query batch lookup scoped to a viewing project
  (`get_many_in_project`) that applies this module's visibility rules.

Design decisions:
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
from app.modules.registry import ArtefactSummary, ArtefactSummaryProvider
from app.modules.stakeholders.models import (
    Persona,
    PersonaVersion,
    Stakeholder,
    StakeholderNeed,
    StakeholderNeedVersion,
    StakeholderVersion,
)
from app.modules.stakeholders.service import hidden_persona_ids, hidden_stakeholder_ids

ARTEFACT_TYPE_LABELS: dict[str, str] = {
    "persona": "Persona",
    "stakeholder": "Stakeholder",
    "stakeholder_need": "Stakeholder need",
}


def _provider(
    model: Any, version_model: Any, fk_name: str, hidden_ids: Callable[[Session, UUID], set[UUID]] | None
) -> ArtefactSummaryProvider:
    """Provider for a versioned record (`Persona`, `Stakeholder`, `StakeholderNeed`).

    Args:
        model: The record model (has `id`, `project_id`, `is_archived`, and
            `organization_id` when `hidden_ids` is given).
        version_model: Its version model (has `name`, `status`, `valid_to`).
        fk_name: The version model's foreign-key attribute to the record.
        hidden_ids: `(db, project_id) -> ids` of org-owned records hidden from
            the project; `None` for a project-only record type.

    Returns:
        The provider.
    """
    fk = getattr(version_model, fk_name)
    org_owned = hidden_ids is not None

    def summary(row: Any, version: Any) -> ArtefactSummary:
        return ArtefactSummary(
            id=row.id, project_id=row.project_id, organization_id=getattr(row, "organization_id", None),
            label=version.name, status=version.status.value, is_archived=row.is_archived,
        )

    def query(*conditions: Any):
        return select(model, version_model).join(version_model, fk == model.id).where(
            version_model.valid_to.is_(None), *conditions
        )

    def get(db: Session, record_id: UUID) -> ArtefactSummary | None:
        pair = db.execute(query(model.id == record_id)).first()
        return None if pair is None else summary(*pair)

    def visible_conditions(db: Session, project_id: UUID) -> Any:
        if not org_owned:
            return model.project_id == project_id
        organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
        return or_(model.project_id == project_id, model.organization_id == organization_id)

    def visible(db: Session, project_id: UUID, pairs: Sequence[Any]) -> list[ArtefactSummary]:
        hidden = hidden_ids(db, project_id) if hidden_ids is not None else set()
        return [summary(*p) for p in pairs if p[0].id not in hidden]

    def list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
        pairs = db.execute(query(visible_conditions(db, project_id), model.is_archived.is_(False))).all()
        return sorted(visible(db, project_id, pairs), key=lambda s: s.label.lower())

    def get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
        pairs = db.execute(query(model.id.in_(ids), visible_conditions(db, project_id))).all()
        return visible(db, project_id, pairs)

    return ArtefactSummaryProvider(get=get, list_for_project=list_for_project, get_many_in_project=get_many_in_project)


ARTEFACT_SUMMARY_PROVIDERS: dict[str, ArtefactSummaryProvider] = {
    "persona": _provider(Persona, PersonaVersion, "persona_id", hidden_persona_ids),
    "stakeholder": _provider(Stakeholder, StakeholderVersion, "stakeholder_id", hidden_stakeholder_ids),
    "stakeholder_need": _provider(StakeholderNeed, StakeholderNeedVersion, "need_id", None),
}
