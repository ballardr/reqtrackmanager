"""
Module: routers.requirements.subscriptions

Per-requirement notification follow/unfollow (C-N-01), independent of a
user's broad per-notification-type preferences, plus the users and groups watching a
requirement (a user, or every member of a group, who can view the project follows it; users and
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
    """The users and groups watching this requirement: each user, and each group member who can view the project, is notified."""
    _get_requirement_in_project(db, project_id, requirement_id)
    return engagement.watching_out(db, "requirement", requirement_id)


@router.post("/{requirement_id}/watchers", response_model=list[PrincipalOut], status_code=status.HTTP_201_CREATED)
def add_requirement_watcher(
    project_id: UUID, requirement_id: UUID, payload: WatcherCreate,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Adds a user or group as a watcher (project managers and administrators). Returns the watchers."""
    _get_requirement_in_project(db, project_id, requirement_id)
    return engagement.add_watching(db, project, "requirement", requirement_id, payload.principal, current_user)


@router.delete("/{requirement_id}/watchers/{watcher_type}/{watcher_id}", response_model=list[PrincipalOut])
def remove_requirement_watcher(
    project_id: UUID, requirement_id: UUID, watcher_type: PrincipalType, watcher_id: UUID,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Stops a user or group watching this requirement. Returns the remaining watchers."""
    _get_requirement_in_project(db, project_id, requirement_id)
    return engagement.remove_watching(
        db, project, "requirement", requirement_id, PrincipalRef(type=watcher_type, id=watcher_id), current_user,
    )
