"""
Module: modules.product_feedback.summaries

The `ArtefactSummaryProvider` for `enhancement_request`: an `ArtefactSummary`
(`ENH-001 title`, status, archived flag, `status` facet) from the current
version, with a one-query batch lookup for a viewing project. A project sees
only its own requests; an inbox request is never a link target.
Dependencies: this module's models; `modules.registry`; `services.summary_facets`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.product_feedback.labels import REQUEST_STATUS_LABEL
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestVersion
from app.modules.registry import ArtefactSummary, ArtefactSummaryProvider, BrowseLevel
from app.services.summary_facets import status_facet

REQUEST_BROWSE_LEVELS = (BrowseLevel("status", "Status"),)


def _query(*conditions: Any):
    """Requests joined to their current version, filtered by `conditions`."""
    return select(EnhancementRequest, EnhancementRequestVersion).join(
        EnhancementRequestVersion, EnhancementRequestVersion.request_id == EnhancementRequest.id,
    ).where(EnhancementRequestVersion.valid_to.is_(None), *conditions)


def _build(pairs: Sequence[tuple[EnhancementRequest, EnhancementRequestVersion]]) -> list[ArtefactSummary]:
    """Summaries for `(request, current version)` pairs."""
    return [
        ArtefactSummary(
            id=request.id, project_id=request.project_id, label=f"{request.unique_code} {version.title}",
            status=version.status.value, is_archived=request.is_archived, organization_id=request.organization_id,
            facets={"status": status_facet(version.status.value, REQUEST_STATUS_LABEL)},
        )
        for request, version in pairs
    ]


def _get(db: Session, request_id: UUID) -> ArtefactSummary | None:
    pair = db.execute(_query(EnhancementRequest.id == request_id)).first()
    return None if pair is None else _build([tuple(pair)])[0]


def _list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
    pairs = db.execute(_query(EnhancementRequest.project_id == project_id, EnhancementRequest.is_archived.is_(False))).all()
    return sorted(_build([tuple(p) for p in pairs]), key=lambda s: s.label)


def _get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
    pairs = db.execute(_query(EnhancementRequest.id.in_(ids), EnhancementRequest.project_id == project_id)).all()
    return _build([tuple(p) for p in pairs])


REQUEST_SUMMARY_PROVIDER = ArtefactSummaryProvider(
    get=_get, list_for_project=_list_for_project, get_many_in_project=_get_many_in_project,
    browse_levels=REQUEST_BROWSE_LEVELS,
)
