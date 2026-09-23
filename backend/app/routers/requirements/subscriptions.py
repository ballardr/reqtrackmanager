"""
Module: routers.requirements.subscriptions

Per-requirement notification follow/unfollow (C-N-01), independent of a
user's broad per-notification-type preferences.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.requirements.core import _get_requirement_in_project
from app.services import engagement
from app.services.rbac import require_project_view

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
