"""
Module: modules.risk_management.summaries

The `ArtefactSummaryProvider` for the `risk` artefact type, so core (the link
graph, the "Add a link" finder) and other modules can label, status-badge and
visibility-check a risk without importing its models.

Responsibilities:
- Build an `ArtefactSummary` (`RSK-001 title`, status, archived flag) from a
  risk's current version, with `status` and `risk_type` facets for the finder.
- Offer a one-query batch lookup scoped to a viewing project.

Design decisions:
- A risk is always project-owned, so a project sees only its own risks
  (`project_id` is set, never `None`).
- The current version (`valid_to IS NULL`) supplies label, status and type.

Dependencies: this module's models and labels; `modules.registry` for the
summary dataclasses; `services.summary_facets`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.registry import ArtefactSummary, ArtefactSummaryProvider, BrowseLevel
from app.modules.risk_management.labels import RISK_STATUS_LABEL
from app.modules.risk_management.models import ProjectRiskType, Risk, RiskTypeDefinition, RiskVersion
from app.services.summary_facets import status_facet, two_tier_type_facets

RISK_BROWSE_LEVELS = (BrowseLevel("status", "Status"), BrowseLevel("risk_type", "Risk type"))


def _query(*conditions: Any):
    """Risks joined to their current version, filtered by `conditions`."""
    return select(Risk, RiskVersion).join(RiskVersion, RiskVersion.risk_id == Risk.id).where(
        RiskVersion.valid_to.is_(None), *conditions
    )


def _build(db: Session, pairs: Sequence[tuple[Risk, RiskVersion]]) -> list[ArtefactSummary]:
    """Summaries for `(risk, current version)` pairs, resolving type names in one query."""
    types = two_tier_type_facets(
        db, RiskTypeDefinition, ProjectRiskType, project_type_ids=[v.project_type_id for _r, v in pairs]
    )
    out = []
    for risk, version in pairs:
        facets = {"status": status_facet(version.status.value, RISK_STATUS_LABEL)}
        type_facet = types.get(("project", version.project_type_id)) if version.project_type_id else None
        if type_facet is not None:
            facets["risk_type"] = type_facet
        out.append(ArtefactSummary(
            id=risk.id, project_id=risk.project_id, label=f"{risk.unique_code} {version.title}",
            status=version.status.value, is_archived=risk.is_archived, facets=facets,
        ))
    return out


def _get(db: Session, risk_id: UUID) -> ArtefactSummary | None:
    pair = db.execute(_query(Risk.id == risk_id)).first()
    return None if pair is None else _build(db, [tuple(pair)])[0]


def _list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
    pairs = db.execute(_query(Risk.project_id == project_id, Risk.is_archived.is_(False))).all()
    return sorted(_build(db, [tuple(p) for p in pairs]), key=lambda s: s.label)


def _get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
    pairs = db.execute(_query(Risk.id.in_(ids), Risk.project_id == project_id)).all()
    return _build(db, [tuple(p) for p in pairs])


RISK_SUMMARY_PROVIDER = ArtefactSummaryProvider(
    get=_get, list_for_project=_list_for_project, get_many_in_project=_get_many_in_project,
    browse_levels=RISK_BROWSE_LEVELS,
)
