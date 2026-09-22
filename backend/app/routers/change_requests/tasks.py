"""
Module: routers.change_requests.tasks

Task assignment during a change request's review (C-R-02, C-R-04):
assigning, listing, and editing/completing review tasks.

Split out of the former flat `routers/change_requests.py` as a pure
code-organization refactor — see `routers/change_requests/__init__.py`'s
module docstring for the package layout. `_get_cr_in_project` is imported
from `_shared.py` (used by four sibling buckets — see that module's
docstring).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.change_request import ChangeRequestTask
from app.models.enums import ProjectRole
from app.models.project import Project
from app.models.user import User
from app.routers.change_requests._shared import _get_cr_in_project
from app.schemas.change_request import ChangeRequestTaskCreate, ChangeRequestTaskOut, ChangeRequestTaskUpdate
from app.services.audit import log_event
from app.services.rbac import get_effective_project_roles, require_project_manage, require_project_view

router = APIRouter(tags=["change-requests-tasks"])


@router.post("/{cr_id}/tasks", response_model=ChangeRequestTaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    project_id: UUID, cr_id: UUID, payload: ChangeRequestTaskCreate,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Assigns a task during a change request's review (C-R-02, C-R-04)."""
    cr = _get_cr_in_project(db, project_id, cr_id)
    task = ChangeRequestTask(
        change_request_id=cr.id, description=payload.description,
        assignee_id=payload.assignee_id, due_date=payload.due_date, created_by=current_user.id,
    )
    db.add(task)
    db.flush()
    log_event(db, entity_type="change_request_task", entity_id=task.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"description": task.description})
    db.commit()
    db.refresh(task)
    return task


@router.get("/{cr_id}/tasks", response_model=list[ChangeRequestTaskOut])
def list_tasks(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    cr = _get_cr_in_project(db, project_id, cr_id)
    return db.scalars(
        select(ChangeRequestTask).where(ChangeRequestTask.change_request_id == cr.id).order_by(ChangeRequestTask.created_at)
    ).all()


@router.patch("/{cr_id}/tasks/{task_id}", response_model=ChangeRequestTaskOut)
def update_task(
    project_id: UUID, cr_id: UUID, task_id: UUID, payload: ChangeRequestTaskUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Edits a task, or marks it done/undone.

    A project manager can edit anything. A task's own assignee may toggle
    `is_done` on their own task without manager rights, but may not reassign
    or reschedule it.
    """
    cr = _get_cr_in_project(db, project_id, cr_id)
    task = db.get(ChangeRequestTask, task_id)
    if task is None or task.change_request_id != cr.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")

    is_manager = ProjectRole.PROJECT_MANAGER in get_effective_project_roles(db, current_user.id, project_id)
    is_own_task_done_toggle = (
        task.assignee_id == current_user.id
        and payload.description is None and payload.assignee_id is None and payload.due_date is None
        and payload.is_done is not None
    )
    if not (is_manager or is_own_task_done_toggle):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager, or the task's own assignee toggling done-status, may edit this task.")

    if payload.description is not None:
        task.description = payload.description
    if payload.assignee_id is not None:
        task.assignee_id = payload.assignee_id
    if payload.due_date is not None:
        task.due_date = payload.due_date
    if payload.is_done is not None:
        task.is_done = payload.is_done
        task.completed_at = datetime.now(UTC) if payload.is_done else None
    log_event(db, entity_type="change_request_task", entity_id=task.id, action="updated",
              actor_id=current_user.id, project_id=project_id, detail={"is_done": task.is_done})
    db.commit()
    db.refresh(task)
    return task
