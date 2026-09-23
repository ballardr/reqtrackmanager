"""
Module: routers.projects.module_roles

Module-contributed roles at the project scope (module system Phase 2/3):
which module roles/nav entries are currently available on this project,
minting a `<ModuleFrame>` frame token, and granting/revoking a
module-contributed role for a member.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.module_role import UserModuleRole
from app.models.notification import NotificationType
from app.models.project import Project
from app.models.user import User
from app.modules.registry import get_frontend_manifest, get_module_registry, is_module_enabled, list_enabled_module_roles
from app.schemas.org import ModuleFrameTokenOut, ModuleFrontendManifestOut, ModuleNavEntryOut, ModuleRoleAssign, ModuleRoleDefinitionOut
from app.security import create_module_frame_token
from app.services.audit import log_event
from app.services.notifications import notify
from app.services.rbac import (
    require_project_manage_or_grant_roles,
    require_project_module_enabled_dynamic,
    require_project_view_or_manage,
)

router = APIRouter(tags=["projects-module-roles"])


@router.get("/{project_id}/module-roles", response_model=list[ModuleRoleDefinitionOut])
def list_project_module_roles(
    project_id: UUID,
    current_user: User = Depends(require_project_view_or_manage),
    db: Session = Depends(get_db),
):
    """Lists the project-scoped module-contributed roles currently
    available to grant on this project — i.e. declared by a module that is
    currently effectively enabled for the project's owning organisation
    (module system Phase 2).

    Gated by `require_project_view_or_manage`, the same dependency
    `list_project_groups` uses: this exposes role/group *structure*
    (which role options exist) rather than requirement/change-request
    *content*, so either a genuine project role or org-admin-level
    project-settings-management capability is enough — matching that
    dependency's own documented purpose.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return [
        ModuleRoleDefinitionOut(module_key=module_key, role_key=role.role_key, name=role.name, description=role.description)
        for module_key, role in list_enabled_module_roles(db, project.organization_id, "project")
    ]


@router.get("/{project_id}/enabled-modules", response_model=list[ModuleNavEntryOut])
def list_project_enabled_modules(
    project_id: UUID,
    current_user: User = Depends(require_project_view_or_manage),
    db: Session = Depends(get_db),
):
    """Lists every module currently *effectively enabled* for this
    project's owning organisation, with enough of its frontend manifest for
    the frontend to render a nav entry and route for it (module system
    Phase 3).

    Deliberately lean and enabled-only, unlike `GET /orgs/{id}/modules`
    (`OrgModuleOut`) which is an org-admin bookkeeping view that
    deliberately includes non-entitled/disabled modules greyed out — this
    is the read any project member uses purely to render nav/routing, so a
    disabled/non-entitled module is simply absent rather than represented
    in some disabled state a plain nav rail has no use for. Gated by
    `require_project_view_or_manage`, the same dependency `list_project_
    module_roles`/`list_project_groups` use, for the same "structure, not
    content" reasoning.

    `ModuleFrontendManifest.nav_path`/`.frame_url` may contain a literal
    `"{project_id}"` placeholder (its own docstring gives exactly this as
    an example, e.g. `"/projects/{project_id}/modules/compliance"`) — this
    is the one endpoint that actually knows a concrete `project_id`, so it
    interpolates the placeholder into every manifest field before returning
    it (Phase 13, `docs/compliance-module-plan.md`: Compliance is the first
    module to populate this placeholder for real). `GET /orgs/{id}/modules`
    (`OrgModuleOut`, `routers/orgs.py`) has no single project in scope and
    deliberately leaves the placeholder un-interpolated for its own
    admin-bookkeeping display. `ModuleFrontendManifest.remote_entry_url`/
    `.exposed_module` (Tier C, module system follow-up) are carried through
    unchanged — neither is expected to ever contain the placeholder, since
    `remote_entry_url` points at a static build artifact, not a per-project
    route.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    result: list[ModuleNavEntryOut] = []
    for definition in get_module_registry().values():
        if not is_module_enabled(db, project.organization_id, definition.key):
            continue
        manifest = get_frontend_manifest(definition.key)
        # A module may hide its own already-enabled nav entry for this
        # specific project (`ModuleDefinition.project_nav_visible`'s own
        # docstring) — e.g. Compliance hides its entry until the owning
        # organisation has a standard actually assignable. This core,
        # module-agnostic endpoint never imports a specific module to make
        # that call itself.
        if manifest is not None and definition.project_nav_visible is not None and not definition.project_nav_visible(db, project):
            manifest = None
        frontend_manifest_out = None
        if manifest is not None:
            frontend_manifest_out = ModuleFrontendManifestOut(
                tier=manifest.tier,
                nav_label=manifest.nav_label,
                nav_path=manifest.nav_path.replace("{project_id}", str(project_id)),
                frame_url=manifest.frame_url.replace("{project_id}", str(project_id)) if manifest.frame_url else None,
                # Tier C fields carried through unchanged: remote_entry_url
                # points at a static build artifact (a JS file), never a
                # per-project route, so the "{project_id}" placeholder
                # interpolation above has nothing to substitute in either of
                # these — unlike nav_path/frame_url, neither is expected to
                # ever contain that placeholder.
                remote_entry_url=manifest.remote_entry_url,
                exposed_module=manifest.exposed_module,
            )
        result.append(
            ModuleNavEntryOut(module_key=definition.key, name=definition.name, frontend_manifest=frontend_manifest_out)
        )
    return result


@router.post("/{project_id}/modules/{module_key}/frame-token", response_model=ModuleFrameTokenOut)
def create_project_module_frame_token(
    project_id: UUID,
    module_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_project_module_enabled_dynamic),
) -> ModuleFrameTokenOut:
    """Project-scoped sibling of `orgs.create_org_module_frame_token`
    (module system Phase 3) — mints a token scoped to `(module_key,
    project_id, current_user)` for a Tier B `<ModuleFrame>` mounted on a
    project-scoped page. See that endpoint's and `app.security.create_
    module_frame_token`'s docstrings for the full scoping rationale.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    token = create_module_frame_token(
        module_key=module_key, organization_id=str(project.organization_id),
        user_id=str(current_user.id), project_id=str(project_id),
    )
    return ModuleFrameTokenOut(token=token, expires_in_minutes=15)


@router.post("/{project_id}/members/{user_id}/module-roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_project_module_role(
    project_id: UUID,
    user_id: UUID,
    payload: ModuleRoleAssign,
    project: Project = Depends(require_project_manage_or_grant_roles),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grants a project-scoped module-contributed role to a user (module
    system Phase 2) — the module-role counterpart to `routers.projects.
    roles.assign_project_role`, same gate (a project manager already
    implicitly holds every project-scoped module role via `require_module_
    role`'s own override, so it's consistent that a project manager is
    also who explicitly grants/revokes the row) plus a `grant_roles`
    holder (Fine-Grained Access Control Phase 0 Q6/Phase 3).

    400s if `(payload.module_key, payload.role_key)` doesn't name a real
    `scope="project"` role of a currently-enabled module for this
    project's organisation — same "ungrantable when disabled, catches a
    typo" reasoning as `assign_org_module_role`.
    """
    valid = any(
        module_key == payload.module_key and role.role_key == payload.role_key
        for module_key, role in list_enabled_module_roles(db, project.organization_id, "project")
    )
    if not valid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This module role does not exist, is not project-scoped, or its module is not currently enabled for this project's organisation.",
        )
    existing = db.scalar(
        select(UserModuleRole).where(
            UserModuleRole.user_id == user_id,
            UserModuleRole.module_key == payload.module_key,
            UserModuleRole.role_key == payload.role_key,
            UserModuleRole.project_id == project.id,
        )
    )
    if existing is None:
        db.add(
            UserModuleRole(
                user_id=user_id, module_key=payload.module_key, role_key=payload.role_key,
                organization_id=project.organization_id, project_id=project.id, granted_by=current_user.id,
            )
        )
        log_event(
            db, entity_type="user_module_role", entity_id=user_id, action="granted",
            actor_id=current_user.id, project_id=project.id,
            detail={"module_key": payload.module_key, "role_key": payload.role_key},
        )
        granted_user = db.get(User, user_id)
        if granted_user is not None:
            notify(
                db, granted_user, notification_type=NotificationType.PERMISSION_GRANTED,
                title=f"You were granted a permission on {project.name}",
                body=f"You were granted the '{payload.role_key}' role.",
                project_id=project.id, actor_id=current_user.id,
            )
        db.commit()


@router.delete(
    "/{project_id}/members/{user_id}/module-roles/{module_key}/{role_key}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_project_module_role(
    project_id: UUID,
    user_id: UUID,
    module_key: str,
    role_key: str,
    project: Project = Depends(require_project_manage_or_grant_roles),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revokes a project-scoped module-contributed role grant —
    `assign_project_module_role`'s counterpart, same gate, mirroring
    `routers.projects.roles.revoke_project_role`'s shape minus its "last manager"
    guard, which is meaningless for module roles (they carry no admin-tier
    significance of their own — a `PROJECT_MANAGER` retains full access to
    every project-scoped module role regardless of this table's contents,
    see `require_module_role`). No-op if the user doesn't currently hold
    the grant."""
    existing = db.scalar(
        select(UserModuleRole).where(
            UserModuleRole.user_id == user_id,
            UserModuleRole.module_key == module_key,
            UserModuleRole.role_key == role_key,
            UserModuleRole.project_id == project.id,
        )
    )
    if existing is not None:
        db.delete(existing)
        log_event(
            db, entity_type="user_module_role", entity_id=user_id, action="revoked",
            actor_id=current_user.id, project_id=project.id,
            detail={"module_key": module_key, "role_key": role_key},
        )
        db.commit()
