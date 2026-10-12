"""
Module: routers.change_requests.subscriptions

Subscribing/unsubscribing to a change request (C-N-01), so a follower is
notified of its comments and decision, plus the groups watching a change
request (every member who can view the project follows it).

Split out of the former flat `routers/change_requests.py` as a pure
code-organization refactor — see `routers/change_requests/__init__.py`'s
module docstring for the package layout. Kept as its own small bucket
rather than folded into `comments.py`, matching how the `requirements/`
package's own split gave subscriptions their own dedicated bucket.
`_get_cr_in_project` is imported from `_shared.py` (used by four sibling
buckets).
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
from app.routers.change_requests._shared import _get_cr_in_project
from app.schemas.principal import PrincipalOut, PrincipalRef, WatcherCreate
from app.services import engagement
from app.services.rbac import require_project_manage, require_project_view

router = APIRouter(tags=["change-requests-subscriptions"])


@router.put("/{cr_id}/subscription", status_code=status.HTTP_204_NO_CONTENT)
def subscribe_to_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_cr_in_project(db, project_id, cr_id)
    engagement.subscribe(db, current_user.id, "change_request", cr_id)


@router.delete("/{cr_id}/subscription", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe_from_change_request(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_cr_in_project(db, project_id, cr_id)
    engagement.unsubscribe(db, current_user.id, "change_request", cr_id)


@router.get("/{cr_id}/watchers", response_model=list[PrincipalOut])
def list_change_request_watchers(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """The groups watching this change request: every member who can view the project is notified of its comments."""
    _get_cr_in_project(db, project_id, cr_id)
    return engagement.watching_groups_out(db, "change_request", cr_id)


@router.post("/{cr_id}/watchers", response_model=list[PrincipalOut], status_code=status.HTTP_201_CREATED)
def add_change_request_watcher(
    project_id: UUID, cr_id: UUID, payload: WatcherCreate,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Adds a group as a watcher (project managers and administrators). Returns the watching groups."""
    _get_cr_in_project(db, project_id, cr_id)
    return engagement.add_watching_group(db, project, "change_request", cr_id, payload.group, current_user)


@router.delete("/{cr_id}/watchers/{group_type}/{group_id}", response_model=list[PrincipalOut])
def remove_change_request_watcher(
    project_id: UUID, cr_id: UUID, group_type: PrincipalType, group_id: UUID,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Stops a group watching this change request. Returns the remaining watching groups."""
    _get_cr_in_project(db, project_id, cr_id)
    return engagement.remove_watching_group(
        db, project, "change_request", cr_id, PrincipalRef(type=group_type, id=group_id), current_user,
    )
