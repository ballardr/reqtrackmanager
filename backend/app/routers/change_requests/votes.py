"""
Module: routers.change_requests.votes

Casting (or updating) an advisory stakeholder vote on a change request
(C-R-03), and the vote tally. Advisory only — see
`models.change_request.ChangeRequestVote`'s docstring.

Split out of the former flat `routers/change_requests.py` as a pure
code-organization refactor — see `routers/change_requests/__init__.py`'s
module docstring for the package layout. `_get_cr_in_project` is imported
from `_shared.py` (used by four sibling buckets); `OPEN_CR_STATUSES` is
imported from `core.py` (used by exactly one sibling bucket besides core
itself).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.change_request import ChangeRequestVote
from app.models.enums import ChangeRequestVoteChoice, ProjectRole
from app.models.user import User
from app.routers.change_requests._shared import _get_cr_in_project
from app.routers.change_requests.core import OPEN_CR_STATUSES
from app.schemas.change_request import ChangeRequestVoteCreate, ChangeRequestVoteOut, ChangeRequestVoteTallyOut
from app.services.audit import log_event
from app.services.rbac import require_project_role, require_project_view

router = APIRouter(tags=["change-requests-votes"])


@router.post("/{cr_id}/votes", response_model=ChangeRequestVoteOut)
def cast_vote(
    project_id: UUID, cr_id: UUID, payload: ChangeRequestVoteCreate,
    current_user: User = Depends(require_project_role(ProjectRole.STAKEHOLDER)), db: Session = Depends(get_db),
):
    """Casts (or updates) the caller's advisory vote on a change request (C-R-03).

    Advisory only — see `models.change_request.ChangeRequestVote`'s
    docstring. Voting again before a decision is made updates the existing
    vote rather than creating a duplicate.
    """
    cr = _get_cr_in_project(db, project_id, cr_id)
    if cr.status not in OPEN_CR_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Voting is only open while a change request is under review.")

    existing = db.scalar(
        select(ChangeRequestVote).where(ChangeRequestVote.change_request_id == cr.id, ChangeRequestVote.user_id == current_user.id)
    )
    if existing is not None:
        existing.vote = payload.vote
        existing.comment = payload.comment
        existing.voted_at = datetime.now(UTC)
        vote = existing
    else:
        vote = ChangeRequestVote(
            change_request_id=cr.id, user_id=current_user.id, vote=payload.vote,
            comment=payload.comment, voted_at=datetime.now(UTC),
        )
        db.add(vote)
    db.flush()
    log_event(db, entity_type="change_request_vote", entity_id=vote.id, action="cast",
              actor_id=current_user.id, project_id=project_id, detail={"vote": payload.vote.value})
    db.commit()
    db.refresh(vote)
    return vote


@router.get("/{cr_id}/votes", response_model=ChangeRequestVoteTallyOut)
def list_votes(
    project_id: UUID, cr_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    cr = _get_cr_in_project(db, project_id, cr_id)
    votes = db.scalars(select(ChangeRequestVote).where(ChangeRequestVote.change_request_id == cr.id)).all()
    return ChangeRequestVoteTallyOut(
        votes=list(votes),
        approve_count=sum(1 for v in votes if v.vote == ChangeRequestVoteChoice.APPROVE),
        reject_count=sum(1 for v in votes if v.vote == ChangeRequestVoteChoice.REJECT),
    )
