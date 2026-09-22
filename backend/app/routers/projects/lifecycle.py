"""
Module: routers.projects.lifecycle

Archive/unarchive (C-P-01): hides a project from the active project list
without deleting its data, and reverses that.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.project import Project
from app.models.user import User
from app.routers.projects.core import _project_out_with_redacted_parent
from app.schemas.project import ProjectOut
from app.services.audit import log_event
from app.services.rbac import require_project_manage

router = APIRouter(tags=["projects-lifecycle"])


@router.post("/{project_id}/archive", response_model=ProjectOut)
def archive_project(
    project_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Archives a project: hidden from the active project list, data preserved (C-P-01)."""
    project.is_archived = True
    project.archived_at = datetime.now(UTC)
    project.archived_by = current_user.id
    log_event(db, entity_type="project", entity_id=project.id, action="archived",
              actor_id=current_user.id, project_id=project.id)
    db.commit()
    db.refresh(project)
    return _project_out_with_redacted_parent(db, current_user, project)


@router.post("/{project_id}/unarchive", response_model=ProjectOut)
def unarchive_project(
    project_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Restores an archived project to the active project list (C-P-01)."""
    project.is_archived = False
    project.archived_at = None
    project.archived_by = None
    log_event(db, entity_type="project", entity_id=project.id, action="unarchived",
              actor_id=current_user.id, project_id=project.id)
    db.commit()
    db.refresh(project)
    return _project_out_with_redacted_parent(db, current_user, project)
