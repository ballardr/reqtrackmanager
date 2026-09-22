"""
Module: routers.system.modules

Module system Phase 0/1/4 administration: the deployment-wide default
module entitlement policy, the module registry listing, per-organisation
module entitlement overrides, and the module-contributed MCP tool
manifest. The entitlement-policy and registry/entitlement endpoints accept
either `SERVER_ADMIN` or the narrower `MODULE_ADMINISTRATOR` server role —
the one place this router's gating isn't uniformly `require_server_admin`.

Split out of the former flat `routers/system.py` as a pure code-organization
refactor — see `routers/system/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import ModuleEntitlementPolicy, ServerRole
from app.models.module import OrganizationModuleEntitlement
from app.models.organization import Organization
from app.models.user import User
from app.modules.registry import build_mcp_tool_manifest, get_module_registry, is_module_entitled
from app.services.audit import log_event
from app.services.branding import get_server_settings
from app.services.rbac import require_server_role

router = APIRouter(tags=["system-modules"])


class ModuleEntitlementPolicyOut(BaseModel):
    model_config = {"from_attributes": True}

    default_module_entitlement_policy: ModuleEntitlementPolicy


class ModuleEntitlementPolicyUpdate(BaseModel):
    default_module_entitlement_policy: ModuleEntitlementPolicy


class ModuleOut(BaseModel):
    """A registered module's static description (module system Phase 1) —
    "what modules exist," with no per-organisation data. See
    `OrgModuleEntitlementOut` for the per-organisation entitlement view."""

    module_key: str
    name: str
    description: str
    version: str
    default_enabled: bool
    implemented: bool


class OrgModuleEntitlementOut(BaseModel):
    """One module's entitlement state for a specific organisation, as seen
    by a `MODULE_ADMINISTRATOR`/`SERVER_ADMIN` (module system Phase 1).

    Attributes:
        module_key: The module's registry key.
        name: The module's display name.
        entitled: The *effective* entitlement (an explicit override row's
            value, or the deployment's default policy if none exists).
        has_override: Whether an explicit `OrganizationModuleEntitlement`
            row exists for this organisation/module pair.
        default_policy_used: The inverse of `has_override` — `True` when
            `entitled` was derived from `ServerSettings.
            default_module_entitlement_policy` rather than an explicit row.
    """

    module_key: str
    name: str
    entitled: bool
    has_override: bool
    default_policy_used: bool


class OrgModuleEntitlementUpdate(BaseModel):
    """Sets an explicit server-tier entitlement override for one
    organisation/module pair (module system Phase 1)."""

    entitled: bool


class ModuleMcpToolOut(BaseModel):
    """One module-contributed `mcp-server/` tool (module system Phase 4) —
    the wire shape of `app.modules.registry.ResolvedMcpTool`. Every field
    here has already been through `build_mcp_tool_manifest`'s mechanical
    verification; see that function's docstring for what that means.
    `params` is passed through as plain dicts (`{"name", "type", "required",
    "in", "description"}` per entry) rather than a nested model — the same
    loosely-typed, declaration-shaped design `McpToolDefinition.params`
    itself uses, since these values are display/JSON-Schema hints for the
    calling AI assistant, not something this endpoint needs to validate
    further."""

    name: str
    description: str
    method: str
    path_template: str
    mutates: bool
    params: list[dict[str, Any]]


# --- Module entitlement policy (module system Phase 0/1) --------------------


@router.get("/module-entitlement-policy", response_model=ModuleEntitlementPolicyOut)
def get_module_entitlement_policy(
    current_user: User = Depends(require_server_role(ServerRole.MODULE_ADMINISTRATOR)),
    db: Session = Depends(get_db),
):
    """Returns the deployment-wide default module entitlement policy
    (`ServerSettings.default_module_entitlement_policy`) — the value
    Phase 1's entitlement resolution falls back to when an organisation has
    no explicit `organization_module_entitlements` override row.

    Gated the same as the PUT below (`SERVER_ADMIN` or
    `MODULE_ADMINISTRATOR`), unlike `/branding`'s unauthenticated GET: this
    has no unauthenticated consumer, so it stays behind the same admin gate
    as any other module-management setting.
    """
    return get_server_settings(db)


@router.put("/module-entitlement-policy", response_model=ModuleEntitlementPolicyOut)
def update_module_entitlement_policy(
    payload: ModuleEntitlementPolicyUpdate,
    current_user: User = Depends(require_server_role(ServerRole.MODULE_ADMINISTRATOR)),
    db: Session = Depends(get_db),
):
    """Sets the deployment-wide default module entitlement policy.
    `SERVER_ADMIN` or `MODULE_ADMINISTRATOR` may call this — the one
    genuinely per-deployment lever Phase 0 introduces alongside the new
    role itself."""
    server_settings = get_server_settings(db)
    server_settings.default_module_entitlement_policy = payload.default_module_entitlement_policy
    log_event(
        db, entity_type="system", entity_id="platform", action="module_entitlement_policy_updated",
        actor_id=current_user.id, detail={"default_module_entitlement_policy": payload.default_module_entitlement_policy.value},
    )
    db.commit()
    db.refresh(server_settings)
    return server_settings


# --- Module registry & entitlement (module system Phase 1) ------------------


@router.get("/modules", response_model=list[ModuleOut])
def list_modules(
    current_user: User = Depends(require_server_role(ServerRole.MODULE_ADMINISTRATOR)),
):
    """Returns every module in the registry — "what modules exist," with
    no per-organisation entitlement/enablement data (see
    `list_org_module_entitlements` below for that). Gated the same as the
    entitlement-policy endpoints above."""
    return [
        ModuleOut(
            module_key=definition.key, name=definition.name, description=definition.description,
            version=definition.version, default_enabled=definition.default_enabled,
            implemented=definition.implemented,
        )
        for definition in get_module_registry().values()
    ]


@router.get("/orgs/{organization_id}/module-entitlements", response_model=list[OrgModuleEntitlementOut])
def list_org_module_entitlements(
    organization_id: UUID,
    current_user: User = Depends(require_server_role(ServerRole.MODULE_ADMINISTRATOR)),
    db: Session = Depends(get_db),
):
    """Lists every registered module combined with `organization_id`'s
    current effective and explicit entitlement state — the server-tier
    licensing/plan view (module system Phase 1)."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")

    overrides = {
        row.module_key: row
        for row in db.scalars(
            select(OrganizationModuleEntitlement).where(
                OrganizationModuleEntitlement.organization_id == organization_id
            )
        )
    }
    result: list[OrgModuleEntitlementOut] = []
    for definition in get_module_registry().values():
        override = overrides.get(definition.key)
        entitled = is_module_entitled(db, organization_id, definition.key)
        result.append(
            OrgModuleEntitlementOut(
                module_key=definition.key, name=definition.name, entitled=entitled,
                has_override=override is not None, default_policy_used=override is None,
            )
        )
    return result


@router.put(
    "/orgs/{organization_id}/module-entitlements/{module_key}", response_model=OrgModuleEntitlementOut
)
def update_org_module_entitlement(
    organization_id: UUID, module_key: str, payload: OrgModuleEntitlementUpdate,
    current_user: User = Depends(require_server_role(ServerRole.MODULE_ADMINISTRATOR)),
    db: Session = Depends(get_db),
):
    """Sets an explicit server-tier entitlement override for one
    organisation/module pair (module system Phase 1).

    Turning entitlement off does NOT cascade-delete any existing
    `OrganizationModuleEnablement` row for this org/module — that's
    intentional, not a missed cleanup: `is_module_enabled`'s effective
    formula already ANDs entitlement with enablement, so a stale
    `enabled=True` enablement row under a revoked entitlement is inert and
    presents no confusing effective state. A future reader should not "fix"
    this by adding a cascade delete.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    definition = get_module_registry().get(module_key)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found.")

    row = db.scalar(
        select(OrganizationModuleEntitlement).where(
            OrganizationModuleEntitlement.organization_id == organization_id,
            OrganizationModuleEntitlement.module_key == module_key,
        )
    )
    if row is None:
        row = OrganizationModuleEntitlement(organization_id=organization_id, module_key=module_key)
        db.add(row)
    row.entitled = payload.entitled
    row.updated_by = current_user.id
    log_event(
        db, entity_type="organization_module", entity_id=f"{organization_id}:{module_key}",
        action="module.entitlement_updated", actor_id=current_user.id, organization_id=organization_id,
        detail={"module_key": module_key, "entitled": payload.entitled},
    )
    db.commit()
    db.refresh(row)
    return OrgModuleEntitlementOut(
        module_key=definition.key, name=definition.name, entitled=row.entitled,
        has_override=True, default_policy_used=False,
    )


# --- Module-contributed MCP tools (module system Phase 4) -------------------


@router.get("/modules/mcp-tools", response_model=list[ModuleMcpToolOut])
def list_module_mcp_tools(current_user: User = Depends(get_current_user)):
    """Returns the manifest of every module-contributed `mcp-server/` tool
    across the live module registry (compliance-module-plan.md Phase 4) —
    what `mcp-server` fetches (lazily, on a caller's own already-presented
    token, cached in-process for a refresh window) to register declarative
    tools that proxy to a module's own REST endpoints.

    Gated by plain `get_current_user` — normal bearer-token authentication,
    deliberately with **no exemption**, per this phase's own hardening pass
    (docs/compliance-module-plan.md's "SOC2 / Security Planning" section):
    this must never become an unauthenticated boot-time call, even though
    the manifest itself carries no organisation-specific data. Per-call
    access to whatever a listed tool actually proxies to is still fully
    enforced by that endpoint's own `require_org_module_enabled`/
    `require_project_module_enabled`/`require_module_role` dependency —
    a tool being listed here has never implied a given caller can use it,
    exactly like `list_projects` in `mcp-server` already works today.

    Every entry has already been through `build_mcp_tool_manifest`'s
    mechanical verification — `mutates` is derived from HTTP method, never
    module-declared; any tool whose `path_template` fell outside its
    declaring module's own router, or that resolved to a route marked as an
    approval action, has already been excluded. This endpoint does no
    further filtering of its own.
    """
    return [
        ModuleMcpToolOut(
            name=tool.name, description=tool.description, method=tool.method,
            path_template=tool.path_template, mutates=tool.mutates, params=tool.params,
        )
        for tool in build_mcp_tool_manifest()
    ]
