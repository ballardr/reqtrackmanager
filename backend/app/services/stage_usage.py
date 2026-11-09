"""
Module: services.stage_usage

Whether a project makes use of its stages, so the navigation can offer the Delivery status page only where it has
something to show.

Responsibilities:
- `stages_in_use`: true when the project goes beyond the single default stage every project is created with.

Design decisions:
- Every project is created with one "Scoping" stage and the last stage cannot be deleted, so "has stages" never
  distinguishes a project; "in use" does (Decided by: User): more than one stage, or any stage that has left the first
  phase of its workflow, has an owner, a review deadline or a completion, or any scheduled phase, or component phases on.
- Read only, a few small queries; the answer is advisory (a navigation hint), never an authorisation decision, and the
  page itself stays reachable by its address.

Dependencies: `services.stage_workflows`, `services.component_stages`, `services.stage_phase_plans`.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectStage
from app.models.stage_workflow import StagePhasePlan
from app.services import component_stages
from app.services.stage_workflows import start_phase


def stages_in_use(db: Session, project: Project) -> bool:
    """Whether `project` uses its stages beyond the default one.

    Args:
        db: The session (read only).
        project: The project.

    Returns:
        True if it has several stages, or a stage that moved on, has an owner, review deadline or completion, or any
        phase schedule row exists, or component phases are on.
    """
    stages = list(db.scalars(select(ProjectStage).where(ProjectStage.project_id == project.id)).all())
    if len(stages) > 1:
        return True
    for stage in stages:
        if (
            stage.phase_id != start_phase(db, stage.workflow_id).id
            or stage.owner_id is not None
            or stage.review_deadline is not None
            or stage.completed_at is not None
        ):
            return True
    if db.scalar(select(func.count()).select_from(StagePhasePlan).where(StagePhasePlan.project_id == project.id)):
        return True
    return component_stages.phases_enabled(db, project)
