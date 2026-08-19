"""
Module: routers.reviews

The user-basis requirement review-due listing (C-R-09/C-R-10) — the
project-basis equivalent lives under routers/requirements.py's existing
`/api/v1/projects/{project_id}/requirements` prefix; this one spans every
project the caller has any role on, so it gets its own small top-level
`/api/v1/me` router instead.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.project import Project, ProjectComponent
from app.models.user import User
from app.schemas.requirement import RequirementDueForReviewOut
from app.services.reviews import get_due_reviews_for_user

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("/reviews/due", response_model=list[RequirementDueForReviewOut])
def list_my_due_reviews(
    response: Response,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Requirements assigned to the current user as reviewer, due/overdue,
    across every project (C-R-09, filtered per C-R-10's assignment).

    Unlike the project-scoped equivalent, this spans every project the
    caller has any role on, so each row also carries `project_name` — see
    `RequirementDueForReviewOut`. `limit`/`offset` (U-P-06) are optional,
    same contract as `list_requirements`: omitting both returns everything.
    """
    due = get_due_reviews_for_user(db, current_user.id)
    component_ids = {req.component_id for _, req in due}
    component_names = (
        dict(db.execute(select(ProjectComponent.id, ProjectComponent.name).where(ProjectComponent.id.in_(component_ids))).all())
        if component_ids
        else {}
    )
    project_ids = {req.project_id for _, req in due}
    project_names = (
        dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids))).all())
        if project_ids
        else {}
    )
    out = [
        RequirementDueForReviewOut(
            requirement_id=req.id, project_id=req.project_id, project_name=project_names.get(req.project_id),
            unique_code=req.unique_code, name=version.name, review_date=version.review_date,
            reviewer_id=version.reviewer_id, reviewer_name=current_user.display_name,
            component_id=req.component_id, component_name=component_names.get(req.component_id, ""),
        )
        for version, req in due
    ]
    response.headers["X-Total-Count"] = str(len(out))
    if limit is not None:
        out = out[offset:offset + limit]
    return out
