"""
Module: routers.reviews

The user-basis requirement review-due listing (C-R-09/C-R-10) — the
project-basis equivalent lives under routers/requirements.py's existing
`/api/v1/projects/{project_id}/requirements` prefix; this one spans every
project the caller has any role on, so it gets its own small top-level
`/api/v1/me` router instead.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.requirement import RequirementDueForReviewOut
from app.services.reviews import get_due_reviews_for_user

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("/reviews/due", response_model=list[RequirementDueForReviewOut])
def list_my_due_reviews(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Requirements assigned to the current user as reviewer, due/overdue,
    across every project (C-R-09, filtered per C-R-10's assignment)."""
    return [
        RequirementDueForReviewOut(
            requirement_id=req.id, project_id=req.project_id, unique_code=req.unique_code,
            name=version.name, review_date=version.review_date, reviewer_id=version.reviewer_id,
        )
        for version, req in get_due_reviews_for_user(db, current_user.id)
    ]
