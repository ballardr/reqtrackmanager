"""
Module: modules.stakeholders.group_router

Org-scoped Stakeholder Group API (Phase 3c), mounted at
`/api/v1/orgs/{organization_id}/modules/stakeholders` next to the Stakeholder routes: the group tree
(list/create/edit/move/reorder/delete), direct membership, a stakeholder's group
set, and the "create groups from organisation / group text" action. The bodies
live in `_group_shared.py`; this file declares the routes and the gates.

Org groups hold org-scoped stakeholders only (item 26).

Viewing needs the `stakeholder` sub-component to be enabled; every write needs
`_group_shared.require_group_manage` (item 31 of the plan's addendum 3: a group is
managed by whoever manages Stakeholders, or holds a `(stakeholder_group, manage)` grant).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.modules.stakeholders import _group_shared as gsh
from app.modules.stakeholders.schemas import (
    GroupFromTextCreate,
    GroupFromTextOut,
    GroupTextProposalOut,
    StakeholderGroupCreate,
    StakeholderGroupIdsSet,
    StakeholderGroupMemberCreate,
    StakeholderGroupMemberOut,
    StakeholderGroupOut,
    StakeholderGroupRefOut,
    StakeholderGroupUpdate,
)
from app.schemas.project import MoveDirection
from app.services.rbac import require_org_subcomponent_enabled

router = APIRouter(prefix="/api/v1/orgs/{organization_id}/modules/stakeholders", tags=["stakeholder-groups-org"])

_require_view = require_org_subcomponent_enabled("stakeholders", "stakeholder")


def _ctx(db: Session, organization_id: UUID) -> gsh.GroupContext:
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return gsh.GroupContext(organization_id=organization_id)


def _require_manage(db: Session, user: User, ctx: gsh.GroupContext) -> None:
    gsh.require_group_manage(db, user, ctx)


def _refs(refs) -> list[StakeholderGroupRefOut]:
    return [StakeholderGroupRefOut(id=r.id, name=r.name, scope=r.scope, parent_group_id=r.parent_group_id) for r in refs]


@router.get("/stakeholder-groups", response_model=list[StakeholderGroupOut])
def list_groups(organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The organisation's groups, flat; the client builds the tree from `parent_group_id`."""
    return gsh.list_groups(db, _ctx(db, organization_id))


@router.get("/stakeholder-groups/text-proposals", response_model=list[GroupTextProposalOut])
def text_proposals(organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The distinct free-text "organisation / group" values that could become groups. Declared
    before `/stakeholder-groups/{id}` so the literal path wins."""
    return gsh.text_proposals(db, _ctx(db, organization_id))


@router.post("/stakeholder-groups/from-text", response_model=GroupFromTextOut, status_code=status.HTTP_201_CREATED)
def create_from_text(
    organization_id: UUID, payload: GroupFromTextCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates an "Organisation / group" root, a child per chosen text and the memberships that text implies."""
    ctx = _ctx(db, organization_id)
    _require_manage(db, current_user, ctx)
    return gsh.create_from_text(db, ctx, payload.names, current_user)


@router.post("/stakeholder-groups", response_model=StakeholderGroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    organization_id: UUID, payload: StakeholderGroupCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    ctx = _ctx(db, organization_id)
    _require_manage(db, current_user, ctx)
    return gsh.create_group(db, ctx, payload, current_user)


@router.patch("/stakeholder-groups/{group_id}", response_model=StakeholderGroupOut)
def update_group(
    organization_id: UUID, group_id: UUID, payload: StakeholderGroupUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Renames, re-describes, re-flags or moves (`parent_group_id`, null for the top level) a group."""
    ctx = _ctx(db, organization_id)
    _require_manage(db, current_user, ctx)
    return gsh.update_group(db, ctx, group_id, payload, current_user)


@router.post("/stakeholder-groups/{group_id}/move", response_model=StakeholderGroupOut)
def move_group(
    organization_id: UUID, group_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Moves a group up or down among its siblings."""
    ctx = _ctx(db, organization_id)
    _require_manage(db, current_user, ctx)
    return gsh.move_group(db, ctx, group_id, payload.direction, current_user)


@router.delete("/stakeholder-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    organization_id: UUID, group_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Deletes a group: its memberships go (never the stakeholders) and its children move up to its parent."""
    ctx = _ctx(db, organization_id)
    _require_manage(db, current_user, ctx)
    gsh.delete_group(db, ctx, group_id, current_user)


@router.get("/stakeholder-groups/{group_id}/members", response_model=list[StakeholderGroupMemberOut])
def list_members(
    organization_id: UUID, group_id: UUID, direct_only: bool = False,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The group's stakeholders, including those in its descendants unless `direct_only=true`."""
    return gsh.list_members(db, _ctx(db, organization_id), group_id, direct_only)


@router.post(
    "/stakeholder-groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT,
)
def add_member(
    organization_id: UUID, group_id: UUID, payload: StakeholderGroupMemberCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Adds a stakeholder to the group directly (409 if already in it or an exclusive sibling branch holds it)."""
    ctx = _ctx(db, organization_id)
    _require_manage(db, current_user, ctx)
    gsh.add_member(db, ctx, group_id, payload.stakeholder_id, current_user)


@router.delete("/stakeholder-groups/{group_id}/members/{stakeholder_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    organization_id: UUID, group_id: UUID, stakeholder_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    ctx = _ctx(db, organization_id)
    _require_manage(db, current_user, ctx)
    gsh.remove_member(db, ctx, group_id, stakeholder_id, current_user)


@router.get("/stakeholders/{stakeholder_id}/groups", response_model=list[StakeholderGroupRefOut])
def get_stakeholder_groups(
    organization_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The groups the stakeholder is directly in that this view can see."""
    return _refs(gsh.stakeholder_groups(db, _ctx(db, organization_id), stakeholder_id))


@router.put("/stakeholders/{stakeholder_id}/groups", response_model=list[StakeholderGroupRefOut])
def set_stakeholder_groups(
    organization_id: UUID, stakeholder_id: UUID, payload: StakeholderGroupIdsSet,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Sets the stakeholder's organisation groups to exactly `group_ids`; groups of the other tier are untouched."""
    ctx = _ctx(db, organization_id)
    _require_manage(db, current_user, ctx)
    return _refs(gsh.set_stakeholder_groups(db, ctx, stakeholder_id, payload.group_ids, current_user))
