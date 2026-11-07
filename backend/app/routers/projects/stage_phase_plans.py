"""
Module: routers.projects.stage_phase_plans

Phase schedule: every phase's expected range and actual dates for a project's stages and component tracks,
the expected range of one phase, and the project's reminder lead time (`services.stage_phase_plans`).

Design decisions:
- Reading is for any project member; setting a range or the lead time is for those who manage the project.
- One response shape for the whole project, as the component tracks, so the screen reads it in one request.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.project import Project, ProjectComponent, ProjectStage
from app.models.stage_workflow import StageWorkflowPhase
from app.models.user import User
from app.schemas.stage_workflow import PhasePlanOut, PhasePlanSet, PhasePlansOut, PhaseReminderSettingSet
from app.services import stage_phase_plans as plans
from app.services.rbac import require_project_manage, require_project_view
from app.services.stage_workflows import WorkflowConflict

router = APIRouter(tags=["projects-phase-plans"])


def _plans_out(db: Session, project: Project) -> PhasePlansOut:
    """The lead time that applies and every stored plan row of the project."""
    days, inherited = plans.resolve_lead_days(db, project)
    return PhasePlansOut(
        lead_days=days, own_lead_days=project.phase_reminder_lead_days, inherited=inherited,
        plans=[
            PhasePlanOut(
                stage_id=r.stage_id, component_id=r.component_id, phase_id=r.phase_id, expected_from=r.expected_from,
                expected_to=r.expected_to, started_at=r.started_at, completed_at=r.completed_at,
            )
            for r in plans.project_plans(db, project)
        ],
    )


@router.get("/{project_id}/phase-plans", response_model=PhasePlansOut)
def get_phase_plans(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> PhasePlansOut:
    """The project's phase schedule and reminder lead time."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return _plans_out(db, project)


@router.put("/{project_id}/stages/{stage_id}/phase-plan", response_model=PhasePlansOut)
def set_phase_plan(
    stage_id: UUID, body: PhasePlanSet, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> PhasePlansOut:
    """Sets or clears the expected range of one phase of a stage, or of a component's track within it.

    Both dates empty clears the range (the actual dates are kept). The start must not be after the end.
    """
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    phase = db.get(StageWorkflowPhase, body.phase_id)
    if phase is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "phase_id must be a phase of the workflow that applies.")
    component = None
    if body.component_id is not None:
        component = db.get(ProjectComponent, body.component_id)
        if component is None or component.project_id != project.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found.")
    try:
        plans.set_plan(
            db, project, stage, phase, current_user, component=component,
            expected_from=body.expected_from, expected_to=body.expected_to,
        )
    except WorkflowConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return _plans_out(db, project)


@router.put("/{project_id}/phase-reminder-settings", response_model=PhasePlansOut)
def set_phase_reminder_settings(
    body: PhaseReminderSettingSet, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> PhasePlansOut:
    """Sets the days before a phase's expected start that its reminder is sent, or `null` to follow the nearest ancestor."""
    plans.set_lead_days(db, project, body.lead_days, current_user.id)
    db.commit()
    return _plans_out(db, project)
