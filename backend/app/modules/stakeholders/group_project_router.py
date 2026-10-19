"""
Module: modules.stakeholders.group_project_router

Project-scoped Stakeholder Group API, mounted at
`/api/v1/projects/{project_id}/modules/stakeholders` next to the Stakeholder routes: the group tree
(list/create/edit/move/reorder/delete), direct membership, a stakeholder's group
set, and the "create groups from organisation / group text" action. The bodies
live in `_group_shared.py`; this file declares the routes and the gates.

The project sees the organisation's groups (read-only here: they are edited through the org
router) and its own, which may sit under an org group and hold org or project stakeholders.
Stakeholders hidden from the project are neither listed nor addable.

Viewing needs the `stakeholder` sub-component to be enabled; every write needs
`_group_shared.require_group_manage` (a group is
managed by whoever manages Stakeholders, or holds a `(stakeholder_group, manage)` grant).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import _group_shared as gsh
from app.modules.stakeholders.groups import GROUP_ARTEFACT_TYPE
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
from app.services.project_scope import ProjectScope
from app.services.rbac import require_project_subcomponent_enabled
from app.services.tags import TagFilter

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/stakeholders", tags=["stakeholder-groups-project"])

_require_view = require_project_subcomponent_enabled("stakeholders", "stakeholder")


def _ctx(db: Session, project_id: UUID) -> gsh.GroupContext:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return gsh.GroupContext(organization_id=project.organization_id, project=project)


def _require_manage(db: Session, user: User, ctx: gsh.GroupContext) -> None:
    gsh.require_group_manage(db, user, ctx)


def _refs(refs) -> list[StakeholderGroupRefOut]:
    return [StakeholderGroupRefOut(id=r.id, name=r.name, scope=r.scope, parent_group_id=r.parent_group_id) for r in refs]


@router.get("/stakeholder-groups", response_model=list[StakeholderGroupOut])
def list_groups(
    project_id: UUID, tag_filter: TagFilter = Depends(), current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
    project_scope: ProjectScope = Depends(),
):
    """The organisation's groups and this project's own, flat; the client builds the tree from `parent_group_id`."""

    def rows_for(pid: UUID) -> list:
        """This endpoint's rows for one project of the scope."""
        return tag_filter.keep(db, pid, GROUP_ARTEFACT_TYPE, gsh.list_groups(db, _ctx(db, pid)))

    return project_scope.collect(
        db, db.get(Project, project_id), current_user.id, GROUP_ARTEFACT_TYPE, rows_for,
        gate=("stakeholders", "stakeholder"),
    )


@router.get("/stakeholder-groups/text-proposals", response_model=list[GroupTextProposalOut])
def text_proposals(project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The distinct free-text "organisation / group" values that could become groups. Declared
    before `/stakeholder-groups/{id}` so the literal path wins."""
    return gsh.text_proposals(db, _ctx(db, project_id))


@router.post("/stakeholder-groups/from-text", response_model=GroupFromTextOut, status_code=status.HTTP_201_CREATED)
def create_from_text(
    project_id: UUID, payload: GroupFromTextCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates an "Organisation / group" root, a child per chosen text and the memberships that text implies."""
    ctx = _ctx(db, project_id)
    _require_manage(db, current_user, ctx)
    return gsh.create_from_text(db, ctx, payload.names, current_user)


@router.post("/stakeholder-groups", response_model=StakeholderGroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    project_id: UUID, payload: StakeholderGroupCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    ctx = _ctx(db, project_id)
    _require_manage(db, current_user, ctx)
    return gsh.create_group(db, ctx, payload, current_user)


@router.patch("/stakeholder-groups/{group_id}", response_model=StakeholderGroupOut)
def update_group(
    project_id: UUID, group_id: UUID, payload: StakeholderGroupUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Renames, re-describes, re-flags or moves (`parent_group_id`, null for the top level) a group."""
    ctx = _ctx(db, project_id)
    _require_manage(db, current_user, ctx)
    return gsh.update_group(db, ctx, group_id, payload, current_user)


@router.post("/stakeholder-groups/{group_id}/move", response_model=StakeholderGroupOut)
def move_group(
    project_id: UUID, group_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Moves a group up or down among its siblings."""
    ctx = _ctx(db, project_id)
    _require_manage(db, current_user, ctx)
    return gsh.move_group(db, ctx, group_id, payload.direction, current_user)


@router.delete("/stakeholder-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    project_id: UUID, group_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Deletes a group: its memberships go (never the stakeholders) and its children move up to its parent."""
    ctx = _ctx(db, project_id)
    _require_manage(db, current_user, ctx)
    gsh.delete_group(db, ctx, group_id, current_user)


@router.get("/stakeholder-groups/{group_id}/members", response_model=list[StakeholderGroupMemberOut])
def list_members(
    project_id: UUID, group_id: UUID, direct_only: bool = False,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The group's stakeholders, including those in its descendants unless `direct_only=true`."""
    return gsh.list_members(db, _ctx(db, project_id), group_id, direct_only)


@router.post(
    "/stakeholder-groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT,
)
def add_member(
    project_id: UUID, group_id: UUID, payload: StakeholderGroupMemberCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Adds a stakeholder to the group directly (409 if already in it or an exclusive sibling branch holds it)."""
    ctx = _ctx(db, project_id)
    _require_manage(db, current_user, ctx)
    gsh.add_member(db, ctx, group_id, payload.stakeholder_id, current_user)


@router.delete("/stakeholder-groups/{group_id}/members/{stakeholder_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    project_id: UUID, group_id: UUID, stakeholder_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    ctx = _ctx(db, project_id)
    _require_manage(db, current_user, ctx)
    gsh.remove_member(db, ctx, group_id, stakeholder_id, current_user)


@router.get("/stakeholders/{stakeholder_id}/groups", response_model=list[StakeholderGroupRefOut])
def get_stakeholder_groups(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The groups the stakeholder is directly in that this view can see."""
    return _refs(gsh.stakeholder_groups(db, _ctx(db, project_id), stakeholder_id))


@router.put("/stakeholders/{stakeholder_id}/groups", response_model=list[StakeholderGroupRefOut])
def set_stakeholder_groups(
    project_id: UUID, stakeholder_id: UUID, payload: StakeholderGroupIdsSet,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Sets the stakeholder's project groups to exactly `group_ids`; groups of the other tier are untouched."""
    ctx = _ctx(db, project_id)
    _require_manage(db, current_user, ctx)
    return _refs(gsh.set_stakeholder_groups(db, ctx, stakeholder_id, payload.group_ids, current_user))
