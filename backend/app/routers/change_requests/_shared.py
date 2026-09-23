"""
Module: routers.change_requests._shared

Internal helper shared by four of this package's six bucket modules
(`tasks`, `votes`, `comments`, `subscriptions`) — the change-request
ownership-chain lookup that guards against an IDOR where a caller in one
project could read/write a sub-resource of a change request belonging to a
different project by supplying its id (role checks in each bucket only
validate against `project_id`, not the change request's own). Not a
router itself — no `@router` routes live here. `core.py`/`workflow.py`
don't need this helper: they already load the `ChangeRequest` row
themselves (via `db.get`/`db.scalar(...).with_for_update()`) as part of
their own logic, so re-deriving it through this helper would be redundant.

Split out of the former flat `routers/change_requests.py` as a pure
code-organization refactor — see `routers/change_requests/__init__.py`'s
module docstring for the package layout.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest


def _get_cr_in_project(db: Session, project_id: UUID, cr_id: UUID) -> ChangeRequest:
    """Loads a change request and 404s unless it belongs to `project_id`.

    Prevents an IDOR where a member of one project could read/write
    comments on a change request belonging to a different project by
    supplying its id, since role checks below only validate against
    `project_id`.
    """
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found.")
    return cr
