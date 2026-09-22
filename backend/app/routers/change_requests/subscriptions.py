"""
Module: routers.change_requests.subscriptions

Subscribing/unsubscribing to a change request (C-N-01), so a follower is
notified of its comments and decision.

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
from app.models.user import User
from app.routers.change_requests._shared import _get_cr_in_project
from app.services import engagement
from app.services.rbac import require_project_view

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
