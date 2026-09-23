"""
Module: routers.orgs.custom_roles

Fine-Grained Access Control (`docs/plans/core-fine-grained-access-control-
plan.md` Phase 3) — the permission vocabulary listing, `CustomRoleDefinition`
CRUD, and its user/group grant endpoints.

`CustomRoleDefinition` create/update/delete stays `ORG_ADMIN`-only
(`require_org_admin_or_server_admin`) and is never delegable via any
permission atom (Phase 0 Q5: no "manage custom roles" atom exists) — only
the *grant* endpoints (assigning an already-defined role to a user/group)
additionally accept a `grant_roles` holder (Phase 0 Q6), via
`app.services.rbac.require_org_admin_or_grant_roles`.

Split out as its own router in the `orgs` package, following the same
per-concern layout `routers/orgs/__init__.py`'s docstring describes for
`core`/`membership`/`groups`/etc.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, GroupCustomRoleGrant, UserCustomRoleGrant
from app.models.enums import OrgRole
from app.models.notification import NotificationType
from app.models.organization import OrgGroup
from app.models.project import Project
from app.models.user import User
from app.routers.projects.core import _require_user_in_org
from app.schemas.org import (
    CustomRoleDefinitionCreate,
    CustomRoleDefinitionOut,
    CustomRoleDefinitionUpdate,
    CustomRoleGrantTarget,
    PermissionOut,
)
from app.services.audit import log_event
from app.services.notifications import notify
from app.services.permissions import get_all_permissions, validate_permission_key
from app.services.rbac import require_org_admin_or_grant_roles, require_org_admin_or_server_admin, require_org_role

router = APIRouter(tags=["organizations-custom-roles"])

# Any real org role may see the permission vocabulary and the list of
# defined custom roles — the same "structure, not content" gate
# `list_org_module_roles` already uses for the analogous "what role options
# exist" listing (`routers.orgs.membership`), since a `grant_roles` holder
# needs to see this to know what's grantable, and it carries no more
# sensitivity than the existing fixed/module role option lists do (Phase 3
# task's own judgment call — the alternative, `require_org_admin_or_server_
# admin`, would block a non-admin `grant_roles` holder from seeing what
# they can actually grant).
_VIEW_ROLES = (OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)


def _permissions_by_role_id(db: Session, role_ids: list[UUID]) -> dict[UUID, list[str]]:
    """Batch-loads every `CustomRolePermission.permission` for `role_ids`,
    grouped by `custom_role_id` — avoids an N+1 query when rendering a
    list of roles (`list_custom_roles`)."""
    if not role_ids:
        return {}
    result: dict[UUID, list[str]] = {role_id: [] for role_id in role_ids}
    rows = db.execute(
        select(CustomRolePermission.custom_role_id, CustomRolePermission.permission).where(
            CustomRolePermission.custom_role_id.in_(role_ids)
        )
    ).all()
    for role_id, permission in rows:
        result[role_id].append(permission)
    return result


def _custom_role_definition_out(role: CustomRoleDefinition, permissions: list[str]) -> CustomRoleDefinitionOut:
    return CustomRoleDefinitionOut(
        id=role.id,
        organization_id=role.organization_id,
        name=role.name,
        description=role.description,
        scope=role.scope,
        created_by=role.created_by,
        created_at=role.created_at,
        permissions=sorted(permissions),
    )


def _get_org_custom_role(db: Session, organization_id: UUID, role_id: UUID) -> CustomRoleDefinition:
    """Loads a `CustomRoleDefinition` and 404s unless it belongs to
    `organization_id` — tenant isolation (Design Principle 2): a role from
    another organisation must never be visible or actionable through this
    org's own URL, so a cross-org id gets the same 404 a nonexistent id
    would, never a 403 that would confirm the role exists elsewhere."""
    role = db.get(CustomRoleDefinition, role_id)
    if role is None or role.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Custom role not found.")
    return role


def _validate_scope(scope: str) -> None:
    if scope not in ("org", "project"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "scope must be 'org' or 'project'.")


def _validate_permission_keys(db: Session, organization_id: UUID, permissions: list[str]) -> None:
    for permission in permissions:
        try:
            validate_permission_key(db, organization_id, permission)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _validate_grant_project_id(
    db: Session, role: CustomRoleDefinition, organization_id: UUID, project_id: UUID | None
) -> None:
    """Enforces `CustomRoleGrantTarget.project_id`'s own documented
    constraint against the actual role being granted: required if and only
    if `role.scope == "project"` (mirroring `UserCustomRoleGrant`/
    `GroupCustomRoleGrant`'s own model docstrings) — never left to the
    schema layer alone, since the schema has no access to the role's own
    `scope` to validate against."""
    if role.scope == "project":
        if project_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This role is project-scoped; project_id is required.")
        project = db.get(Project, project_id)
        if project is None or project.organization_id != organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "project_id must be a project in this organisation.")
    elif project_id is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This role is org-scoped; project_id must not be given.")


@router.get("/{organization_id}/permissions", response_model=list[PermissionOut])
def list_org_permissions(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(*_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    """Lists this organisation's full, currently-valid permission-atom
    vocabulary (`app.services.permissions.get_all_permissions`) — backs the
    Role Management UI's permission-atom picker (Phase 3) so the frontend
    never hardcodes the vocabulary itself, mirroring `GET /orgs/{id}/
    module-roles`'s identical "derived, not hand-maintained" role."""
    return [
        PermissionOut(key=p.key, label=p.label, artefact_type=p.artefact_type, level=p.level, subtype=p.subtype)
        for p in get_all_permissions(db, organization_id)
    ]


@router.get("/{organization_id}/custom-roles", response_model=list[CustomRoleDefinitionOut])
def list_custom_roles(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(*_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    """Lists this organisation's `CustomRoleDefinition`s, each with its full
    permission-atom set — `require_org_role` (any real org role), same
    reasoning as `list_org_permissions` above."""
    roles = db.scalars(
        select(CustomRoleDefinition)
        .where(CustomRoleDefinition.organization_id == organization_id)
        .order_by(CustomRoleDefinition.name)
    ).all()
    permissions_by_role = _permissions_by_role_id(db, [role.id for role in roles])
    return [_custom_role_definition_out(role, permissions_by_role.get(role.id, [])) for role in roles]


@router.get("/{organization_id}/custom-roles/{role_id}", response_model=CustomRoleDefinitionOut)
def get_custom_role(
    organization_id: UUID,
    role_id: UUID,
    current_user: User = Depends(require_org_role(*_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    role = _get_org_custom_role(db, organization_id, role_id)
    permissions = db.scalars(
        select(CustomRolePermission.permission).where(CustomRolePermission.custom_role_id == role.id)
    ).all()
    return _custom_role_definition_out(role, list(permissions))


@router.post(
    "/{organization_id}/custom-roles", response_model=CustomRoleDefinitionOut, status_code=status.HTTP_201_CREATED
)
def create_custom_role(
    organization_id: UUID,
    payload: CustomRoleDefinitionCreate,
    current_user: User = Depends(require_org_admin_or_server_admin),
    db: Session = Depends(get_db),
):
    """Defines a new organisation-scoped custom role (Phase 0 Q5:
    `ORG_ADMIN`/server-admin only, never delegable via `grant_roles` — no
    "manage custom roles" permission atom exists or should be invented).

    400s on an invalid `scope` or any permission key that isn't currently
    valid for this organisation (`validate_permission_key`); 409s on a
    duplicate `(organization_id, name)` — the DB's own unique constraint is
    a backstop, this returns a clean error rather than a raw
    `IntegrityError`. Audit-logged (`entity_type="custom_role_definition"`,
    action `"created"`); `created_by` is set to the creating admin.
    """
    _validate_scope(payload.scope)
    permissions = sorted(set(payload.permissions))
    _validate_permission_keys(db, organization_id, permissions)

    existing = db.scalar(
        select(CustomRoleDefinition).where(
            CustomRoleDefinition.organization_id == organization_id, CustomRoleDefinition.name == payload.name
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A custom role with this name already exists in this organisation."
        )

    role = CustomRoleDefinition(
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        scope=payload.scope,
        created_by=current_user.id,
    )
    db.add(role)
    db.flush()
    for permission in permissions:
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
    log_event(
        db,
        entity_type="custom_role_definition",
        entity_id=role.id,
        action="created",
        actor_id=current_user.id,
        organization_id=organization_id,
        detail={"name": role.name, "scope": role.scope, "permissions": permissions},
    )
    db.commit()
    return _custom_role_definition_out(role, permissions)


@router.patch("/{organization_id}/custom-roles/{role_id}", response_model=CustomRoleDefinitionOut)
def update_custom_role(
    organization_id: UUID,
    role_id: UUID,
    payload: CustomRoleDefinitionUpdate,
    current_user: User = Depends(require_org_admin_or_server_admin),
    db: Session = Depends(get_db),
):
    """Partial update of a custom role's name/description/scope/permission
    set — same `ORG_ADMIN`/server-admin-only gate and validation as
    `create_custom_role`. `permissions`, when given, replaces the role's
    entire permission set (see `CustomRoleDefinitionUpdate`'s docstring).
    Audit-logged with only the fields that actually changed."""
    role = _get_org_custom_role(db, organization_id, role_id)

    if payload.scope is not None:
        _validate_scope(payload.scope)
    new_permissions: list[str] | None = None
    if payload.permissions is not None:
        new_permissions = sorted(set(payload.permissions))
        _validate_permission_keys(db, organization_id, new_permissions)

    changes: dict[str, object] = {}

    if payload.name is not None and payload.name != role.name:
        existing = db.scalar(
            select(CustomRoleDefinition).where(
                CustomRoleDefinition.organization_id == organization_id,
                CustomRoleDefinition.name == payload.name,
                CustomRoleDefinition.id != role.id,
            )
        )
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A custom role with this name already exists in this organisation."
            )
        changes["name"] = payload.name
        role.name = payload.name

    if payload.description is not None and payload.description != role.description:
        changes["description"] = payload.description
        role.description = payload.description

    if payload.scope is not None and payload.scope != role.scope:
        changes["scope"] = payload.scope
        role.scope = payload.scope

    if new_permissions is not None:
        current_permissions = sorted(
            db.scalars(
                select(CustomRolePermission.permission).where(CustomRolePermission.custom_role_id == role.id)
            ).all()
        )
        if new_permissions != current_permissions:
            db.execute(CustomRolePermission.__table__.delete().where(CustomRolePermission.custom_role_id == role.id))
            for permission in new_permissions:
                db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
            changes["permissions"] = new_permissions

    if changes:
        log_event(
            db,
            entity_type="custom_role_definition",
            entity_id=role.id,
            action="updated",
            actor_id=current_user.id,
            organization_id=organization_id,
            detail=changes,
        )
    db.commit()

    permissions = new_permissions if new_permissions is not None else sorted(
        db.scalars(select(CustomRolePermission.permission).where(CustomRolePermission.custom_role_id == role.id)).all()
    )
    return _custom_role_definition_out(role, permissions)


@router.delete("/{organization_id}/custom-roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_role(
    organization_id: UUID,
    role_id: UUID,
    current_user: User = Depends(require_org_admin_or_server_admin),
    db: Session = Depends(get_db),
):
    """Deletes a custom role definition, `ORG_ADMIN`/server-admin only.
    Cascades to its `CustomRolePermission`/`UserCustomRoleGrant`/
    `GroupCustomRoleGrant` rows via their `ondelete="CASCADE"` foreign
    keys (`app.models.custom_role`) — no manual cleanup needed here."""
    role = _get_org_custom_role(db, organization_id, role_id)
    role_name = role.name
    db.delete(role)
    log_event(
        db,
        entity_type="custom_role_definition",
        entity_id=role_id,
        action="deleted",
        actor_id=current_user.id,
        organization_id=organization_id,
        detail={"name": role_name},
    )
    db.commit()


@router.post("/{organization_id}/custom-roles/{role_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def grant_custom_role_to_user(
    organization_id: UUID,
    role_id: UUID,
    user_id: UUID,
    payload: CustomRoleGrantTarget,
    current_user: User = Depends(require_org_admin_or_grant_roles),
    db: Session = Depends(get_db),
):
    """Grants a custom role to a user — `ORG_ADMIN` or a `grant_roles`
    holder (Phase 0 Q6: role *assignment*, unlike *definition* above, is
    delegable). The affected user is always the `{user_id}` path
    parameter, never a body field (see `CustomRoleGrantTarget`'s
    docstring). `payload.project_id` is required if and only if the role's
    own `scope == "project"`.

    Mirrors C-U-02 (`_require_user_in_org`): the target must already be a
    member of this organisation. No-op-safe on an already-held grant
    (`UserCustomRoleGrant`'s own unique constraint), matching
    `assign_org_module_role`'s check-then-insert shape. Audit-logged and
    notifies the grantee, mirroring `assign_project_module_role`'s
    `NotificationType.PERMISSION_GRANTED` call exactly.
    """
    role = _get_org_custom_role(db, organization_id, role_id)
    _validate_grant_project_id(db, role, organization_id, payload.project_id)
    _require_user_in_org(db, user_id, organization_id)

    target = db.get(User, user_id)
    if target is not None and target.is_banned:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This user has been banned by a server admin and cannot be granted a role."
        )

    existing = db.scalar(
        select(UserCustomRoleGrant).where(
            UserCustomRoleGrant.user_id == user_id,
            UserCustomRoleGrant.custom_role_id == role.id,
            UserCustomRoleGrant.project_id == payload.project_id,
        )
    )
    if existing is None:
        db.add(
            UserCustomRoleGrant(
                user_id=user_id,
                custom_role_id=role.id,
                organization_id=organization_id,
                project_id=payload.project_id,
                granted_by=current_user.id,
            )
        )
        log_event(
            db,
            entity_type="user_custom_role_grant",
            entity_id=user_id,
            action="granted",
            actor_id=current_user.id,
            organization_id=organization_id,
            project_id=payload.project_id,
            detail={"custom_role_id": str(role.id), "custom_role_name": role.name},
        )
        if target is not None:
            notify(
                db,
                target,
                notification_type=NotificationType.PERMISSION_GRANTED,
                title="Organisation permission granted",
                body=f"You were granted the '{role.name}' role.",
                project_id=payload.project_id,
                actor_id=current_user.id,
            )
        db.commit()


@router.delete("/{organization_id}/custom-roles/{role_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_custom_role_from_user(
    organization_id: UUID,
    role_id: UUID,
    user_id: UUID,
    project_id: UUID | None = Query(
        None,
        description="Required iff the role's scope is 'project' — a project-scoped role may be granted to the "
        "same user across more than one project, so the specific grant to revoke must be named explicitly.",
    ),
    current_user: User = Depends(require_org_admin_or_grant_roles),
    db: Session = Depends(get_db),
):
    """Revokes a custom role grant from a user — `grant_custom_role_to_user`'s
    counterpart, same gate. A query parameter (not a body) carries
    `project_id` here, matching this codebase's existing DELETE-endpoint
    convention (e.g. `revoke_project_role`) of taking no request body.
    No-op if the grant doesn't currently exist."""
    role = _get_org_custom_role(db, organization_id, role_id)
    _validate_grant_project_id(db, role, organization_id, project_id)

    existing = db.scalar(
        select(UserCustomRoleGrant).where(
            UserCustomRoleGrant.user_id == user_id,
            UserCustomRoleGrant.custom_role_id == role.id,
            UserCustomRoleGrant.project_id == project_id,
        )
    )
    if existing is not None:
        db.delete(existing)
        log_event(
            db,
            entity_type="user_custom_role_grant",
            entity_id=user_id,
            action="revoked",
            actor_id=current_user.id,
            organization_id=organization_id,
            project_id=project_id,
            detail={"custom_role_id": str(role.id), "custom_role_name": role.name},
        )
        db.commit()


@router.post("/{organization_id}/custom-roles/{role_id}/groups/{org_group_id}", status_code=status.HTTP_204_NO_CONTENT)
def grant_custom_role_to_group(
    organization_id: UUID,
    role_id: UUID,
    org_group_id: UUID,
    payload: CustomRoleGrantTarget,
    current_user: User = Depends(require_org_admin_or_grant_roles),
    db: Session = Depends(get_db),
):
    """Grants a custom role to every (transitive) member of an
    organisation group — the group-level counterpart to
    `grant_custom_role_to_user`, same gate/validation shape. `org_group_id`
    must belong to this organisation. No per-member notification is sent,
    mirroring `assign_group_project_role`'s own precedent (a group grant
    potentially affects many users at once)."""
    role = _get_org_custom_role(db, organization_id, role_id)
    _validate_grant_project_id(db, role, organization_id, payload.project_id)

    org_group = db.get(OrgGroup, org_group_id)
    if org_group is None or org_group.organization_id != organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to this organisation.")

    existing = db.scalar(
        select(GroupCustomRoleGrant).where(
            GroupCustomRoleGrant.org_group_id == org_group_id,
            GroupCustomRoleGrant.custom_role_id == role.id,
            GroupCustomRoleGrant.project_id == payload.project_id,
        )
    )
    if existing is None:
        db.add(
            GroupCustomRoleGrant(
                org_group_id=org_group_id,
                custom_role_id=role.id,
                organization_id=organization_id,
                project_id=payload.project_id,
                granted_by=current_user.id,
            )
        )
        log_event(
            db,
            entity_type="group_custom_role_grant",
            entity_id=org_group_id,
            action="granted",
            actor_id=current_user.id,
            organization_id=organization_id,
            project_id=payload.project_id,
            detail={"custom_role_id": str(role.id), "custom_role_name": role.name},
        )
        db.commit()


@router.delete(
    "/{organization_id}/custom-roles/{role_id}/groups/{org_group_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_custom_role_from_group(
    organization_id: UUID,
    role_id: UUID,
    org_group_id: UUID,
    project_id: UUID | None = Query(None, description="Required iff the role's scope is 'project' — see the user revoke endpoint's docstring."),
    current_user: User = Depends(require_org_admin_or_grant_roles),
    db: Session = Depends(get_db),
):
    """Revokes a custom role grant from an organisation group —
    `grant_custom_role_to_group`'s counterpart, same gate. No-op if absent."""
    role = _get_org_custom_role(db, organization_id, role_id)
    _validate_grant_project_id(db, role, organization_id, project_id)

    existing = db.scalar(
        select(GroupCustomRoleGrant).where(
            GroupCustomRoleGrant.org_group_id == org_group_id,
            GroupCustomRoleGrant.custom_role_id == role.id,
            GroupCustomRoleGrant.project_id == project_id,
        )
    )
    if existing is not None:
        db.delete(existing)
        log_event(
            db,
            entity_type="group_custom_role_grant",
            entity_id=org_group_id,
            action="revoked",
            actor_id=current_user.id,
            organization_id=organization_id,
            project_id=project_id,
            detail={"custom_role_id": str(role.id), "custom_role_name": role.name},
        )
        db.commit()
