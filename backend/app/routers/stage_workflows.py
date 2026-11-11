"""
Module: routers.stage_workflows

Stage workflow administration at both tiers.

Responsibilities:
- Organisation tier (`/orgs/{id}/stage-workflows`, organisation administrators): list, create,
  replace and delete the workflows every project of the organisation may use.
- Project tier (`/projects/{id}/stage-workflows`, project managers): the project's effective set
  (with where each came from), its own workflows, and hiding and restoring organisation ones.

Design decisions:
- Delete on an organisation workflow inside a project hides it there (a tombstone), as every
  other organisation default does; a project always keeps at least one usable workflow.
- Validation and the in-use rules live in `services.stage_workflows`; this file maps their
  errors to HTTP statuses.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.project import Project
from app.models.stage_workflow import StageWorkflow
from app.models.user import User
from app.schemas.stage_workflow import (
    HiddenWorkflowOut,
    PhaseOut,
    RestoreWorkflowsRequest,
    WorkflowOut,
    WorkflowUsageOut,
    WorkflowWrite,
)
from app.services import definition_suppression
from app.services.audit import log_event
from app.services.lookups import project_or_404
from app.services.rbac import require_org_role, require_project_manage, require_project_view
from app.services.stage_workflows import (
    WORKFLOW_KIND,
    PhaseInput,
    WorkflowConflict,
    delete_workflow,
    effective_workflows,
    phases_by_workflow,
    workflow_in_use,
    workflow_usage,
    write_workflow,
)

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/stage-workflows", tags=["stage-workflows"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/stage-workflows", tags=["stage-workflows"])


def _out(db: Session, workflows: list[StageWorkflow], project_id: UUID | None = None) -> list[WorkflowOut]:
    """Workflow responses with their phases (one query), whether a stage follows each and who does.

    `project_id` scopes the usage to one project (and names its stages); without it the usage is counts across the
    organisation.
    """
    phases = phases_by_workflow(db, [w.id for w in workflows])
    usage = workflow_usage(db, [w.id for w in workflows], project_id)
    return [
        WorkflowOut(
            id=w.id, name=w.name, scope="organisation" if w.project_id is None else "project", sort_order=w.sort_order,
            phases=[PhaseOut.model_validate(p) for p in phases[w.id]], in_use=workflow_in_use(db, w.id),
            used_by=WorkflowUsageOut.model_validate(usage[w.id], from_attributes=True),
        )
        for w in workflows
    ]


def _write(db: Session, payload: WorkflowWrite, *, organization_id: UUID, project_id: UUID | None, actor: User,
           workflow: StageWorkflow | None = None) -> StageWorkflow:
    """Saves a workflow through the service, mapping its errors to 409 (state) and 400 (shape)."""
    try:
        return write_workflow(
            db, organization_id=organization_id, project_id=project_id, name=payload.name,
            phases=[PhaseInput(name=p.name, kind=p.kind, id=p.id) for p in payload.phases],
            workflow=workflow, actor_id=actor.id,
        )
    except WorkflowConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _own(db: Session, workflow_id: UUID, organization_id: UUID, project_id: UUID | None) -> StageWorkflow:
    """The workflow if it belongs to exactly this tier, else a 404."""
    workflow = db.get(StageWorkflow, workflow_id)
    if workflow is None or workflow.organization_id != organization_id or workflow.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    return workflow


@org_router.get("", response_model=list[WorkflowOut])
def list_org_workflows(
    organization_id: UUID, current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """The organisation's workflows."""
    return _out(db, list(db.scalars(
        select(StageWorkflow).where(StageWorkflow.organization_id == organization_id, StageWorkflow.project_id.is_(None))
        .order_by(StageWorkflow.sort_order, StageWorkflow.name)
    ).all()))


@org_router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
def create_org_workflow(
    organization_id: UUID, payload: WorkflowWrite,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Creates an organisation workflow, offered to every project of the organisation."""
    workflow = _write(db, payload, organization_id=organization_id, project_id=None, actor=current_user)
    db.commit()
    return _out(db, [workflow])[0]


@org_router.put("/{workflow_id}", response_model=WorkflowOut)
def replace_org_workflow(
    organization_id: UUID, workflow_id: UUID, payload: WorkflowWrite,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Replaces an organisation workflow's name and phases (see `services.stage_workflows.write_workflow`)."""
    workflow = _own(db, workflow_id, organization_id, None)
    _write(db, payload, organization_id=organization_id, project_id=None, actor=current_user, workflow=workflow)
    db.commit()
    return _out(db, [workflow])[0]


@org_router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_workflow(
    organization_id: UUID, workflow_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Deletes an organisation workflow no stage follows; its hidden markers in projects go with it."""
    workflow = _own(db, workflow_id, organization_id, None)
    try:
        delete_workflow(db, workflow, current_user.id)
    except WorkflowConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()


@project_router.get("", response_model=list[WorkflowOut])
def list_project_workflows(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """The workflows this project may use: the organisation's it has not hidden, then its own (or its nearest ancestor's)."""
    return _out(db, effective_workflows(db, project_or_404(db, project_id)), project_id)


@project_router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
def create_project_workflow(
    payload: WorkflowWrite, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Creates a workflow for this project only."""
    workflow = _write(db, payload, organization_id=project.organization_id, project_id=project.id, actor=current_user)
    db.commit()
    return _out(db, [workflow], project.id)[0]


@project_router.get("/hidden", response_model=list[HiddenWorkflowOut])
def list_hidden_workflows(
    project_id: UUID, project: Project = Depends(require_project_manage), db: Session = Depends(get_db),
):
    """Organisation workflows this project has hidden."""
    hidden = definition_suppression.get_suppressed_ids(db, project.id, WORKFLOW_KIND)
    if not hidden:
        return []
    return [
        HiddenWorkflowOut(id=w.id, name=w.name)
        for w in db.scalars(select(StageWorkflow).where(StageWorkflow.id.in_(hidden)).order_by(StageWorkflow.name)).all()
    ]


@project_router.post("/restore", response_model=list[HiddenWorkflowOut])
def restore_hidden_workflows(
    payload: RestoreWorkflowsRequest, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Shows hidden organisation workflows in this project again (all of them unless `workflow_ids` is given)."""
    restored = definition_suppression.restore_definitions(
        db, project.id, WORKFLOW_KIND, set(payload.workflow_ids) if payload.workflow_ids is not None else None
    )
    out = []
    if restored:
        for workflow in db.scalars(select(StageWorkflow).where(StageWorkflow.id.in_(restored)).order_by(StageWorkflow.name)).all():
            log_event(db, entity_type="stage_workflow", entity_id=workflow.id, action="restored", actor_id=current_user.id,
                      project_id=project.id, organization_id=project.organization_id, detail={"name": workflow.name})
            out.append(HiddenWorkflowOut(id=workflow.id, name=workflow.name))
    db.commit()
    return out


@project_router.put("/{workflow_id}", response_model=WorkflowOut)
def replace_project_workflow(
    workflow_id: UUID, payload: WorkflowWrite, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Replaces one of this project's own workflows; an organisation workflow is read-only here."""
    workflow = _own(db, workflow_id, project.organization_id, project.id)
    _write(db, payload, organization_id=project.organization_id, project_id=project.id, actor=current_user, workflow=workflow)
    db.commit()
    return _out(db, [workflow], project.id)[0]


@project_router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_workflow(
    workflow_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Deletes one of the project's own workflows, or hides an organisation one in this project.

    Hiding stops new use only (stages already following it keep it). The project must keep at
    least one usable workflow, so the last cannot be deleted or hidden.
    """
    workflow = db.get(StageWorkflow, workflow_id)
    if workflow is None or workflow.organization_id != project.organization_id or workflow.project_id not in (None, project.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    usable = effective_workflows(db, project)
    if workflow.id in {w.id for w in usable} and len(usable) == 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A project needs at least one workflow, so the last cannot be removed.")
    if workflow.project_id is None:
        if definition_suppression.hide_definition(db, project.id, WORKFLOW_KIND, workflow.id):
            log_event(db, entity_type="stage_workflow", entity_id=workflow.id, action="hidden", actor_id=current_user.id,
                      project_id=project.id, organization_id=project.organization_id, detail={"name": workflow.name})
    else:
        try:
            delete_workflow(db, workflow, current_user.id)
        except WorkflowConflict as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
