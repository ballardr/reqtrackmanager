"""
Module: routers.requirements.subscriptions

Per-requirement notification follow/unfollow (C-N-01), independent of a
user's broad per-notification-type preferences, plus the groups watching a
requirement (every member who can view the project follows it; users and
groups on parity).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import PrincipalType
from app.models.project import Project
from app.models.user import User
from app.routers.requirements.core import _get_requirement_in_project
from app.schemas.principal import PrincipalOut, PrincipalRef, WatcherCreate
from app.services import engagement
from app.services.rbac import require_project_manage, require_project_view

router = APIRouter(tags=["requirements-subscriptions"])


@router.put("/{requirement_id}/subscription", status_code=status.HTTP_204_NO_CONTENT)
def subscribe_to_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Opts the caller into notifications for this specific requirement
    (independent of their broad per-type notification preferences)."""
    _get_requirement_in_project(db, project_id, requirement_id)
    engagement.subscribe(db, current_user.id, "requirement", requirement_id)


@router.delete("/{requirement_id}/subscription", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe_from_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    engagement.unsubscribe(db, current_user.id, "requirement", requirement_id)


@router.get("/{requirement_id}/watchers", response_model=list[PrincipalOut])
def list_requirement_watchers(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """The groups watching this requirement: every member who can view the project is notified of its comments."""
    _get_requirement_in_project(db, project_id, requirement_id)
    return engagement.watching_groups_out(db, "requirement", requirement_id)


@router.post("/{requirement_id}/watchers", response_model=list[PrincipalOut], status_code=status.HTTP_201_CREATED)
def add_requirement_watcher(
    project_id: UUID, requirement_id: UUID, payload: WatcherCreate,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Adds a group as a watcher (project managers and administrators). Returns the watching groups."""
    _get_requirement_in_project(db, project_id, requirement_id)
    return engagement.add_watching_group(db, project, "requirement", requirement_id, payload.group, current_user)


@router.delete("/{requirement_id}/watchers/{group_type}/{group_id}", response_model=list[PrincipalOut])
def remove_requirement_watcher(
    project_id: UUID, requirement_id: UUID, group_type: PrincipalType, group_id: UUID,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Stops a group watching this requirement. Returns the remaining watching groups."""
    _get_requirement_in_project(db, project_id, requirement_id)
    return engagement.remove_watching_group(
        db, project, "requirement", requirement_id, PrincipalRef(type=group_type, id=group_id), current_user,
    )
