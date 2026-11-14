"""
Module: routers.projects.baselines

A project's baselines (C-G-10): list them and take a manual one. Stage baselines are written by the stage transition
(`services.baseline.create_baseline_for_stage`), never here. The list carries counts only; the content a module
captured is read through that module's own routes, since its visibility is the module's rule.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project, ProjectStage
from app.models.requirement import Baseline, BaselineItem
from app.models.user import User
from app.modules.registry import get_all_registered_artefact_types
from app.schemas.baseline import BaselineOut, ManualBaselineCreate
from app.services.audit import log_event
from app.services.baseline import create_manual_baseline, manual_baseline_types
from app.services.lookups import get_or_404
from app.services.rbac import require_project_view

router = APIRouter(tags=["projects-baselines"])


def _baselines_out(db: Session, baselines: list[Baseline]) -> list[BaselineOut]:
    """Baseline responses with stage names, creators and per-type counts, read in three queries.

    Args:
        db: Database session.
        baselines: The baselines to describe.

    Returns:
        One `BaselineOut` per baseline, in the given order.
    """
    ids = [b.id for b in baselines]
    counts: dict[UUID, dict[str, int]] = {}
    if ids:
        for baseline_id, item_type, n in db.execute(
            select(BaselineItem.baseline_id, BaselineItem.item_type, func.count())
            .where(BaselineItem.baseline_id.in_(ids)).group_by(BaselineItem.baseline_id, BaselineItem.item_type)
        ):
            counts.setdefault(baseline_id, {})[item_type] = n
    stage_ids = {b.stage_id for b in baselines if b.stage_id}
    stage_names: dict[UUID, str] = {}
    if stage_ids:
        stage_names = {i: n for i, n in db.execute(select(ProjectStage.id, ProjectStage.name).where(ProjectStage.id.in_(stage_ids)))}
    user_ids = {b.created_by for b in baselines}
    names: dict[UUID, str] = {}
    if user_ids:
        names = {i: n for i, n in db.execute(select(User.id, User.display_name).where(User.id.in_(user_ids)))}
    return [
        BaselineOut(
            id=b.id, kind=b.kind, label=b.label, stage_id=b.stage_id, stage_name=stage_names.get(b.stage_id) if b.stage_id else None,
            component_id=b.component_id, created_by=b.created_by, created_by_name=names.get(b.created_by),
            created_at=b.created_at, item_counts=counts.get(b.id, {}),
        )
        for b in baselines
    ]


@router.get("/{project_id}/baselines", response_model=list[BaselineOut])
def list_baselines(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> list[BaselineOut]:
    """Lists the project's baselines, newest first, with how many records of each type each captured.

    Args:
        project_id: The project.
        current_user: The caller, who must be a project member.
        db: Database session.

    Returns:
        The baselines; content is not included.
    """
    baselines = list(db.scalars(
        select(Baseline).where(Baseline.project_id == project_id).order_by(Baseline.created_at.desc(), Baseline.id)
    ))
    return _baselines_out(db, baselines)


@router.post("/{project_id}/baselines", response_model=BaselineOut, status_code=status.HTTP_201_CREATED)
def create_baseline(
    project_id: UUID, payload: ManualBaselineCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> BaselineOut:
    """Takes a manual baseline of the chosen record types as they stand now.

    It names no stage and approves or locks nothing. A person may snapshot a type only with the permission its
    owner declares (project management for requirements, the module's permission for a module type).

    Args:
        project_id: The project.
        payload: The label and, optionally, the types.
        current_user: The caller, who must be a project member.
        db: Database session.

    Returns:
        The new baseline.

    Raises:
        HTTPException: 422 for a type that is not registered, 403 when the caller may snapshot none of the types
            asked for (or none at all).
    """
    project = get_or_404(db, Project, project_id, "Project")
    allowed = manual_baseline_types(db, project, current_user)
    if payload.item_types is None:
        chosen = allowed
    else:
        unknown = sorted(set(payload.item_types) - get_all_registered_artefact_types())
        if unknown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown item type: {', '.join(unknown)}.")
        chosen = list(dict.fromkeys(payload.item_types))
        if any(t not in allowed for t in chosen):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions to baseline one of those types.")
    if not chosen:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions to take a baseline.")
    baseline, counts = create_manual_baseline(db, project, current_user, payload.label, chosen)
    log_event(
        db, entity_type="baseline", entity_id=baseline.id, action="created", actor_id=current_user.id,
        organization_id=project.organization_id, project_id=project.id, detail={"kind": "manual", "counts": counts},
    )
    db.commit()
    db.refresh(baseline)
    return _baselines_out(db, [baseline])[0]
