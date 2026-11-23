"""
Module: routers.change_requests._shared

Internal helper shared by `tasks`, `votes`, `comments` and `subscriptions`: the change-request
ownership-chain lookup that guards against an IDOR where a caller in one project reads or writes a
sub-resource of another project's change request by supplying its id (each bucket's role checks validate
only against `project_id`). Not a router. `core.py` and `workflow.py` load the `ChangeRequest` row
themselves, so they do not need it.
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
