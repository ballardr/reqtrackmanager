"""
Module: routers.orgs.groups

Organisation groups (C-U-08, C-U-12): create/list/update (IdP-sync target
and granted-role configuration, item 522) and member/nested-group
add/remove.

Split out of the former flat `routers/orgs.py` as a pure code-organization
refactor — see `routers/orgs/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import OrgGroup, OrgGroupMember
from app.models.user import User
from app.modules.registry import run_org_group_member_removal_hooks
from app.schemas.org import OrgGroupCreate, OrgGroupMemberAdd, OrgGroupOut, OrgGroupUpdate
from app.services.audit import log_event
from app.services.rbac import get_effective_org_roles, require_org_role, would_create_org_group_cycle

router = APIRouter(tags=["organizations-groups"])


@router.post("/{organization_id}/groups", response_model=OrgGroupOut, status_code=status.HTTP_201_CREATED)
def create_org_group(
    organization_id: UUID,
    payload: OrgGroupCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Creates an organisation group (C-U-08), optionally marking it as
    IdP-synced from creation (`payload.idp_synced_group_name`) and/or
    granting an org role to anyone synced into it (`payload.
    granted_org_role`, 2026-08 UX audit roadmap item 522)."""
    if payload.idp_synced_group_name:
        _require_idp_synced_name_available(db, organization_id, payload.idp_synced_group_name)
    _require_granted_role_has_sync_target(payload.granted_org_role, payload.idp_synced_group_name)
    group = OrgGroup(
        organization_id=organization_id, name=payload.name, idp_synced_group_name=payload.idp_synced_group_name,
        granted_org_role=payload.granted_org_role,
    )
    db.add(group)
    db.flush()
    log_event(
        db, entity_type="org_group", entity_id=group.id, action="created", actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()
    return OrgGroupOut(
        id=group.id, name=group.name, member_user_ids=[], member_org_group_ids=[],
        idp_synced_group_name=group.idp_synced_group_name, granted_org_role=group.granted_org_role,
    )


@router.get("/{organization_id}/groups", response_model=list[OrgGroupOut])
def list_org_groups(
    organization_id: UUID,
    response: Response,
    search: str | None = None,
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's groups, each with its resolved member/nested-
    group id lists.

    `search` (name substring, case-insensitive) and `limit`/`offset`
    (U-P-06, 2026-08 UX audit "Directories at scale") are optional — same
    contract as `list_org_users`/`list_requirements`: omitting `limit`
    returns every group unpaginated (existing callers, e.g. Project Admin's
    own org-group nesting picker, rely on exactly this to keep working
    unchanged), and when given, the pre-slice total is returned via
    `X-Total-Count`.

    `order` (Phase B, follow-up UX batch, 2026-08-31 — `DirectoryTable`'s
    Name column is this list's only sortable column, so there's no
    separate `sort` param to pick a field the way `list_org_users` has;
    only which direction to apply to the existing name order) defaults to
    `asc` (unchanged pre-existing behaviour) — style guide "Pattern:
    sortable column header"'s "already pages via limit/offset -> backend
    sort/order params" branch, since a client-side sort of only the
    currently-loaded page would misrepresent the true full-list order.

    `granted_org_role` (item 522) is masked to `None` for a non-admin
    caller — this endpoint is deliberately open to any org member (a
    `MEMBER`/`PROJECT_CREATOR` needs group names/ids for the nesting
    picker above), but which group auto-grants which `OrgRole` via SSO
    sync is exactly the kind of privilege-configuration detail
    `sso_group_mappings` used to keep behind the `ORG_ADMIN`-only
    `GET .../advanced-settings` before this field existed — hardening-pass
    finding: it must not become member-readable recon just because it
    moved onto an already-broadly-readable endpoint.
    """
    is_admin = OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
    query = select(OrgGroup).where(OrgGroup.organization_id == organization_id)
    if search:
        query = query.where(OrgGroup.name.ilike(f"%{search}%"))
    name_order = OrgGroup.name.desc() if order == "desc" else OrgGroup.name
    groups = db.scalars(query.order_by(name_order)).all()

    response.headers["X-Total-Count"] = str(len(groups))
    if limit is not None:
        groups = groups[offset:offset + limit]

    out = []
    for g in groups:
        member_ids = db.scalars(
            select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == g.id, OrgGroupMember.user_id.is_not(None))
        ).all()
        nested_group_ids = db.scalars(
            select(OrgGroupMember.member_org_group_id).where(
                OrgGroupMember.org_group_id == g.id, OrgGroupMember.member_org_group_id.is_not(None)
            )
        ).all()
        out.append(
            OrgGroupOut(
                id=g.id, name=g.name, member_user_ids=list(member_ids), member_org_group_ids=list(nested_group_ids),
                idp_synced_group_name=g.idp_synced_group_name,
                granted_org_role=g.granted_org_role if is_admin else None,
            )
        )
    return out


def _require_granted_role_has_sync_target(granted_org_role, idp_synced_group_name: str | None) -> None:
    """Rejects with 400 if `granted_org_role` is set without a resolved
    `idp_synced_group_name` — granting a role via SSO group membership is
    meaningless without an IdP claim to trigger it on (`OrgGroup.
    granted_org_role`'s model docstring). `idp_synced_group_name` is passed
    already resolved (payload value if provided, otherwise the group's
    existing one) so this same check works for both create and update."""
    if granted_org_role is not None and not idp_synced_group_name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "granted_org_role requires idp_synced_group_name to also be set — a role can only be granted via a "
            "matching IdP group claim.",
        )


def _require_idp_synced_name_available(db: Session, organization_id: UUID, name: str, *, exclude_group_id: UUID | None = None) -> None:
    """Rejects with 400 if another `OrgGroup` in this org already claims
    `name` as its IdP-sync target — enforced here (in addition to the
    partial unique index, the real guarantee under concurrent writes) so a
    routine admin mistake gets a clear error instead of a raw
    `IntegrityError`."""
    conflict_query = select(OrgGroup).where(
        OrgGroup.organization_id == organization_id, OrgGroup.idp_synced_group_name == name
    )
    if exclude_group_id is not None:
        conflict_query = conflict_query.where(OrgGroup.id != exclude_group_id)
    if db.scalar(conflict_query) is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Another group is already synced from IdP group '{name}'."
        )


@router.patch("/{organization_id}/groups/{group_id}", response_model=OrgGroupOut)
def update_org_group(
    organization_id: UUID,
    group_id: UUID,
    payload: OrgGroupUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sets or clears an org group's IdP-sync target
    (`OrgGroup.idp_synced_group_name`) and the org role it grants
    (`OrgGroup.granted_org_role`, 2026-08 UX audit roadmap item 522) — the
    only mutable fields an org group has today (no rename endpoint exists
    for this or `ProjectGroup`). Both are always set wholesale from the
    payload (not merged), matching this endpoint's existing "set or clear"
    semantics for `idp_synced_group_name` from before `granted_org_role`
    existed.
    """
    group = _get_org_group_in_org(db, organization_id, group_id)
    if payload.idp_synced_group_name:
        _require_idp_synced_name_available(db, organization_id, payload.idp_synced_group_name, exclude_group_id=group_id)
    _require_granted_role_has_sync_target(payload.granted_org_role, payload.idp_synced_group_name)
    group.idp_synced_group_name = payload.idp_synced_group_name
    group.granted_org_role = payload.granted_org_role
    log_event(
        db, entity_type="org_group", entity_id=group_id, action="idp_sync_updated", actor_id=current_user.id,
        organization_id=organization_id,
        detail={
            "idp_synced_group_name": payload.idp_synced_group_name,
            "granted_org_role": payload.granted_org_role.value if payload.granted_org_role else None,
        },
    )
    db.commit()
    db.refresh(group)
    member_ids = db.scalars(
        select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == group.id, OrgGroupMember.user_id.is_not(None))
    ).all()
    nested_group_ids = db.scalars(
        select(OrgGroupMember.member_org_group_id).where(
            OrgGroupMember.org_group_id == group.id, OrgGroupMember.member_org_group_id.is_not(None)
        )
    ).all()
    return OrgGroupOut(
        id=group.id, name=group.name, member_user_ids=list(member_ids), member_org_group_ids=list(nested_group_ids),
        idp_synced_group_name=group.idp_synced_group_name, granted_org_role=group.granted_org_role,
    )


def _get_org_group_in_org(db: Session, organization_id: UUID, group_id: UUID) -> OrgGroup:
    """Loads an org group and 404s unless it belongs to `organization_id`.

    Without this check, an org_admin of organization A — validated only
    against the `organization_id` path param — could add/remove members of
    an org group belonging to a *different* organisation by supplying its
    id, a cross-tenant IDOR.
    """
    group = db.get(OrgGroup, group_id)
    if group is None or group.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Org group not found.")
    return group


@router.post("/{organization_id}/groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_org_group_member(
    organization_id: UUID,
    group_id: UUID,
    payload: OrgGroupMemberAdd,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Adds a member to an organisation group: either a user, or another
    org group nested inside it (exactly one of `payload.user_id`/
    `payload.member_org_group_id`, same convention as
    `add_project_group_member`).

    Hardening-review finding (user branch): this endpoint checked that
    `group_id` belongs to `organization_id`, but never that
    `payload.user_id` itself holds any role in that organisation — unlike
    the structurally parallel `add_project_group_member`
    (`routers/projects.py`), which explicitly enforces C-U-02 ("All Project
    users must be an organisation user") via `_require_user_in_org`.
    Because `get_effective_project_roles` resolves project access through
    org groups nested into project groups purely from `OrgGroupMember` rows
    (re-checking only that the *group's* org matches the project's, never
    that the *member* actually belongs to that org), an org admin adding an
    arbitrary user id here — anyone in the system, with zero relationship
    to this organisation — would have silently handed that user full
    project access the moment this group is (routinely, legitimately)
    nested into any project group. A genuine cross-tenant privilege
    escalation, not merely a data-integrity nit.
    """
    if not payload.user_id and not payload.member_org_group_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide user_id or member_org_group_id.")
    _get_org_group_in_org(db, organization_id, group_id)

    if payload.user_id is not None:
        if not get_effective_org_roles(db, payload.user_id, organization_id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "The user must be a member of this organisation first."
            )
        existing = db.scalar(
            select(OrgGroupMember).where(
                OrgGroupMember.org_group_id == group_id, OrgGroupMember.user_id == payload.user_id
            )
        )
        if existing is None:
            db.add(OrgGroupMember(org_group_id=group_id, user_id=payload.user_id))
            log_event(
                db, entity_type="org_group", entity_id=group_id, action="member_added", actor_id=current_user.id,
                organization_id=organization_id, detail={"user_id": str(payload.user_id)},
            )
            db.commit()
    else:
        # Nesting a group belonging to a different organisation would let
        # its members inherit membership here, crossing the tenant boundary
        # — same reasoning as `add_project_group_member`'s org_group_id
        # branch, one level up.
        child_group = _get_org_group_in_org(db, organization_id, payload.member_org_group_id)
        if child_group.id == group_id or would_create_org_group_cycle(db, group_id, child_group.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This would create a cycle of nested groups.")
        existing = db.scalar(
            select(OrgGroupMember).where(
                OrgGroupMember.org_group_id == group_id, OrgGroupMember.member_org_group_id == child_group.id
            )
        )
        if existing is None:
            db.add(OrgGroupMember(org_group_id=group_id, member_org_group_id=child_group.id))
            log_event(
                db, entity_type="org_group", entity_id=group_id, action="nested_group_added", actor_id=current_user.id,
                organization_id=organization_id, detail={"member_org_group_id": str(child_group.id)},
            )
            db.commit()


@router.delete("/{organization_id}/groups/{group_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_group_member(
    organization_id: UUID,
    group_id: UUID,
    member_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Removes a member from an organisation group — `member_id` is matched
    against either a user member or a nested-group member (whichever it
    is), same generic-id convention as `remove_project_group_member`.

    Phase 22 (docs/compliance-module-plan.md): when `member_id` names a
    genuine *user* member (never a nested-group member — a module-owned
    floor concept is about real people, not group structure), every
    registered module gets a chance to block this specific removal via
    `run_org_group_member_removal_hooks` (e.g. Compliance's own "this group
    is a standard's last fallback compliance-manager coverage" check) —
    core code deciding to ask, without importing any specific module's own
    models, per the Modular Feature System Boundary."""
    _get_org_group_in_org(db, organization_id, group_id)
    is_user_member = db.scalar(
        select(OrgGroupMember.id).where(OrgGroupMember.org_group_id == group_id, OrgGroupMember.user_id == member_id)
    ) is not None
    if is_user_member:
        block_message = run_org_group_member_removal_hooks(db, group_id, member_id)
        if block_message is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, block_message)
    db.execute(
        OrgGroupMember.__table__.delete().where(
            OrgGroupMember.org_group_id == group_id,
            (OrgGroupMember.user_id == member_id) | (OrgGroupMember.member_org_group_id == member_id),
        )
    )
    log_event(
        db, entity_type="org_group", entity_id=group_id, action="member_removed", actor_id=current_user.id,
        organization_id=organization_id, detail={"member_id": str(member_id)},
    )
    db.commit()

