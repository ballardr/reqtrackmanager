"""
Module: modules.architecture.baseline_routes

The endpoints that read the architecture a baseline holds, added to the module's project router by
`add_baseline_routes`: the records of a baseline (without content), one record's content, and a comparison of a baseline
with the live model or with another baseline. Baselines are taken and listed through the core `/projects/{id}/baselines`
routes; this module reads only what its own snapshot providers wrote.

RBAC: project membership and the Elements sub-component. A type whose own sub-component is off for the project is left
out of the view, the record read and the comparison. Every lookup is scoped to the project in the URL, so another project's
baseline looks absent. A snapshot holds only the project's own records, scrubbed of personal data and of references the
project cannot read (`baseline_snapshot`), so reading it needs no per-element visibility check beyond that.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import ProjectStage
from app.models.requirement import Baseline, BaselineItem
from app.models.user import User
from app.modules.architecture import baseline_compare, baseline_snapshot
from app.modules.architecture.schemas import (
    BaselineComparisonOut,
    BaselineFieldChangeOut,
    BaselineItemOut,
    BaselineRecordChangeOut,
    BaselineRecordOut,
    BaselineRecordRefOut,
    BaselineTypeComparisonOut,
    BaselineViewOut,
)
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_SUBCOMPONENT_KEY,
    DIAGRAM_ARTEFACT_TYPE,
    DIAGRAM_SUBCOMPONENT_KEY,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_SUBCOMPONENT_KEY,
    STATE_MACHINE_ARTEFACT_TYPE,
    STATE_MACHINE_SUBCOMPONENT_KEY,
)
from app.modules.registry import is_module_subcomponent_enabled
from app.services.lookups import project_or_404
from app.services.rbac import require_project_subcomponent_enabled

#: The baseline types and the sub-component that shows each, in display order.
_TYPES: tuple[tuple[str, str], ...] = (
    (ELEMENT_ARTEFACT_TYPE, ELEMENT_SUBCOMPONENT_KEY),
    (CONNECTION_ARTEFACT_TYPE, CONNECTION_SUBCOMPONENT_KEY),
    (DIAGRAM_ARTEFACT_TYPE, DIAGRAM_SUBCOMPONENT_KEY),
    (STATE_MACHINE_ARTEFACT_TYPE, STATE_MACHINE_SUBCOMPONENT_KEY),
)
LIVE = "live"


def visible_types(db: Session, project_id: uuid.UUID) -> list[str]:
    """The baseline types whose sub-component is on for the project, in display order."""
    return [t for t, key in _TYPES if is_module_subcomponent_enabled(db, project_id, ARCHITECTURE_MODULE_KEY, key)]


def _baseline_or_404(db: Session, project_id: uuid.UUID, baseline_id: uuid.UUID) -> Baseline:
    """The project's baseline, or 404 (another project's id looks absent)."""
    baseline = db.scalar(select(Baseline).where(Baseline.id == baseline_id, Baseline.project_id == project_id))
    if baseline is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Baseline not found.")
    return baseline


def _contents(db: Session, baseline: Baseline, types: Sequence[str]) -> dict[str, list[Mapping[str, Any]]]:
    """`{type: [snapshot content]}` of a baseline's records of the given types."""
    contents: dict[str, list[Mapping[str, Any]]] = {t: [] for t in types}
    rows = db.scalars(select(BaselineItem).where(BaselineItem.baseline_id == baseline.id, BaselineItem.item_type.in_(list(types))))
    for item in rows:
        if item.snapshot is not None:
            contents[item.item_type].append(item.snapshot)
    return contents


def _record(item: BaselineItem) -> BaselineRecordOut:
    """A baseline item as the list shows it."""
    ref = baseline_compare.record_ref(item.snapshot or {})
    return BaselineRecordOut(id=item.id, item_type=item.item_type, code=ref.code, name=ref.name, status=ref.status)


def _ref_out(ref: baseline_compare.RecordRef) -> BaselineRecordRefOut:
    return BaselineRecordRefOut(code=ref.code, name=ref.name, status=ref.status)


def _type_out(comparison: baseline_compare.TypeComparison) -> BaselineTypeComparisonOut:
    """The response form of one type's comparison."""
    return BaselineTypeComparisonOut(
        item_type=comparison.item_type, unchanged=comparison.unchanged,
        added=[_ref_out(r) for r in comparison.added], removed=[_ref_out(r) for r in comparison.removed],
        changed=[
            BaselineRecordChangeOut(
                code=c.record.code, name=c.record.name, status=c.record.status,
                fields=[
                    BaselineFieldChangeOut(field=f.field, before=f.before, after=f.after, added=f.added, removed=f.removed)
                    for f in c.fields
                ],
            )
            for c in comparison.changed
        ],
    )


def add_baseline_routes(router: APIRouter) -> None:
    """Adds the baseline read routes to `router` (the project router)."""
    view = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY)

    @router.get("/baselines/{baseline_id}", response_model=BaselineViewOut)
    def baseline_records(
        project_id: uuid.UUID, baseline_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """The architecture records a baseline holds (without their content), by type then code."""
        baseline = _baseline_or_404(db, project_id, baseline_id)
        types = visible_types(db, project_id)
        items = list(db.scalars(
            select(BaselineItem).where(BaselineItem.baseline_id == baseline.id, BaselineItem.item_type.in_(types))
        ))
        order = {t: n for n, t in enumerate(types)}
        records = sorted((_record(i) for i in items), key=lambda r: (order[r.item_type], r.code))
        author = db.get(User, baseline.created_by)
        stage_name = None
        if baseline.stage_id is not None:
            stage = db.get(ProjectStage, baseline.stage_id)
            stage_name = stage.name if stage else None
        return BaselineViewOut(
            id=baseline.id, label=baseline.label, kind=baseline.kind.value, stage_name=stage_name,
            created_at=baseline.created_at, created_by_name=author.display_name if author else None, records=records,
        )

    @router.get("/baselines/{baseline_id}/items/{item_id}", response_model=BaselineItemOut)
    def baseline_record(
        project_id: uuid.UUID, baseline_id: uuid.UUID, item_id: uuid.UUID,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """One record of a baseline with its full content as it stood."""
        baseline = _baseline_or_404(db, project_id, baseline_id)
        item = db.scalar(select(BaselineItem).where(
            BaselineItem.id == item_id, BaselineItem.baseline_id == baseline.id,
            BaselineItem.item_type.in_(visible_types(db, project_id)),
        ))
        if item is None or item.snapshot is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Baseline record not found.")
        return BaselineItemOut(**_record(item).model_dump(), content=item.snapshot)

    @router.get("/baselines/{baseline_id}/compare", response_model=BaselineComparisonOut)
    def compare_baseline(
        project_id: uuid.UUID, baseline_id: uuid.UUID,
        against: str = Query(LIVE, description="`live` for the model as it stands, or the id of another baseline."),
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """What differs between the baseline and the live model, or between it and a later baseline.

        The baseline in the path is the base: a record only in the other side is `added`, one only in the base `removed`.
        """
        project = project_or_404(db, project_id)
        baseline = _baseline_or_404(db, project_id, baseline_id)
        types = visible_types(db, project_id)
        second: dict[str, Any]
        if against == LIVE:
            kind, against_id, label = LIVE, None, "Live model"
            second = {t: [e.content for e in entries] for t, entries in baseline_snapshot.build(db, project).items()}
        else:
            try:
                other_id = uuid.UUID(against)
            except ValueError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "`against` must be `live` or a baseline id.") from exc
            other = _baseline_or_404(db, project_id, other_id)
            kind, against_id, label = "baseline", other.id, other.label
            second = _contents(db, other, types)
        comparisons = baseline_compare.compare(_contents(db, baseline, types), second, types)
        return BaselineComparisonOut(
            baseline_id=baseline.id, baseline_label=baseline.label, against=kind, against_id=against_id, against_label=label,
            types=[_type_out(c) for c in comparisons],
        )
