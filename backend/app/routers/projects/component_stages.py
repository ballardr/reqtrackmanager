"""
Module: routers.projects.component_stages

Component phases: the project switch, every component's track per stage, and moving a track between
the phases of its workflow (`services.component_stages`).

Design decisions:
- Reading is for any project member; changing a track's workflow, owner or applicability, and the switch,
  is for those who manage the project; moving a track is also open to the track's owner (a user or a
  member of the owner group), who may reach locked phases too (`component_stages.may_move_locked`).
- The same transition request shape as a stage (`StageTransitionRequest`), so the screen reuses it.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.project import Project, ProjectComponent, ProjectStage
from app.models.stage_workflow import StageWorkflow, StageWorkflowPhase
from app.models.user import User
from app.schemas.stage_workflow import (
    ComponentPhasesOut,
    ComponentPhasesSettingSet,
    ComponentTrackOut,
    ComponentTrackUpdate,
    StageTransitionRequest,
)
from app.services import component_stages as cs
from app.services.principals import is_principal_member, principal_labels, principal_ref
from app.services.rbac import (
    can_manage_project_settings,
    get_effective_project_roles,
    require_project_manage,
    require_project_view,
)
from app.services.stage_workflows import WorkflowConflict, phase_index

router = APIRouter(tags=["projects-component-stages"])


def _own_mode(project: Project) -> Literal["on", "off"] | None:
    """The project's own switch value, None when it follows an ancestor."""
    if project.component_phases_mode == cs.MODE_ON:
        return cs.MODE_ON
    if project.component_phases_mode == cs.MODE_OFF:
        return cs.MODE_OFF
    return None


def _phases_out(db: Session, project: Project, user: User) -> ComponentPhasesOut:
    """The switch and, when on, every track with the caller's `can_move`, in a fixed number of queries."""
    mode, inherited = cs.resolve_mode(db, project)
    own = _own_mode(project)
    tracks = cs.project_tracks(db, project)
    if not tracks:
        return ComponentPhasesOut(mode=mode, own_mode=own, inherited=inherited, tracks=[])
    phases = phase_index(db, {t.phase_id for t in tracks})
    workflow_ids = {t.workflow_id for t in tracks}
    workflows = {w.id: w.name for w in db.scalars(select(StageWorkflow).where(StageWorkflow.id.in_(workflow_ids))).all()}
    owners = [principal_ref(t.state.owner_type, t.state.owner_id) for t in tracks if t.state is not None]
    labels = principal_labels(db, owners)
    manager = can_manage_project_settings(db, user, project)
    member_cache: dict[tuple[str, UUID], bool] = {}
    out: list[ComponentTrackOut] = []
    for t in tracks:
        ref = principal_ref(t.state.owner_type, t.state.owner_id) if t.state is not None else None
        owner = labels.get((ref.type.value, ref.id)) if ref is not None else None
        can_move = manager
        if not can_move and ref is not None:
            key = (ref.type.value, ref.id)
            if key not in member_cache:
                member_cache[key] = is_principal_member(db, ref, user.id)
            can_move = member_cache[key]
        phase = phases[t.phase_id]
        out.append(ComponentTrackOut(
            component_id=t.component_id, stage_id=t.stage_id, workflow_id=t.workflow_id,
            workflow_name=workflows.get(t.workflow_id, ""), phase_id=phase.id, phase_name=phase.name, phase_kind=phase.kind,
            not_applicable=t.not_applicable, customised=t.state is not None, owner=owner,
            approved_at=t.state.approved_at if t.state else None, completed_at=t.state.completed_at if t.state else None,
            previous_closed=t.previous_closed, can_move=can_move,
        ))
    return ComponentPhasesOut(mode=mode, own_mode=own, inherited=inherited, tracks=out)


def _component(db: Session, project: Project, component_id: UUID) -> ProjectComponent:
    component = db.get(ProjectComponent, component_id)
    if component is None or component.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found.")
    return component


def _stage(db: Session, project: Project, stage_id: UUID) -> ProjectStage:
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    return stage


@router.get("/{project_id}/component-stages", response_model=ComponentPhasesOut)
def get_component_stages(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ComponentPhasesOut:
    """The project's component-phases switch and, when it is on, every component's track for every stage."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return _phases_out(db, project, current_user)


@router.put("/{project_id}/component-phases-settings", response_model=ComponentPhasesOut)
def set_component_phases_mode(
    body: ComponentPhasesSettingSet, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ComponentPhasesOut:
    """Turns component phases on or off for the project, or `null` to follow the nearest ancestor."""
    cs.set_mode(db, project, body.mode, current_user.id)
    db.commit()
    return _phases_out(db, project, current_user)


@router.patch("/{project_id}/components/{component_id}/stages/{stage_id}/track", response_model=ComponentPhasesOut)
def update_component_track(
    component_id: UUID, stage_id: UUID, body: ComponentTrackUpdate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ComponentPhasesOut:
    """Changes a component's workflow, owner or applicability for one stage (only the fields sent change).

    A workflow or applicability change is refused unless the track is in an open phase with no baseline of its own.
    """
    component = _component(db, project, component_id)
    stage = _stage(db, project, stage_id)
    sent = body.model_fields_set
    try:
        cs.update_track(
            db, project, component, stage, current_user,
            workflow_id=body.workflow_id if "workflow_id" in sent else cs.UNSET,
            not_applicable=body.not_applicable if "not_applicable" in sent and body.not_applicable is not None else cs.UNSET,
            owner=body.owner if "owner" in sent else cs.UNSET,
        )
    except WorkflowConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return _phases_out(db, project, current_user)


@router.post("/{project_id}/components/{component_id}/stages/{stage_id}/transition", response_model=ComponentPhasesOut)
def transition_component_track(
    project_id: UUID, component_id: UUID, stage_id: UUID, body: StageTransitionRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ComponentPhasesOut:
    """Moves a component's track to another phase of its workflow.

    Allowed to those who manage the project and to the track's owner. Entering a locked phase approves and
    baselines only that component's requirements that target the stage; entering a closed phase completes the
    track and, with `cascade_to_requirements`, those requirements.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    component = _component(db, project, component_id)
    stage = _stage(db, project, stage_id)
    state = cs.get_state(db, component.id, stage.id)
    if not (can_manage_project_settings(db, current_user, project) or is_principal_member(db, cs.owner_of(state), current_user.id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager or the track's owner can move it.")
    phase = db.get(StageWorkflowPhase, body.phase_id)
    if phase is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "phase_id must be a phase of the track's workflow.")
    try:
        cs.move_track(
            db, project, component, stage, phase, current_user,
            roles=get_effective_project_roles(db, current_user.id, project.id),
            cascade_to_requirements=body.cascade_to_requirements,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except WorkflowConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return _phases_out(db, project, current_user)
