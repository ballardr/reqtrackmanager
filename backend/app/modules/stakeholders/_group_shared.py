"""
Module: modules.stakeholders._group_shared

Handler bodies shared by the org-scoped (`group_router.py`) and project-scoped
(`group_project_router.py`) Stakeholder Group routers, so the two declare only
their routes (the `_stakeholder_shared.py` pattern).

Responsibilities:
- `GroupContext`: which tier a router acts on (organisation or project) and the
  stakeholders it may touch, hiding the org/project difference from the bodies.
- Group CRUD/move, direct membership, a stakeholder's group set, and the
  "create from organisation / group text" action, each audit-logged with ids
  only (item 23) and translating `groups.GroupRuleError` to its HTTP status.
- `filter_and_sort_stakeholders`: the list endpoints' `group_id` /
  `direct_only` / `group_by` handling.

RBAC: callers have already passed `require_group_manage` for writes (item 31: groups
share the Stakeholder manage gate, plus their own `(stakeholder_group, manage)` grant). A project
context never reads or lists a stakeholder hidden from that project (Phase 3b).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import groups as grp
from app.modules.stakeholders._stakeholder_shared import get_stakeholder_in_scope, require_stakeholder_manage
from app.modules.stakeholders.enums import StakeholderScope
from app.modules.stakeholders.models import Stakeholder, StakeholderGroup, StakeholderGroupMember
from app.modules.stakeholders.schemas import (
    GroupFromTextOut,
    GroupTextProposalOut,
    StakeholderGroupCreate,
    StakeholderGroupMemberOut,
    StakeholderGroupOut,
    StakeholderGroupUpdate,
)
from app.modules.stakeholders.service import (
    get_current_stakeholder_version,
    hidden_stakeholder_ids,
    list_project_visible_stakeholders,
)
from app.services.audit import log_event
from app.services.ordering import move_ordered
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied

GROUP_MANAGE_PERMISSION = encode_permission(grp.GROUP_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)


@dataclass(frozen=True)
class GroupContext:
    """The tier a group router acts on: `project` is set for the project router, else it is the organisation's."""

    organization_id: uuid.UUID
    project: Project | None = None

    @property
    def scope(self) -> StakeholderScope:
        return StakeholderScope.PROJECT if self.project else StakeholderScope.ORGANIZATION

    @property
    def project_id(self) -> uuid.UUID | None:
        return self.project.id if self.project else None


def require_group_manage(db: Session, user: User, ctx: GroupContext) -> None:
    """Gate for every group write: whoever may manage Stakeholders of this tier (the owner role or a
    `(stakeholder, manage)` grant), or a Fine-Grained Access Control `(stakeholder_group, manage)` grant.

    Raises:
        HTTPException: 403 if none holds.
    """
    try:
        require_stakeholder_manage(db, user, ctx.scope, organization_id=ctx.organization_id, project_id=ctx.project_id)
        return
    except HTTPException:
        pass
    held = get_effective_permissions(db, user.id, organization_id=ctx.organization_id, project_id=ctx.project_id)
    if not permission_satisfied(held, GROUP_MANAGE_PERMISSION):
        raise HTTPException(403, "Only a Stakeholder Owner (or admin/manager) may do this.")


def as_http(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Calls `fn`, answering a `GroupRuleError` with the HTTP status it carries."""
    try:
        return fn(*args, **kwargs)
    except grp.GroupRuleError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


def _universe(db: Session, ctx: GroupContext) -> dict[uuid.UUID, StakeholderGroup]:
    return grp.load_groups(db, ctx.organization_id, ctx.project_id)


def _hidden(db: Session, ctx: GroupContext) -> set[uuid.UUID]:
    return hidden_stakeholder_ids(db, ctx.project.id) if ctx.project else set()


def _log(db: Session, ctx: GroupContext, actor: User, group_id: uuid.UUID, action: str, **detail: Any) -> None:
    log_event(
        db, entity_type=grp.GROUP_ARTEFACT_TYPE, entity_id=group_id, action=action, actor_id=actor.id,
        organization_id=ctx.organization_id if not ctx.project else None, project_id=ctx.project_id,
        detail={k: str(v) for k, v in detail.items()} or None,
    )


def _get_group(db: Session, ctx: GroupContext, group_id: uuid.UUID) -> StakeholderGroup:
    return as_http(
        grp.get_group_in_scope, db, ctx.scope, organization_id=ctx.organization_id, project_id=ctx.project_id,
        group_id=group_id,
    )


def _visible_group(db: Session, ctx: GroupContext, group_id: uuid.UUID) -> StakeholderGroup:
    group = _universe(db, ctx).get(group_id)
    if group is None:
        raise HTTPException(404, "Stakeholder group not found.")
    return group


def _get_stakeholder(db: Session, ctx: GroupContext, stakeholder_id: uuid.UUID) -> Stakeholder:
    """A stakeholder this context may attach to groups: an org one (org router), or a project's own / visible org one."""
    if ctx.project is None:
        return get_stakeholder_in_scope(
            db, StakeholderScope.ORGANIZATION, organization_id=ctx.organization_id, stakeholder_id=stakeholder_id
        )
    from app.modules.stakeholders._shared import get_visible_stakeholder

    return get_visible_stakeholder(db, ctx.project, stakeholder_id)


# --- Groups ----------------------------------------------------------------------------------


def groups_out(db: Session, ctx: GroupContext, groups: list[StakeholderGroup]) -> list[StakeholderGroupOut]:
    """API shape of groups, with direct member counts (excluding stakeholders hidden from the project) and child counts."""
    ids = [g.id for g in groups]
    hidden = _hidden(db, ctx)
    members: dict[uuid.UUID, int] = {}
    if ids:
        from sqlalchemy import select

        for gid, sid in db.execute(select(StakeholderGroupMember.group_id, StakeholderGroupMember.stakeholder_id).where(
            StakeholderGroupMember.group_id.in_(ids)
        )).all():
            if sid not in hidden:
                members[gid] = members.get(gid, 0) + 1
    # Child counts come from the groups this viewer can see, so an organisation group does not reveal how many
    # groups other projects have placed under it.
    visible = _universe(db, ctx)
    children: dict[uuid.UUID, int] = {}
    for g in visible.values():
        if g.parent_group_id is not None:
            children[g.parent_group_id] = children.get(g.parent_group_id, 0) + 1
    return [
        StakeholderGroupOut(
            id=g.id, scope=g.scope, organization_id=g.organization_id, project_id=g.project_id,
            parent_group_id=g.parent_group_id, name=g.name, description=g.description,
            exclusive_children=g.exclusive_children, sort_order=g.sort_order,
            member_count=members.get(g.id, 0), child_count=children.get(g.id, 0),
        )
        for g in groups
    ]


def list_groups(db: Session, ctx: GroupContext) -> list[StakeholderGroupOut]:
    """Every group the context can see, org groups first then the project's, each in sort order."""
    ordered = sorted(
        _universe(db, ctx).values(),
        key=lambda g: (g.scope != StakeholderScope.ORGANIZATION, g.sort_order, g.name.lower()),
    )
    return groups_out(db, ctx, ordered)


def create_group(db: Session, ctx: GroupContext, payload: StakeholderGroupCreate, actor: User) -> StakeholderGroupOut:
    group = as_http(
        grp.create_group, db, scope=ctx.scope, organization_id=ctx.organization_id, project_id=ctx.project_id,
        name=payload.name, description=payload.description, parent_group_id=payload.parent_group_id,
        exclusive_children=payload.exclusive_children,
    )
    _log(db, ctx, actor, group.id, "created", parent_group_id=group.parent_group_id)
    db.commit()
    return groups_out(db, ctx, [group])[0]


def update_group(
    db: Session, ctx: GroupContext, group_id: uuid.UUID, payload: StakeholderGroupUpdate, actor: User
) -> StakeholderGroupOut:
    group = _get_group(db, ctx, group_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name") is None:
        changes.pop("name", None)
    if changes.get("exclusive_children") is None:
        changes.pop("exclusive_children", None)
    as_http(grp.update_group, db, group, ctx.organization_id, ctx.project_id, changes)
    _log(db, ctx, actor, group.id, "moved" if "parent_group_id" in changes else "updated", fields=",".join(sorted(changes)))
    db.commit()
    return groups_out(db, ctx, [group])[0]


def move_group(db: Session, ctx: GroupContext, group_id: uuid.UUID, direction: str, actor: User) -> StakeholderGroupOut:
    """Swaps the group's sort order with its neighbour among its siblings."""
    group = _get_group(db, ctx, group_id)
    if direction not in ("up", "down"):
        raise HTTPException(422, "direction must be 'up' or 'down'.")
    move_ordered(
        db, StakeholderGroup, grp.sibling_filters(group.scope, ctx.organization_id, ctx.project_id, group.parent_group_id),
        group.id, direction,
    )
    _log(db, ctx, actor, group.id, "reordered", direction=direction)
    db.commit()
    db.refresh(group)
    return groups_out(db, ctx, [group])[0]


def delete_group(db: Session, ctx: GroupContext, group_id: uuid.UUID, actor: User) -> None:
    group = _get_group(db, ctx, group_id)
    members, children = as_http(grp.delete_group, db, group)
    _log(db, ctx, actor, group_id, "deleted", members_removed=members, children_promoted=children)
    db.commit()


# --- Membership ------------------------------------------------------------------------------


def list_members(db: Session, ctx: GroupContext, group_id: uuid.UUID, direct_only: bool) -> list[StakeholderGroupMemberOut]:
    """The group's stakeholders (including those in descendants unless `direct_only`), minus any hidden from the project."""
    universe = _universe(db, ctx)
    group = _visible_group(db, ctx, group_id)
    ids = {group.id} if direct_only else {group.id, *grp.descendant_ids(universe, group.id)}
    direct = grp.member_ids(db, {group.id})
    hidden = _hidden(db, ctx)
    out = []
    for sid in grp.member_ids(db, ids) - hidden:
        stakeholder = db.get(Stakeholder, sid)
        if stakeholder is None or stakeholder.is_archived:
            continue
        out.append(StakeholderGroupMemberOut(
            stakeholder_id=sid, name=get_current_stakeholder_version(db, sid).name, scope=stakeholder.scope,
            direct=sid in direct,
        ))
    return sorted(out, key=lambda m: m.name.lower())


def add_member(db: Session, ctx: GroupContext, group_id: uuid.UUID, stakeholder_id: uuid.UUID, actor: User) -> None:
    group = _get_group(db, ctx, group_id)
    stakeholder = _get_stakeholder(db, ctx, stakeholder_id)
    as_http(grp.add_member, db, group, stakeholder, _universe(db, ctx), ctx.organization_id, ctx.project_id)
    _log(db, ctx, actor, group.id, "member_added", stakeholder_id=stakeholder.id)
    db.commit()


def remove_member(db: Session, ctx: GroupContext, group_id: uuid.UUID, stakeholder_id: uuid.UUID, actor: User) -> None:
    group = _get_group(db, ctx, group_id)
    _get_stakeholder(db, ctx, stakeholder_id)
    if not grp.remove_member(db, group, stakeholder_id):
        raise HTTPException(404, "This Stakeholder is not directly in the group.")
    _log(db, ctx, actor, group.id, "member_removed", stakeholder_id=stakeholder_id)
    db.commit()


def stakeholder_groups(db: Session, ctx: GroupContext, stakeholder_id: uuid.UUID) -> list[grp.GroupRef]:
    """The stakeholder's direct groups the context can see."""
    stakeholder = _get_stakeholder(db, ctx, stakeholder_id)
    return grp.group_refs(db, [stakeholder.id], _universe(db, ctx))[stakeholder.id]


def set_stakeholder_groups(
    db: Session, ctx: GroupContext, stakeholder_id: uuid.UUID, group_ids: list[uuid.UUID], actor: User
) -> list[grp.GroupRef]:
    """Replaces the stakeholder's memberships in this tier's groups (groups of the other tier are untouched)."""
    stakeholder = _get_stakeholder(db, ctx, stakeholder_id)
    universe = _universe(db, ctx)
    added, removed = as_http(
        grp.set_tier_memberships, db, stakeholder, set(group_ids), ctx.scope, universe, ctx.organization_id,
        ctx.project_id,
    )
    for gid in sorted(added, key=str):
        _log(db, ctx, actor, gid, "member_added", stakeholder_id=stakeholder.id)
    for gid in sorted(removed, key=str):
        _log(db, ctx, actor, gid, "member_removed", stakeholder_id=stakeholder.id)
    db.commit()
    return grp.group_refs(db, [stakeholder.id], universe)[stakeholder.id]


# --- From free text --------------------------------------------------------------------------


def _text_stakeholders(db: Session, ctx: GroupContext) -> list[Stakeholder]:
    """The stakeholders whose free-text field feeds the proposals: the org's (org router), or all this project can see."""
    if ctx.project is not None:
        return list_project_visible_stakeholders(db, ctx.project)
    from sqlalchemy import select

    return list(db.scalars(select(Stakeholder).where(
        Stakeholder.organization_id == ctx.organization_id, Stakeholder.scope == StakeholderScope.ORGANIZATION,
        Stakeholder.is_archived.is_(False),
    )))


def text_proposals(db: Session, ctx: GroupContext) -> list[GroupTextProposalOut]:
    return [GroupTextProposalOut(**p) for p in grp.text_proposals(db, _text_stakeholders(db, ctx), _universe(db, ctx))]


def create_from_text(db: Session, ctx: GroupContext, names: list[str], actor: User) -> GroupFromTextOut:
    root, children, added = as_http(
        grp.create_from_text, db, scope=ctx.scope, organization_id=ctx.organization_id, project_id=ctx.project_id,
        stakeholders=_text_stakeholders(db, ctx), names=names,
    )
    _log(db, ctx, actor, root.id, "created_from_text", groups=len(children), memberships_added=added)
    db.commit()
    return GroupFromTextOut(root_group_id=root.id, group_ids=[c.id for c in children], memberships_added=added)


# --- Stakeholder list filtering ----------------------------------------------------------------


def filter_and_sort_stakeholders(
    db: Session, stakeholders: list[Stakeholder], universe: dict[uuid.UUID, StakeholderGroup], *,
    group_id: uuid.UUID | None, direct_only: bool, group_by: uuid.UUID | None,
) -> list[Stakeholder]:
    """Narrows to a group's members (with its descendants' unless `direct_only`) and/or orders by branch under a root group.

    Raises:
        HTTPException: 404 if `group_id` is not a reachable group; 400 if `group_by` is not a reachable root group.
    """
    if group_id is not None:
        group = universe.get(group_id)
        if group is None:
            raise HTTPException(404, "Stakeholder group not found.")
        ids = {group.id} if direct_only else {group.id, *grp.descendant_ids(universe, group.id)}
        members = grp.member_ids(db, ids)
        stakeholders = [s for s in stakeholders if s.id in members]
    if group_by is not None:
        root = universe.get(group_by)
        if root is None or root.parent_group_id is not None:
            raise HTTPException(400, "group_by must be a top-level stakeholder group.")
        refs = grp.group_refs(db, [s.id for s in stakeholders], universe)
        stakeholders = sorted(stakeholders, key=lambda s: grp.branch_sort_key(refs[s.id], universe, group_by))
    return stakeholders
