"""
Module: routers.projects.module_roles

Module-contributed roles at the project scope: which module roles and nav entries are available on this
project, minting a `<ModuleFrame>` frame token, and granting/revoking a module-contributed role for a member.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, refuse_personal_access_token
from app.models.module import (
    ProjectModuleEnablement,
    ProjectModuleSubComponentEnablement,
)
from app.models.module_role import UserModuleRole
from app.models.notification import NotificationType
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    get_frontend_manifest,
    get_module_registry,
    is_module_enabled,
    is_module_enabled_for_project,
    is_module_subcomponent_enabled,
    list_enabled_module_roles,
    resolve_default_project_enabled,
    resolve_org_subcomponent_state,
    unmet_subcomponent_requirements,
)
from app.schemas.org import (
    ManifestNavEntryOut,
    ModuleFrameTokenOut,
    ModuleFrontendManifestOut,
    ModuleNavEntryOut,
    ModuleRoleAssign,
    ModuleRoleDefinitionOut,
    ProjectModuleEnablementOut,
    ProjectModuleEnablementUpdate,
    ProjectModuleSubComponentEnablementUpdate,
    ProjectModuleSubComponentOut,
)
from app.security import create_module_frame_token
from app.services.audit import log_event
from app.services.notifications import notify
from app.services.rbac import (
    require_project_manage,
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
    """Lists the project-scoped module-contributed roles available to grant on this project, i.e. declared by a
    module that is effectively enabled for the project's organisation.

    Gated by `require_project_view_or_manage`, as `list_project_groups`: this exposes role/group structure
    rather than requirement/change-request content, so a project role or org-admin project-settings
    capability suffices.
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
    """Lists every module effectively enabled for this project's organisation, with enough of its frontend
    manifest for the frontend to render a nav entry and route.

    Lean and enabled-only, unlike `GET /orgs/{id}/modules` (`OrgModuleOut`), the org-admin view that includes
    non-entitled and disabled modules: any project member uses this read to render nav, so a disabled or
    non-entitled module is absent. Gated by `require_project_view_or_manage`, as `list_project_module_roles`
    and `list_project_groups` ("structure, not content").

    `ModuleFrontendManifest.nav_path`/`.frame_url` may contain a literal `"{project_id}"` placeholder (e.g.
    `"/projects/{project_id}/modules/compliance"`); this is the one endpoint that knows a concrete
    `project_id`, so it interpolates the placeholder into every manifest field. `GET /orgs/{id}/modules`
    has no single project in scope and leaves it un-interpolated. `ModuleFrontendManifest.remote_entry_url`/
    `.exposed_module` (Tier C) are carried through unchanged: `remote_entry_url` points at a static build
    artefact, not a per-project route.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    result: list[ModuleNavEntryOut] = []
    for definition in get_module_registry().values():
        # `is_module_enabled_for_project`, not the org-only `is_module_enabled`: a project's effective state
        # can diverge from its organisation's default in either direction, and the org-only check would
        # show a nav entry for a module this project disabled (clicking it would 404) or hide one this
        # project enabled over an org default that is off.
        if not is_module_enabled_for_project(db, project_id, definition.key):
            continue
        manifest = get_frontend_manifest(definition.key)
        # A module may hide its own enabled nav entry for this project (`ModuleDefinition.project_nav_visible`),
        # e.g. Compliance hides it until the organisation has an assignable standard; this module-agnostic
        # endpoint never imports a module to decide that.
        if manifest is not None and definition.project_nav_visible is not None and not definition.project_nav_visible(db, project):
            manifest = None
        frontend_manifest_out = None
        if manifest is not None:
            frontend_manifest_out = ModuleFrontendManifestOut(
                tier=manifest.tier,
                nav_label=manifest.nav_label,
                nav_path=manifest.nav_path.replace("{project_id}", str(project_id)),
                frame_url=manifest.frame_url.replace("{project_id}", str(project_id)) if manifest.frame_url else None,
                # Tier C fields are carried through unchanged: `remote_entry_url` points at a static build
                # artefact (a JS file), never a per-project route, so the "{project_id}" interpolation above
                # has nothing to substitute in either field.
                remote_entry_url=manifest.remote_entry_url,
                exposed_module=manifest.exposed_module,
                # additional_nav_entries (Context & Strategy): the same "{project_id}" interpolation as
                # nav_path, as every one of a Tier A module's nav entries follows its primary one's convention.
                additional_nav_entries=[
                    ManifestNavEntryOut(
                        nav_label=entry.nav_label,
                        nav_path=entry.nav_path.replace("{project_id}", str(project_id)),
                        nav_icon=entry.nav_icon,
                        sub_component=entry.sub_component,
                        sub_components_any=list(entry.sub_components_any),
                    )
                    for entry in manifest.additional_nav_entries
                ],
                nav_icon=manifest.nav_icon,
                nav_sub_component=manifest.nav_sub_component,
                nav_sub_components_any=list(manifest.nav_sub_components_any),
            )
        disabled_sub_components = [
            sub.key for sub in definition.sub_components
            if not is_module_subcomponent_enabled(db, project_id, definition.key, sub.key)
        ]
        result.append(
            ModuleNavEntryOut(
                module_key=definition.key, name=definition.name, frontend_manifest=frontend_manifest_out,
                disabled_sub_components=disabled_sub_components,
            )
        )
    return result


@router.get("/{project_id}/modules", response_model=list[ProjectModuleEnablementOut])
def list_project_modules(
    project_id: UUID,
    current_user: User = Depends(require_project_view_or_manage),
    db: Session = Depends(get_db),
):
    """Lists every registered module with this project's effective whole-module enablement state, one tier
    below `routers.orgs.settings.list_org_modules` but reachable by a plain project manager who is not an org
    admin (`GET /orgs/{id}/modules` is org-admin-gated, and `GET /projects/{id}/modules/{module_key}/enablement`
    needs every `module_key` up front).

    Gated by `require_project_view_or_manage`, the "structure, not content" dependency of the other read
    endpoints in this file.

    Modules the organisation has disabled, or has no entitlement for, are omitted: a project admin cannot use
    them and is not offered them. A project's own override row for an omitted module is kept, so it reappears
    with its state if the organisation re-enables the module.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    project_rows = {
        row.module_key: row
        for row in db.scalars(
            select(ProjectModuleEnablement).where(ProjectModuleEnablement.project_id == project_id)
        )
    }
    return [
        ProjectModuleEnablementOut(
            module_key=definition.key, name=definition.name,
            effective_enabled=is_module_enabled_for_project(db, project_id, definition.key),
            org_default_enabled=resolve_default_project_enabled(db, project.organization_id, definition.key),
            org_hard_enabled=is_module_enabled(db, project.organization_id, definition.key),
            has_project_override=definition.key in project_rows,
            project_override_enabled=(
                project_rows[definition.key].enabled if definition.key in project_rows else None
            ),
        )
        for definition in get_module_registry().values()
        if is_module_enabled(db, project.organization_id, definition.key)
    ]


@router.post("/{project_id}/modules/{module_key}/frame-token", response_model=ModuleFrameTokenOut)
def create_project_module_frame_token(
    project_id: UUID,
    module_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_project_module_enabled_dynamic),
) -> ModuleFrameTokenOut:
    """Project-scoped sibling of `orgs.create_org_module_frame_token`
 — mints a token scoped to `(module_key,
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


@router.get("/{project_id}/modules/{module_key}/enablement", response_model=ProjectModuleEnablementOut)
def get_project_module_enablement(
    project_id: UUID,
    module_key: str,
    current_user: User = Depends(require_project_view_or_manage),
    db: Session = Depends(get_db),
):
    """Returns this project's effective whole-module enablement state for `module_key`: the effective state,
    the organisation's default, and whether this project has an explicit override, all three so the frontend
    can render "using org default: X" vs "overridden to: Y" distinctly (as the sub-component endpoints). Gated
    by `require_project_view_or_manage` ("structure, not content").

    The path ends in `/enablement`, not the bare `.../modules/{module_key}`: this router is included before
    any module's own `get_project_router()` (`main.py`'s mount order), so a bare `GET/PUT .../modules/{module_key}`
    would shadow a module whose project router declares a bare `GET/PUT ""` at its base path (as Decision
    Management's list/create Decisions does). The extra segment, as `/subcomponents`, makes a collision with a
    module's bare-base route impossible.

    404s if the project doesn't exist or `module_key` isn't registered.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    definition = get_module_registry().get(module_key)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found.")

    # `effective_enabled`/`org_default_enabled` come from the real resolution functions, not the raw rows
    # below, so this read matches what `require_project_module_enabled` enforces (entitlement is a ceiling both
    # `is_module_enabled_for_project` and `is_module_enabled` apply; a stale override row would misreport
    # "enabled" for a de-entitled module).
    project_row = db.scalar(
        select(ProjectModuleEnablement).where(
            ProjectModuleEnablement.project_id == project_id,
            ProjectModuleEnablement.module_key == module_key,
        )
    )
    return ProjectModuleEnablementOut(
        module_key=module_key, name=definition.name,
        effective_enabled=is_module_enabled_for_project(db, project_id, module_key),
        org_default_enabled=resolve_default_project_enabled(db, project.organization_id, module_key),
        org_hard_enabled=is_module_enabled(db, project.organization_id, module_key),
        has_project_override=project_row is not None,
        project_override_enabled=project_row.enabled if project_row is not None else None,
    )


@router.put("/{project_id}/modules/{module_key}/enablement", response_model=ProjectModuleEnablementOut)
def update_project_module_enablement(
    project_id: UUID,
    module_key: str,
    payload: ProjectModuleEnablementUpdate,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets this project's own explicit override of whole-module enablement for `module_key`, symmetric
    against the organisation's `default_project_enabled`: a project admin's choice wins over that default in
    either direction (on for a module the organisation defaults off for new projects, or off for one it
    defaults on), but only within the organisation's `enabled=True` floor.

    Gated by `require_project_manage`, as the project-tier sub-component endpoints in this file.

    Entitlement and the organisation's hard `enabled` flag are an absolute floor this override cannot cross
    upward, enforced at write time: `enabled=True` is rejected (400) if `is_module_enabled(db,
    project.organization_id, module_key)` is `False` (the organisation is not entitled, or has hard-disabled
    it). `enabled=False` (narrowing) is always allowed. A module the organisation merely defaults off for new
    projects (`default_project_enabled=False`, still hard-`enabled=True`) is not rejected: a project may opt in.

    404s if `module_key` isn't registered.
    """
    definition = get_module_registry().get(module_key)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found.")
    if payload.enabled and not is_module_enabled(db, project.organization_id, module_key):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This module is disabled for your organisation — ask an organisation admin to enable it before "
            "setting a project override.",
        )

    row = db.scalar(
        select(ProjectModuleEnablement).where(
            ProjectModuleEnablement.project_id == project_id,
            ProjectModuleEnablement.module_key == module_key,
        )
    )
    if row is None:
        row = ProjectModuleEnablement(project_id=project_id, module_key=module_key)
        db.add(row)
    row.enabled = payload.enabled
    row.updated_by = current_user.id
    log_event(
        # `entity_id=module_key` alone, without `project_id` (its own `AuditEvent` column): see the
        # sub-component endpoint below; `AuditEvent.entity_id` is `String(64)` and a UUID plus colon-joined
        # keys can overflow it.
        db, entity_type="project_module", entity_id=module_key,
        action="module.enablement_updated", actor_id=current_user.id, project_id=project_id,
        detail={"module_key": module_key, "enabled": payload.enabled},
    )
    db.commit()
    db.refresh(row)

    return ProjectModuleEnablementOut(
        module_key=module_key, name=definition.name,
        effective_enabled=is_module_enabled_for_project(db, project_id, module_key),
        org_default_enabled=resolve_default_project_enabled(db, project.organization_id, module_key),
        org_hard_enabled=is_module_enabled(db, project.organization_id, module_key),
        has_project_override=True, project_override_enabled=row.enabled,
    )


def _project_subcomponent_out(
    db: Session, project: Project, module_key: str, sub, project_row: ProjectModuleSubComponentEnablement | None,
) -> ProjectModuleSubComponentOut:
    """Builds one `ProjectModuleSubComponentOut`. `effective_enabled` comes
    from `is_module_subcomponent_enabled` itself so this read can't drift
    from what `require_project_subcomponent_enabled` enforces.

    Args:
        db: An active database session.
        project: The project being viewed.
        module_key: The declaring module's registry key.
        sub: The `ModuleSubComponentDefinition`.
        project_row: This project's own row for `sub`, if any.

    Returns:
        The response model.
    """
    org_enabled, org_default_project_enabled = resolve_org_subcomponent_state(
        db, project.organization_id, module_key, sub.key,
    ) or (False, False)
    return ProjectModuleSubComponentOut(
        module_key=module_key, subcomponent_key=sub.key, name=sub.name,
        effective_enabled=is_module_subcomponent_enabled(db, project.id, module_key, sub.key),
        org_default_enabled=org_default_project_enabled,
        org_hard_enabled=org_enabled and is_module_enabled(db, project.organization_id, module_key),
        has_project_override=project_row is not None,
        project_override_enabled=project_row.enabled if project_row is not None else None,
        blocked_by=[needed.name for needed in unmet_subcomponent_requirements(db, project.id, module_key, sub.key)],
    )


@router.get("/{project_id}/modules/{module_key}/subcomponents", response_model=list[ProjectModuleSubComponentOut])
def list_project_module_subcomponents(
    project_id: UUID,
    module_key: str,
    current_user: User = Depends(require_project_view_or_manage),
    db: Session = Depends(get_db),
):
    """Lists every sub-component `module_key` declares from this project's point of view: its effective
    state, its organisation's default, and whether this project has an explicit override, all three so the
    frontend can render the style guide's "platform-default override visibility" pattern ("using org default:
    X" vs "overridden to: Y"). Gated by `require_project_view_or_manage` ("structure, not content").

    404s if the project doesn't exist or `module_key` isn't registered. A module with no declared
    `sub_components` returns an empty list. Sub-components the organisation has switched off are omitted, as
    are all of them when the organisation has the module itself off.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    definition = get_module_registry().get(module_key)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found.")

    project_rows = {
        row.subcomponent_key: row
        for row in db.scalars(
            select(ProjectModuleSubComponentEnablement).where(
                ProjectModuleSubComponentEnablement.project_id == project_id,
                ProjectModuleSubComponentEnablement.module_key == module_key,
            )
        )
    }
    return [
        out for sub in definition.sub_components
        if not sub.organization_only
        if (out := _project_subcomponent_out(db, project, module_key, sub, project_rows.get(sub.key))).org_hard_enabled
    ]


@router.put(
    "/{project_id}/modules/{module_key}/subcomponents/{subcomponent_key}", response_model=ProjectModuleSubComponentOut,
)
def update_project_module_subcomponent_enablement(
    project_id: UUID,
    module_key: str,
    subcomponent_key: str,
    payload: ProjectModuleSubComponentEnablementUpdate,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets this project's own explicit override for one sub-component of `module_key`: a project admin's
    choice for this project only, taking precedence over the organisation's default
    (`routers.orgs.settings.update_org_module_subcomponent_default`).

    Gated by `require_project_manage` (project managers and the organisation's admins), the capability the
    other project-settings endpoints use.

    404s if `module_key`/`subcomponent_key` isn't registered.
    """
    definition = get_module_registry().get(module_key)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found.")
    subcomponent = next((s for s in definition.sub_components if s.key == subcomponent_key), None)
    if subcomponent is None or subcomponent.organization_only:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sub-component not found.")
    org_state = resolve_org_subcomponent_state(db, project.organization_id, module_key, subcomponent_key)
    if payload.enabled and not (is_module_enabled(db, project.organization_id, module_key) and org_state and org_state[0]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This sub-component is turned off for your organisation — ask an organisation admin to enable it first.",
        )

    row = db.scalar(
        select(ProjectModuleSubComponentEnablement).where(
            ProjectModuleSubComponentEnablement.project_id == project_id,
            ProjectModuleSubComponentEnablement.module_key == module_key,
            ProjectModuleSubComponentEnablement.subcomponent_key == subcomponent_key,
        )
    )
    if row is None:
        row = ProjectModuleSubComponentEnablement(
            project_id=project_id, module_key=module_key, subcomponent_key=subcomponent_key,
        )
        db.add(row)
    row.enabled = payload.enabled
    row.updated_by = current_user.id
    log_event(
        db, entity_type="project_module_subcomponent",
        # `f"{module_key}:{subcomponent_key}"`, without `project_id`: `AuditEvent.entity_id` is `String(64)`
        # and a UUID (36 chars) plus two colon-joined keys can overflow it.
        entity_id=f"{module_key}:{subcomponent_key}",
        action="module.subcomponent_enablement_updated", actor_id=current_user.id, project_id=project_id,
        detail={"module_key": module_key, "subcomponent_key": subcomponent_key, "enabled": payload.enabled},
    )
    db.commit()
    db.refresh(row)

    return _project_subcomponent_out(db, project, module_key, subcomponent, row)


@router.post(
    "/{project_id}/members/{user_id}/module-roles", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(refuse_personal_access_token)],
)
def assign_project_module_role(
    project_id: UUID,
    user_id: UUID,
    payload: ModuleRoleAssign,
    project: Project = Depends(require_project_manage_or_grant_roles),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grants a project-scoped module-contributed role to a user: the module-role counterpart to
    `routers.projects.roles.assign_project_role`, same gate (a project manager already implicitly holds every
    project-scoped module role via `require_module_role`) plus a `grant_roles` holder.

    400 if `(payload.module_key, payload.role_key)` is not a `scope="project"` role of a currently enabled
    module for this project's organisation (disabled modules' roles are ungrantable and a mistyped key is
    caught, as `assign_org_module_role`).
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
, dependencies=[Depends(refuse_personal_access_token)])
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
