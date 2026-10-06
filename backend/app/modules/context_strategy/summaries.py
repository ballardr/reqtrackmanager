"""
Module: modules.context_strategy.summaries

`ArtefactSummaryProvider`s for the five Context & Strategy artefact types, so
core (the artefact link graph) and other modules can label, status-badge and
visibility-check these records as link targets without importing the models.

Responsibilities:
- Build an `ArtefactSummary` (label, status, archived flag, owner) per record.
- Offer a one-query batch lookup scoped to a viewing project
  (`get_many_in_project`) for the link graph.

Design decisions:
- A project sees only records its own project owns. Org-scoped Strategies,
  Future States and Guiding Principles have no per-project visibility rule, so
  they are never offered as a project's link targets (their `project_id` is
  `None`).
- Strategy, Future State and Guiding Principle keep their content in versions;
  the current version (`valid_to IS NULL`) supplies label and status.

Dependencies: this module's own models only; `modules.registry` for the
summary dataclasses.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.context_strategy.models import (
    FutureState,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleVersion,
    OpenQuestion,
    PainPoint,
    Strategy,
    StrategyVersion,
)
from app.modules.registry import ArtefactSummary, ArtefactSummaryProvider

_LABEL_MAX = 120

ARTEFACT_TYPE_LABELS: dict[str, str] = {
    "strategy": "Strategy",
    "future_state": "Future state",
    "pain_point": "Pain point",
    "guiding_principle": "Guiding principle",
    "open_question": "Open question",
}


def _truncate(text: str) -> str:
    """Shortens a long free-text label (an Open Question's text) for display."""
    text = " ".join(text.split())
    return text if len(text) <= _LABEL_MAX else text[: _LABEL_MAX - 1] + "…"


def _simple_provider(model: Any, label: Callable[[Any], str]) -> ArtefactSummaryProvider:
    """Provider for an unversioned, project-only record (`PainPoint`,
    `OpenQuestion`): `label` derives the display text from the row.

    Args:
        model: The SQLAlchemy model (has `id`, `project_id`, `status`, `is_archived`).
        label: Maps a row to its display label.

    Returns:
        The provider.
    """

    def summary(row: Any) -> ArtefactSummary:
        return ArtefactSummary(
            id=row.id, project_id=row.project_id, label=label(row), status=row.status.value,
            is_archived=row.is_archived,
        )

    def get(db: Session, record_id: UUID) -> ArtefactSummary | None:
        row = db.get(model, record_id)
        return None if row is None else summary(row)

    def list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
        rows = db.scalars(select(model).where(model.project_id == project_id, model.is_archived.is_(False))).all()
        return sorted((summary(r) for r in rows), key=lambda s: s.label.lower())

    def get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
        rows = db.scalars(select(model).where(model.id.in_(ids), model.project_id == project_id)).all()
        return [summary(r) for r in rows]

    return ArtefactSummaryProvider(get=get, list_for_project=list_for_project, get_many_in_project=get_many_in_project)


def _versioned_provider(
    model: Any, version_model: Any, fk_name: str, label_attr: str
) -> ArtefactSummaryProvider:
    """Provider for a versioned record that can be org- or project-owned
    (`Strategy`, `FutureState`, `GuidingPrinciple`); label and status come
    from the current version.

    Args:
        model: The record model (has `id`, `project_id`, `organization_id`, `is_archived`).
        version_model: Its version model (has `valid_to`, `status`, and `label_attr`).
        fk_name: The version model's foreign-key attribute to the record.
        label_attr: The version attribute holding the display name.

    Returns:
        The provider.
    """
    fk = getattr(version_model, fk_name)

    def summary(row: Any, version: Any) -> ArtefactSummary:
        return ArtefactSummary(
            id=row.id, project_id=row.project_id, organization_id=row.organization_id,
            label=getattr(version, label_attr), status=version.status.value, is_archived=row.is_archived,
        )

    def query(*conditions: Any):
        return select(model, version_model).join(version_model, fk == model.id).where(
            version_model.valid_to.is_(None), *conditions
        )

    def get(db: Session, record_id: UUID) -> ArtefactSummary | None:
        pair = db.execute(query(model.id == record_id)).first()
        return None if pair is None else summary(*pair)

    def list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
        pairs = db.execute(query(model.project_id == project_id, model.is_archived.is_(False))).all()
        return sorted((summary(*p) for p in pairs), key=lambda s: s.label.lower())

    def get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
        return [summary(*p) for p in db.execute(query(model.id.in_(ids), model.project_id == project_id)).all()]

    return ArtefactSummaryProvider(get=get, list_for_project=list_for_project, get_many_in_project=get_many_in_project)


ARTEFACT_SUMMARY_PROVIDERS: dict[str, ArtefactSummaryProvider] = {
    "strategy": _versioned_provider(Strategy, StrategyVersion, "strategy_id", "title"),
    "future_state": _versioned_provider(FutureState, FutureStateVersion, "future_state_id", "title"),
    "guiding_principle": _versioned_provider(GuidingPrinciple, GuidingPrincipleVersion, "guiding_principle_id", "name"),
    "pain_point": _simple_provider(PainPoint, lambda p: p.title),
    "open_question": _simple_provider(OpenQuestion, lambda q: _truncate(q.question)),
}
