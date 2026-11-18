"""
Module: modules.architecture.allocation_routes

The allocation endpoints, added to the module's project router by `add_allocation_routes`: a requirement's and an
element's allocation view (allocated, suggested, dismissed), accepting suggestions (any number of pairs), dismissing and
restoring one, and the coverage counts.

RBAC: reading needs project membership and the Elements sub-component; accepting, dismissing and restoring need the
authority to change requirement links (`allocation`). The view's `can_manage` tells the screen whether to offer them.
Every lookup is scoped to the project in the URL, so another project's ids look absent, and an element another owner
shares is listed only when the caller may read it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import allocation
from app.modules.architecture.schemas import (
    AllocationAcceptIn,
    AllocationAcceptOut,
    AllocationCoverageOut,
    AllocationFailureOut,
    AllocationPairIn,
    AllocationPairOut,
    AllocationViewOut,
)
from app.modules.architecture.service import ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY
from app.modules.architecture.visibility import Viewer
from app.services.link_graph import ArtefactResolver
from app.services.lookups import project_or_404
from app.services.rbac import require_project_subcomponent_enabled


def _out(pairs: list[allocation.Pair]) -> list[AllocationPairOut]:
    """The response rows for pairs."""
    return [
        AllocationPairOut.model_validate({
            "requirement": p.requirement.__dict__, "element": p.element.__dict__, "link_id": p.link_id,
        })
        for p in pairs
    ]


def add_allocation_routes(router: APIRouter) -> None:
    """Adds the allocation routes to `router` (the project router)."""
    view = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY)

    def can_manage(db: Session, user: User, project_id: uuid.UUID) -> bool:
        return ArtefactResolver(db, project_or_404(db, project_id), user.id).link_authority(allocation.REQUIREMENT_TYPE) is not None

    def build(
        db: Session, user: User, project_id: uuid.UUID, *, requirement_id: uuid.UUID | None = None, element_id: uuid.UUID | None = None,
    ) -> AllocationViewOut:
        project = project_or_404(db, project_id)
        viewer = Viewer.of_user(user, project)
        suggested, dismissed = allocation.suggestions(db, project, requirement_id=requirement_id, element_id=element_id)
        return AllocationViewOut(
            allocated=_out(allocation.allocated(db, project, viewer, requirement_id=requirement_id, element_id=element_id)),
            suggested=_out(suggested), dismissed=_out(dismissed), can_manage=can_manage(db, user, project_id),
        )

    @router.get("/requirements/{requirement_id}/allocation", response_model=AllocationViewOut)
    def requirement_allocation(
        project_id: uuid.UUID, requirement_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """The elements a requirement is allocated to, and the elements its component suggests."""
        return build(db, current_user, project_id, requirement_id=requirement_id)

    @router.get("/elements/{element_id}/allocation", response_model=AllocationViewOut)
    def element_allocation(
        project_id: uuid.UUID, element_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """The requirements an element is allocated to, and the requirements its component suggests."""
        return build(db, current_user, project_id, element_id=element_id)

    @router.post("/allocation/accept", response_model=AllocationAcceptOut)
    def accept_allocations(
        project_id: uuid.UUID, payload: AllocationAcceptIn, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Turns suggested pairs into "Allocated to" links; a pair that cannot be accepted is reported, not fatal."""
        result = allocation.accept(
            db, project_or_404(db, project_id), current_user, [(p.requirement_id, p.element_id) for p in payload.pairs],
        )
        db.commit()
        return AllocationAcceptOut(
            accepted=result.accepted,
            failed=[AllocationFailureOut(requirement_id=r, element_id=e, reason=why) for r, e, why in result.failed],
        )

    @router.post("/allocation/dismiss", status_code=status.HTTP_204_NO_CONTENT)
    def dismiss_allocation(
        project_id: uuid.UUID, payload: AllocationPairIn, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Hides a suggested allocation."""
        allocation.dismiss(db, project_or_404(db, project_id), current_user, payload.requirement_id, payload.element_id)
        db.commit()

    @router.post("/allocation/restore", status_code=status.HTTP_204_NO_CONTENT)
    def restore_allocation(
        project_id: uuid.UUID, payload: AllocationPairIn, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Brings a dismissed suggestion back."""
        allocation.restore(db, project_or_404(db, project_id), current_user, payload.requirement_id, payload.element_id)
        db.commit()

    @router.get("/allocation/coverage", response_model=AllocationCoverageOut)
    def allocation_coverage(project_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """The project's allocation counts."""
        return AllocationCoverageOut.model_validate(allocation.coverage(db, project_or_404(db, project_id)).__dict__)
