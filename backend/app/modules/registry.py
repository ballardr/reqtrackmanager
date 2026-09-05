"""
Module: modules.registry

Builds and serves the merged module registry for the modular feature
system (compliance-module-plan.md Phase 1): the single source of truth for
"which modules exist" that `app.main` mounts routers from and
`app.services.rbac`'s `require_org_module_enabled`/
`require_project_module_enabled` dependencies, and the org/system admin
endpoints in `app.routers.orgs`/`app.routers.system`, all read from.

Three discovery sources are merged, in priority order (an earlier source's
`key` always wins over a later one, logged as a rejection):

1. `INSTALLED_MODULES` — a static, in-repo, code-reviewed list of
   first-party modules. **Always loads**, regardless of configuration.
2. Python entry points in the `reqtrackmanager.modules` group — the
   standard plugin-discovery idiom (the same one pytest/Flask extensions
   use) for a package deliberately `pip install`-ed into the deployment's
   image.
3. An optional local directory (`Settings.extra_modules_path`) scanned for
   subdirectories each containing a `module.py` — for a self-hosted
   operator adding a custom module without publishing a package.

Sources 2 and 3 are gated behind `Settings.allow_external_modules`
(default `False`) — see `Settings.allow_external_modules`'s own
docstring (`app.config`) for the full SOC 2 rationale (CC6.8). When the
flag is off, this module does not even call the discovery functions for
sources 2/3 — not merely filter their results — so no third-party package
metadata or filesystem path is scanned at all.

Design note on later phases: Phase 5+ first-party modules mount their own
`get_router()` behind `require_module_enabled`-family dependencies
*internally*, inside their own router module — there is no second gate
applied here at the `app.main` mount-loop level. This keeps the mount loop
itself trivial (a module either contributes a router or it doesn't) and
keeps all per-module authorization logic colocated with that module's own
endpoints, the same way every other router in this codebase already
handles its own dependency wiring rather than relying on a generic outer
gate.

External dependencies: none beyond the standard library
(`importlib.metadata`, `importlib.util`) and this project's own ORM/config
modules.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "reqtrackmanager.modules"


@dataclass(frozen=True)
class ModuleRoleDefinition:
    """Declares one module-contributed RBAC role (compliance-module-plan.md
    Phase 2) — a module's own analogue of a fixed `OrgRole`/`ProjectRole`
    enum member, without extending either enum (the design-history
    correction Phase 2 exists to satisfy: "modules should be able to
    register their own RBAC entitlements", not have their roles hardcoded
    onto the core enums).

    Every `ModuleDefinition.roles` entry is one of these. At process
    startup, `sync_module_role_definitions` mirrors the live set of these
    into the `module_role_definitions` table so a grant's display name/
    description stays resolvable even across a module being temporarily
    unregistered (see that function's own docstring); at request time,
    `app.services.rbac.require_module_role(module_key, role_key)` resolves
    a role's `scope` by reading it directly from here (the in-process
    registry), not from the database mirror.

    Attributes:
        role_key: Stable identifier for this role, unique within its
            module (e.g. `"compliance_manager"`) — used as the `role_key`
            column value in `UserModuleRole`/`ModuleRoleDefinitionRow`, so
            it must never change once a deployment has grants keyed on it.
        name: Human-readable display name shown in admin UIs (e.g.
            "Compliance Manager") — rendered directly by the frontend, not
            looked up through a frontend label map, since it is data
            returned by the API rather than a frontend-known closed enum.
        description: Short human-readable description of what the role is
            for, shown alongside `name` in admin UIs.
        scope: Either `"org"` (an organisation-scoped role, granted via
            `UserModuleRole` with `project_id IS NULL`) or `"project"` (a
            project-scoped role, granted with a specific `project_id`).
            Determines which `require_module_role` composition applies
            (`OrgRole.ORG_ADMIN` override for `"org"`, `ProjectRole.
            PROJECT_MANAGER` override for `"project"`) and which of the
            two "available module roles" read endpoints
            (`GET /orgs/{id}/module-roles` / `GET /projects/{id}/module-
            roles`) lists it.
    """

    role_key: str
    name: str
    description: str
    scope: Literal["org", "project"]


@dataclass(frozen=True)
class ModuleFrontendManifest:
    """Declares a module's frontend integration (compliance-module-plan.md
    Phase 3's two-tier frontend module system).

    Attributes:
        tier: `"installed"` (Tier A — the module ships route components and
            a nav entry compiled directly into the frontend bundle,
            registered in `frontend/src/modules/registry.ts`; this manifest
            carries only the nav-entry metadata, since the actual React
            components live in that frontend registry, not here — a Python
            backend value has no way to reference a React component) or
            `"remote"` (Tier B — the module is rendered in a sandboxed
            `<ModuleFrame>` iframe pointed at `frame_url`, with the Host UI
            Bridge relaying real shared-component chrome over `postMessage`).
        nav_label: Display label for this module's nav-rail entry.
        nav_path: The frontend route path this module's nav entry links to
            (e.g. `"/compliance"` or `"/projects/{project_id}/modules/
            compliance"`). For `"remote"` modules this is the path the host
            mounts the generic `<ModuleFrame>` route at; for `"installed"`
            modules it must match the path the module's own Tier A route
            registration in `frontend/src/modules/registry.ts` uses.
        frame_url: Required (and only meaningful) when `tier == "remote"` —
            the full origin+path the sandboxed iframe loads. Must resolve to
            an origin present in `Settings.module_frame_allowed_origins`, or
            `get_frontend_manifest` rejects it (logs a warning and returns
            `None` instead of this manifest) — mechanically enforced at the
            point of use, not trusted from the module's own declaration,
            mirroring Phase 4's path-prefix enforcement for MCP tools.
            `None` when `tier == "installed"`.
    """

    tier: Literal["installed", "remote"]
    nav_label: str
    nav_path: str
    frame_url: str | None = None

    def __post_init__(self) -> None:
        if self.tier == "remote" and not self.frame_url:
            raise ValueError("ModuleFrontendManifest: tier 'remote' requires frame_url.")
        if self.tier == "installed" and self.frame_url:
            raise ValueError("ModuleFrontendManifest: tier 'installed' must not set frame_url.")


@dataclass(frozen=True)
class McpToolDefinition:
    """Declares one module-contributed `mcp-server/` tool (compliance-
    module-plan.md Phase 4) — see docs/modules.md's "Module-contributed MCP
    tools" section for the full worked example and rationale, and
    `build_mcp_tool_manifest` (below) for how every security-relevant part
    of this declaration is mechanically re-derived or verified rather than
    trusted as written here.

    Attributes:
        name: A short *local* name (e.g. `"list_standards"`) — never a full
            global tool name. `build_mcp_tool_manifest` always prefixes it
            with the declaring module's own key (`"compliance_list_
            standards"`), regardless of what's passed here, so one module
            can never claim or collide with another module's or core's tool
            name.
        description: Shown to the calling AI assistant as the tool's
            description — write it the way you'd write a tool docstring.
        method: The HTTP method the underlying backend endpoint uses.
            `mutates` (`"GET"` -> `False`, everything else -> `True`) is
            derived from this by `build_mcp_tool_manifest` — deliberately
            not a separate field a module could misdeclare.
        path_template: The backend path this tool proxies to, e.g.
            `"/api/v1/orgs/{organization_id}/modules/compliance/standards/
            {standard_id}"`. Must fall inside this module's own
            `get_router()` mount prefix (its `APIRouter(prefix=...)`), and
            must name a real route on that router with a matching `method`
            — either failure excludes the tool entirely (logged), regardless
            of what's declared here. Every tool must name an explicit
            `{organization_id}` or `{project_id}` path placeholder — there
            is no implicit "current org" and no cross-org aggregation
            (docs/modules.md's Phase 4 section).
        params: One dict per tool parameter: `{"name": str, "type": str,
            "required": bool, "in": "path" | "query" | "body",
            "description": str}` (`"description"` may be omitted, defaulting
            to `""`). `type` is a display/JSON-Schema hint shown to the
            calling AI assistant (e.g. `"uuid"`, `"string"`, `"integer"`,
            `"boolean"`, `"number"`) — not itself a security boundary; real
            validation happens at the proxied backend endpoint, the same
            single source of truth every other request already goes
            through. A malformed entry (missing key, unrecognised `"in"`)
            excludes just that one parameter (logged), not the whole tool.
    """

    name: str
    description: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path_template: str
    params: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedMcpTool:
    """One module-contributed MCP tool that has survived `build_mcp_tool_
    manifest`'s mechanical verification (compliance-module-plan.md Phase 4)
    — this, not `McpToolDefinition`, is what `GET /api/v1/system/modules/
    mcp-tools` actually returns, and the only shape `mcp-server` ever sees.

    Unlike `McpToolDefinition`, every field here is either copied verbatim
    from a value already proven safe (the module-key-prefixed `name`) or
    derived/verified mechanically rather than taken from the module's own
    declaration (`mutates`; the very fact this entry exists at all implies
    its `path_template` fell inside its declaring module's own router and
    did not resolve to a route marked as an approval action).
    """

    name: str
    description: str
    method: str
    path_template: str
    mutates: bool
    params: list[dict]


#: `openapi_extra` key a route's own author sets to mark it as an
#: approval/decision-type action (e.g. `@router.post(..., openapi_extra=
#: APPROVAL_ACTION_ROUTE_EXTRA)`) — `build_mcp_tool_manifest` reads this
#: directly off the resolved route object and excludes any tool resolving
#: to such a route from the manifest entirely, regardless of what the
#: declaring module's own `McpToolDefinition` claims. See docs/modules.md's
#: Phase 4 section: "mark any endpoint that approves/decides something with
#: your route's own approval-action metadata — don't rely on the manifest
#: builder's exclusion as your only defence."
APPROVAL_ACTION_EXTRA_KEY = "x-approval-action"
APPROVAL_ACTION_ROUTE_EXTRA: dict = {APPROVAL_ACTION_EXTRA_KEY: True}

_VALID_MCP_TOOL_PARAM_LOCATIONS = {"path", "query", "body"}


def build_mcp_tool_manifest() -> list[ResolvedMcpTool]:
    """Builds the full, mechanically-verified manifest of every module-
    contributed MCP tool across the live registry (compliance-module-plan.md
    Phase 4) — the exact list `GET /api/v1/system/modules/mcp-tools`
    returns, and the only thing `mcp-server` ever sees of a module's
    `mcp_tools` declarations.

    Nothing about a tool's *safety* is trusted from the declaring module's
    own `McpToolDefinition` — each is re-derived or checked against real,
    already-reviewed data instead:

    - The registered `name` is always this tool's declaring module's `key`,
      an underscore, and its local `name` — never the module's local name
      alone, so a module can't claim another module's (or core's) tool name.
    - `path_template` must fall inside the declaring module's own
      `get_router()` mount prefix (`APIRouter.prefix`) and must name a real
      route on that router with a matching `method` — a module with no
      router at all can declare no legal tools; a `path_template` outside
      its own router, or with no matching route, is excluded (logged),
      regardless of what the module's own declaration claims.
    - `mutates` is derived purely from `method` (`"GET"` -> `False`,
      everything else -> `True`) — nothing for a module to misdeclare.
    - Whether the resolved route is an approval/decision-type action is
      read from *that route's own* `openapi_extra` metadata
      (`APPROVAL_ACTION_EXTRA_KEY`), set by the route's own author and
      reviewed the same way the endpoint itself is — never from the
      module's `McpToolDefinition`. Any tool resolving to such a route is
      excluded from the manifest entirely.

    This gives a genuinely mechanical guarantee for tools resolving to
    first-party module endpoints (this project's own reviewed code). For a
    third-party module's *own* endpoints, the guarantee reduces to the same
    "was deliberately installed" trust boundary `Settings.
    allow_external_modules` already establishes — a malicious third-party
    module could still mislabel its own route's own metadata. This isn't a
    gap unique to this mechanism; it's why third-party discovery defaults
    off in the first place.

    Returns:
        Every `ResolvedMcpTool` that survived verification, across every
        module currently in the registry, in registry iteration order
        (module) then declaration order (tool).
    """
    resolved: list[ResolvedMcpTool] = []
    for definition in get_module_registry().values():
        if not definition.mcp_tools:
            continue

        router = definition.get_router()
        if router is None:
            logger.warning(
                "Module %r declares %d MCP tool(s) but has no get_router() to validate them "
                "against; excluding all of them",
                definition.key, len(definition.mcp_tools),
            )
            continue

        routes_by_path_and_method: dict[tuple[str, str], object] = {}
        for route in router.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None) or ()
            if path is None:
                continue
            for method in methods:
                routes_by_path_and_method[(path, method.upper())] = route

        for tool in definition.mcp_tools:
            full_name = f"{definition.key}_{tool.name}"
            declared_method = tool.method.upper()

            if not tool.path_template.startswith(router.prefix):
                logger.warning(
                    "Module %r's MCP tool %r declares path_template %r outside its own "
                    "router prefix %r; excluding",
                    definition.key, tool.name, tool.path_template, router.prefix,
                )
                continue

            route = routes_by_path_and_method.get((tool.path_template, declared_method))
            if route is None:
                logger.warning(
                    "Module %r's MCP tool %r declares path_template=%r method=%r with no "
                    "matching route on its own router; excluding",
                    definition.key, tool.name, tool.path_template, declared_method,
                )
                continue

            if bool((getattr(route, "openapi_extra", None) or {}).get(APPROVAL_ACTION_EXTRA_KEY)):
                logger.warning(
                    "Module %r's MCP tool %r resolves to a route marked as an approval "
                    "action; excluding regardless of the module's own declaration",
                    definition.key, tool.name,
                )
                continue

            valid_params: list[dict] = []
            for param in tool.params:
                try:
                    param_name = str(param["name"])
                    location = str(param["in"])
                    required = bool(param["required"])
                    param_type = str(param["type"])
                except (KeyError, TypeError):
                    logger.warning(
                        "Module %r's MCP tool %r declares a malformed param %r; excluding "
                        "just this param",
                        definition.key, tool.name, param,
                    )
                    continue
                if location not in _VALID_MCP_TOOL_PARAM_LOCATIONS:
                    logger.warning(
                        "Module %r's MCP tool %r declares param %r with an unrecognised "
                        "'in' %r; excluding just this param",
                        definition.key, tool.name, param_name, location,
                    )
                    continue
                valid_params.append(
                    {
                        "name": param_name, "type": param_type, "required": required,
                        "in": location, "description": str(param.get("description", "")),
                    }
                )

            resolved.append(
                ResolvedMcpTool(
                    name=full_name, description=tool.description, method=declared_method,
                    path_template=tool.path_template, mutates=declared_method != "GET",
                    params=valid_params,
                )
            )
    return resolved


@dataclass(frozen=True)
class ModuleDefinition:
    """Declares a single module — first-party or third-party — to the
    modular feature system's registry.

    Attributes:
        key: Stable, unique identifier for the module (e.g. `"compliance"`)
            — used as the `module_key` column value in
            `OrganizationModuleEntitlement`/`OrganizationModuleEnablement`,
            so it must never change once a deployment has data keyed on it.
        name: Human-readable display name shown in admin UIs.
        description: Short human-readable description shown in admin UIs.
        version: The module's own version string (independent of the core
            application's `app.version`), logged at discovery time so a
            startup log line is a real operational record of what code
            entered the trust boundary on that run.
        default_enabled: Whether an organisation that is entitled to this
            module, but has no explicit `OrganizationModuleEnablement` row,
            gets it enabled by default. Compliance (Phase 5) is
            `default_enabled=True` per its own requirements' "enabled by
            default"; a more optional/experimental module would ship
            `default_enabled=False`.
        implemented: Whether this module actually does anything yet.
            `False` for a definition registered as a placeholder/in-
            progress (nothing in this plan requires that today, but the
            field exists so a future phase can register a module ahead of
            its full implementation landing without misrepresenting it as
            live) — admin UIs display this rather than hiding an
            unimplemented entry, matching the "don't hide, grey out"
            principle this plan already applies to non-entitled modules.
        get_router: Zero-argument callable returning the module's
            `APIRouter`, or `None` if it contributes no HTTP endpoints at
            all. Called (not stored eagerly) so a module can defer its own
            import-time work, and so a module with genuinely no router
            (e.g. one that only contributes MCP tools, Phase 4) can return
            `None` without needing a dummy empty router.
        roles: Module-contributed RBAC role declarations (module system
            Phase 2) — each a `ModuleRoleDefinition`. Synced into the
            `module_role_definitions` table at startup by
            `sync_module_role_definitions` and surfaced to callers of
            `list_enabled_module_roles`. Empty tuple for a module that
            contributes no roles of its own.
        frontend_manifest: Module-contributed frontend integration manifest
            (module system Phase 3) — a `ModuleFrontendManifest`, or `None`
            for a module with no frontend surface of its own (e.g. one that
            only contributes a backend router or MCP tools). Read through
            `get_frontend_manifest`, not this field directly, at any call
            site that renders it to a browser — that function additionally
            enforces the Tier B origin-allowlist check documented on
            `ModuleFrontendManifest.frame_url`.
        mcp_tools: Module-contributed MCP tool declarations (module system
            Phase 4) — each an `McpToolDefinition`. `build_mcp_tool_
            manifest` is what actually turns these into the real,
            mechanically-verified manifest `mcp-server` consumes; see that
            function's own docstring, and docs/modules.md §6 for a worked
            example. Empty tuple for a module that contributes no tools of
            its own.
        models_import_path: Dotted import path to this module's own ORM
            models submodule (e.g. `"app.modules.compliance.models"`), or
            `None` for a module with no models of its own. `import_all_
            module_models` (below) imports every registered module's
            declared path once, early, so `Base.metadata` — this project's
            single shared SQLAlchemy declarative registry — includes that
            module's tables without a hand-written `import app.modules.
            <key>.models` line in `alembic/env.py`/`tests/conftest.py` per
            module (module system Phase 5's own "one model-import line per
            first-party module" touch point, now automated instead of
            hand-maintained). Only ever *imports* a module's already-
            registered models — it grants no new trust: a module still has
            to be in the registry at all (first-party `INSTALLED_MODULES`,
            always reviewed in-repo code; or, if the deployment operator has
            explicitly opted in, `Settings.allow_external_modules`'s entry-
            point/path discovery) before this does anything with it.
            Importing a model class is inert with respect to any real
            database — it only registers a table *shape* in-process. This
            attribute has no bearing on whether that shape is ever actually
            applied to a live database; see `migrations_import_path` below
            for the (much more restricted) mechanism that does that.
        migrations_import_path: Dotted import path to a Python module
            exposing a `run_migrations(connection) -> None` function that
            applies this module's own database schema changes — or `None`
            for a module with no migration of its own (e.g. one with no
            models, or a first-party module, which ships a real Alembic
            migration in the reviewed core chain instead — see below).
            Applied by `apply_external_module_migrations`, called once at
            startup right after `alembic upgrade head` completes.

            **This is honoured only for a module discovered via `Settings.
            allow_external_modules`'s entry-point/path sources — never for
            an `INSTALLED_MODULES` (first-party) module**, even if one sets
            this field: `apply_external_module_migrations` checks registry
            *source*, not merely presence of the field, and logs a warning
            and skips it for any module whose `key` is also in `INSTALLED_
            MODULES`. First-party migrations must keep going through a
            reviewed PR into `backend/alembic/versions/`, exactly as before
            — this field exists to let an *externally discovered* module
            (one the deployment operator has already, separately, opted
            into via `allow_external_modules`) apply its own schema changes
            without a second, per-module core-repo edit, not to give a
            first-party module a second, less-reviewed path to the same
            end. `run_migrations(connection)` must be idempotent (safe to
            call on every process start, the same `CREATE TABLE IF NOT
            EXISTS`/`CREATE INDEX IF NOT EXISTS` convention every migration
            in `backend/alembic/versions/` already follows) — it is called
            every startup, not tracked against a per-module revision
            history the way Alembic tracks the core chain's own `alembic_
            version` table.
    """

    key: str
    name: str
    description: str
    version: str
    default_enabled: bool
    implemented: bool
    get_router: Callable[[], APIRouter | None]
    roles: tuple[ModuleRoleDefinition, ...] = field(default=())
    frontend_manifest: ModuleFrontendManifest | None = None
    mcp_tools: tuple[McpToolDefinition, ...] = field(default=())
    models_import_path: str | None = None
    migrations_import_path: str | None = None


# First-party modules. Always loaded regardless of `Settings.
# allow_external_modules` — this is in-repo code that goes through this
# project's normal review process, not a third-party discovery source.
#
# Left empty here deliberately, rather than populated with a top-of-file
# `from app.modules.compliance.module import MODULE_DEFINITION` — that
# module itself imports `ModuleDefinition`/`ModuleRoleDefinition` from
# *this* module, so importing it back before those names are defined would
# be a genuine circular import if anything ever imported
# `app.modules.compliance.module` directly ahead of this one (e.g. a test).
# `app/modules/__init__.py` is the composition root that appends first-party
# modules here instead: as a package `__init__`, it is guaranteed to finish
# running before any of its submodules (this one included) can be imported
# by anyone, so it can safely import this module to completion first and
# only then import a first-party module's own `module.py` — see its own
# docstring for the full reasoning.
INSTALLED_MODULES: list[ModuleDefinition] = []

_registry_cache: dict[str, ModuleDefinition] | None = None


def _discover_entry_point_modules() -> list[ModuleDefinition]:
    """Discovers third-party modules registered under the
    `reqtrackmanager.modules` entry-point group (`importlib.metadata`).

    Each entry point is expected to load to either a `ModuleDefinition`
    instance directly, or a zero-argument callable returning one. Any
    failure to load or resolve a single entry point is caught and logged
    (`logger.exception`) without aborting discovery of the others — one
    broken third-party package must not take down every other module, or
    the application's own startup.

    Only ever called when `Settings.allow_external_modules` is `True` —
    see this module's docstring and `build_registry`.

    Returns:
        The list of successfully resolved `ModuleDefinition` instances.
    """
    discovered: list[ModuleDefinition] = []
    try:
        entry_points = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        logger.exception("Failed to enumerate entry points for group %r", ENTRY_POINT_GROUP)
        return discovered

    for entry_point in entry_points:
        try:
            loaded = entry_point.load()
            definition = loaded() if callable(loaded) and not isinstance(loaded, ModuleDefinition) else loaded
        except Exception:
            logger.exception("Failed to load module entry point %r", entry_point.name)
            continue

        if not isinstance(definition, ModuleDefinition):
            logger.warning(
                "Entry point %r did not resolve to a ModuleDefinition (got %r); skipping",
                entry_point.name, type(definition),
            )
            continue

        logger.info(
            "Discovered module %r (version=%s, source=entry_point)", definition.key, definition.version
        )
        discovered.append(definition)

    return discovered


def _discover_path_modules(path_str: str) -> list[ModuleDefinition]:
    """Discovers third-party modules by scanning `path_str` for immediate
    subdirectories that each contain a `module.py` exposing a module-level
    `MODULE_DEFINITION` attribute.

    For a self-hosted operator adding a custom module without publishing a
    package. Same per-item try/except-and-log-and-continue behaviour as
    `_discover_entry_point_modules` — a broken module directory doesn't
    abort discovery of any other module. Only ever called when
    `Settings.allow_external_modules` is `True` — see this module's
    docstring and `build_registry`.

    Args:
        path_str: Directory to scan. Non-existent or non-directory paths
            are logged and treated as "no modules found" rather than
            raising, since a misconfigured/typo'd path is an operator
            error, not a reason to fail application startup.

    Returns:
        The list of successfully resolved `ModuleDefinition` instances.
    """
    discovered: list[ModuleDefinition] = []
    base_path = Path(path_str)
    if not base_path.is_dir():
        logger.warning("EXTRA_MODULES_PATH %r is not a directory; skipping path-based module discovery", path_str)
        return discovered

    for entry in sorted(base_path.iterdir()):
        if not entry.is_dir():
            continue
        module_file = entry / "module.py"
        if not module_file.is_file():
            continue

        try:
            spec = importlib.util.spec_from_file_location(f"_extra_module_{entry.name}", module_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not build an import spec for {module_file}")
            loaded_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded_module)
            definition = getattr(loaded_module, "MODULE_DEFINITION", None)
        except Exception:
            logger.exception("Failed to load module from path %r", str(module_file))
            continue

        if not isinstance(definition, ModuleDefinition):
            logger.warning(
                "Module directory %r did not expose a MODULE_DEFINITION ModuleDefinition; skipping", entry.name
            )
            continue

        logger.info("Discovered module %r (version=%s, source=path)", definition.key, definition.version)
        discovered.append(definition)

    return discovered


def build_registry(*, force: bool = False) -> dict[str, ModuleDefinition]:
    """Builds (and process-caches) the merged module registry.

    Always loads `INSTALLED_MODULES` first, logging each at `INFO` with
    `source=installed`. Then, **only if** `Settings.allow_external_modules`
    is `True`, discovers entry-point-registered modules and (if
    `Settings.extra_modules_path` is set) path-based modules; when the flag
    is `False`, neither discovery function is called at all — a single
    `INFO` log line records that discovery was skipped, which is itself
    part of the operational record this plan requires (see this module's
    docstring).

    Any externally-discovered module whose `key` collides with an
    already-registered key (from `INSTALLED_MODULES`, or an earlier
    external source) is skipped with a `WARNING` log — installed modules
    always win, and the first external module to claim a key wins over a
    later one.

    Args:
        force: Bypasses and rebuilds the process-level cache. Needed by
            tests that monkeypatch `INSTALLED_MODULES`, `Settings.
            allow_external_modules`, or the discovery functions themselves
            and need the change to actually take effect.

    Returns:
        A mapping of `module_key -> ModuleDefinition` for every module that
        made it into the merged registry.
    """
    global _registry_cache
    if _registry_cache is not None and not force:
        return _registry_cache

    registry: dict[str, ModuleDefinition] = {}

    for definition in INSTALLED_MODULES:
        if definition.key in registry:
            logger.warning("Duplicate installed module key %r; keeping the first one registered", definition.key)
            continue
        logger.info("Loaded module %r (version=%s, source=installed)", definition.key, definition.version)
        registry[definition.key] = definition

    settings = get_settings()
    if not settings.allow_external_modules:
        logger.info("ALLOW_EXTERNAL_MODULES is false; skipping entry-point and path module discovery")
    else:
        for definition in _discover_entry_point_modules():
            if definition.key in registry:
                logger.warning(
                    "External module %r (source=entry_point) collides with an already-registered key; skipping",
                    definition.key,
                )
                continue
            registry[definition.key] = definition

        if settings.extra_modules_path:
            for definition in _discover_path_modules(settings.extra_modules_path):
                if definition.key in registry:
                    logger.warning(
                        "External module %r (source=path) collides with an already-registered key; skipping",
                        definition.key,
                    )
                    continue
                registry[definition.key] = definition

    _registry_cache = registry
    return registry


def get_module_registry() -> dict[str, ModuleDefinition]:
    """Returns the merged module registry, building it (without forcing a
    rebuild) if it hasn't been built yet this process."""
    return build_registry()


def get_module(module_key: str) -> ModuleDefinition | None:
    """Returns the registered `ModuleDefinition` for `module_key`, or
    `None` if no module with that key is registered."""
    return get_module_registry().get(module_key)


def is_module_entitled(db: Session, organization_id: uuid.UUID, module_key: str) -> bool:
    """Resolves whether `organization_id` is entitled to use `module_key`
    (the server-tier licensing/plan lever, compliance-module-plan.md
    Phase 1).

    An explicit `OrganizationModuleEntitlement` row, if one exists, is
    authoritative. Otherwise, falls back to the deployment-wide
    `ServerSettings.default_module_entitlement_policy`. If no
    `ServerSettings` row exists at all (early bootstrap, before
    `services.branding.get_server_settings` has lazily created one),
    defaults to `True` (open) rather than raising — mirroring how other
    singleton-settings lookups in this codebase tolerate a missing row
    rather than treating it as an error (`services/branding.py`'s own
    "there might be zero rows" handling).

    Args:
        db: An active database session.
        organization_id: The organisation to resolve entitlement for.
        module_key: The module's registry key.

    Returns:
        `True` if the organisation is entitled to the module.
    """
    # Deferred import to avoid a circular import at module load time:
    # `app.models.organization` doesn't import this module, but importing
    # it eagerly at the top of this file would still be an unnecessary
    # coupling for a registry module whose other functions don't need it.
    from app.models.enums import ModuleEntitlementPolicy
    from app.models.module import OrganizationModuleEntitlement
    from app.models.organization import ServerSettings

    override = db.scalar(
        select(OrganizationModuleEntitlement).where(
            OrganizationModuleEntitlement.organization_id == organization_id,
            OrganizationModuleEntitlement.module_key == module_key,
        )
    )
    if override is not None:
        return override.entitled

    server_settings = db.scalar(select(ServerSettings))
    if server_settings is None:
        return True
    return server_settings.default_module_entitlement_policy == ModuleEntitlementPolicy.OPEN


def is_module_enabled(db: Session, organization_id: uuid.UUID, module_key: str) -> bool:
    """Resolves the *effective* enabled state of `module_key` for
    `organization_id` — entitlement AND enablement
    (compliance-module-plan.md Phase 1's exact formula: "Effective enabled
    = entitled(org,key) AND (org_row.enabled if present else
    registry.default_enabled)").

    Returns `False` immediately (without a database lookup for enablement)
    when the module isn't registered at all, or when the organisation
    isn't entitled to it — a disabled/non-entitled module must be
    indistinguishable from one that doesn't exist to the RBAC dependencies
    that call this (`app.services.rbac.require_org_module_enabled`/
    `require_project_module_enabled`, which both 404 rather than 403 on a
    `False` result here).

    Args:
        db: An active database session.
        organization_id: The organisation to resolve enablement for.
        module_key: The module's registry key.

    Returns:
        `True` only if the module exists, the organisation is entitled to
        it, and it is (explicitly or by registry default) enabled.
    """
    definition = get_module(module_key)
    if definition is None:
        return False
    if not is_module_entitled(db, organization_id, module_key):
        return False

    from app.models.module import OrganizationModuleEnablement

    override = db.scalar(
        select(OrganizationModuleEnablement).where(
            OrganizationModuleEnablement.organization_id == organization_id,
            OrganizationModuleEnablement.module_key == module_key,
        )
    )
    if override is not None:
        return override.enabled
    return definition.default_enabled


def import_all_module_models() -> None:
    """Imports every registered module's own `models_import_path`, if it
    declares one, so `Base.metadata` — this project's single shared
    SQLAlchemy declarative registry — includes that module's tables.

    This is what `alembic/env.py` and `tests/conftest.py` call instead of a
    hand-written `import app.modules.<key>.models` line per module: adding a
    first-party module's own models to `Base.metadata` (needed for Alembic
    autogenerate and `test_schema_migrations_match_models.py`'s drift check)
    now follows automatically from that module declaring `models_import_
    path` on its own `ModuleDefinition`, rather than requiring a matching
    edit in two core files every time. Call this once, early — before
    `Base.metadata` is read for anything — the same requirement `app.
    models`'s own "populates Base.metadata" import comment already implies
    for core models; this just does the equivalent for every module's own
    models too, driven by the registry instead of a hand-maintained list of
    imports.

    A module whose `models_import_path` fails to import (a typo, a genuine
    error in that module's own models module) is logged (`logger.exception`)
    and skipped — it does not abort every other module's import, the same
    per-module fault isolation `_discover_entry_point_modules`/`_discover_
    path_modules` already apply to a broken third-party module elsewhere in
    this file.

    Trust boundary — what this function does **not** do: it only imports
    Python model *classes* for a module already present in the live
    registry (first-party `INSTALLED_MODULES`, always reviewed in-repo
    code; or, only if the deployment operator has explicitly set `Settings.
    allow_external_modules`, an entry-point/path-discovered module).
    Importing a model class registers its table's *shape* with SQLAlchemy —
    it does not create, alter, or touch that table in any real database.
    Getting a real database's schema to actually match that shape is a
    separate, more restricted step: a first-party module's own migration
    still lands in the single, reviewed, linear `backend/alembic/versions/`
    chain exactly as before; an externally-discovered module's own schema
    changes are applied by `apply_external_module_migrations` (below), a
    materially more restricted mechanism than this one — see its own
    docstring for why running SQL against a real database is a categorically
    different risk than importing an inert Python class, and is gated
    accordingly.
    """
    for definition in get_module_registry().values():
        if not definition.models_import_path:
            continue
        try:
            importlib.import_module(definition.models_import_path)
        except Exception:
            logger.exception(
                "Failed to import models_import_path %r for module %r; its tables will not appear "
                "in Base.metadata",
                definition.models_import_path, definition.key,
            )


def apply_external_module_migrations(engine: Engine) -> None:
    """Applies every *externally-discovered* module's own database schema
    changes, via its declared `migrations_import_path` — the mechanism that
    lets a module dropped into `Settings.extra_modules_path` (e.g. a
    directory mounted into a container) or installed as a `pip`-installed
    entry-point package bring its own schema changes without a per-module
    edit to this repo's core, reviewed `backend/alembic/versions/` chain.

    Called once, early at process startup (`app.migrations.run_migrations`,
    right after `alembic upgrade head` completes) — after the core schema is
    known-current, and before anything else (route mounting, module-role
    sync) might touch a module's own tables.

    **Gating — deliberately more restrictive than `import_all_module_
    models`, not the same check reused:**

    1. A no-op entirely unless `Settings.allow_external_modules` is `True`
       — the existing off-by-default opt-in (see its own docstring for the
       CC6.8 rationale). When `False`, this function returns immediately
       without even building the registry further or importing anything.
    2. Even when external discovery is on, **only a module whose `key` is
       *not* also in the static `INSTALLED_MODULES` list gets its migration
       applied.** A first-party module declaring `migrations_import_path`
       anyway (it shouldn't) is logged as a warning and skipped — it must
       ship a real migration in the reviewed core chain instead, exactly as
       every existing first-party module (including Compliance's own 0026)
       already does. This is checked structurally (registry-key membership
       against the real `INSTALLED_MODULES` list), not trusted from
       anything the module itself claims about its own status — the same
       "verify, don't trust a self-declared field" principle this file
       already applies to a Tier B `frame_url` (`get_frontend_manifest`)
       and an MCP tool's `path_template`/`is_approval_action`
       (`build_mcp_tool_manifest`).

    Each qualifying external module's `run_migrations(connection)` runs in
    its **own** transaction (`engine.begin()` per module, not one shared
    transaction across every module) — deliberately, so one module's
    mid-migration failure rolls back only its own work and leaves the
    connection usable for the next module, rather than aborting a shared
    transaction every other module's own `connection.execute(...)` calls
    would then also fail against. A failure (an exception raised by the
    module's own `run_migrations`, or that module's `migrations_import_path`
    failing to import, or exposing no `run_migrations` attribute at all) is
    logged (`logger.exception`/`logger.warning`) and that module is skipped
    — it does not abort startup or any other module's own migration, the
    same per-module fault isolation this file already applies to a broken
    third-party module during discovery itself. A module whose migration
    fails may then have missing or incomplete tables of its own; its
    endpoints querying them will fail with ordinary database errors at
    request time rather than the whole application refusing to start over
    one external module's own bug.

    Honesty note, consistent with this file's existing one for MCP tools and
    Tier B frames: this closes the "core files need a per-module edit" gap
    for an *already-opted-into* external module, but does not and cannot
    make running that module's own SQL as safe as a first-party, PR-reviewed
    migration — the actual code being run is still whatever that module
    declares, and the operator's decision to set `allow_external_modules`
    is still what "was deliberately installed" (Phase 1's own trust
    boundary) hinges on. `run_migrations(connection)` must be idempotent —
    it is re-invoked on every process start, not tracked against a
    per-module revision history.

    Args:
        engine: The application's real SQLAlchemy `Engine` (`app.database.
            engine`) — a fresh connection/transaction is opened from it per
            qualifying module.
    """
    if not get_settings().allow_external_modules:
        logger.info("ALLOW_EXTERNAL_MODULES is false; skipping external-module migrations")
        return

    installed_keys = {definition.key for definition in INSTALLED_MODULES}

    for definition in get_module_registry().values():
        if not definition.migrations_import_path:
            continue

        if definition.key in installed_keys:
            logger.warning(
                "First-party module %r declares migrations_import_path %r; ignoring — a first-party "
                "module must ship a real Alembic migration in the reviewed core chain instead",
                definition.key, definition.migrations_import_path,
            )
            continue

        try:
            migrations_module = importlib.import_module(definition.migrations_import_path)
        except Exception:
            logger.exception(
                "Failed to import migrations_import_path %r for external module %r; its own schema "
                "changes were not applied",
                definition.migrations_import_path, definition.key,
            )
            continue

        run_migrations_fn = getattr(migrations_module, "run_migrations", None)
        if run_migrations_fn is None:
            logger.warning(
                "External module %r's migrations_import_path %r has no run_migrations(connection) "
                "function; its own schema changes were not applied",
                definition.key, definition.migrations_import_path,
            )
            continue

        try:
            with engine.begin() as connection:
                logger.info(
                    "Applying external module %r's own migration (source=external, path=%r)",
                    definition.key, definition.migrations_import_path,
                )
                run_migrations_fn(connection)
        except Exception:
            logger.exception(
                "External module %r's own migration raised; its schema may be missing or incomplete, "
                "but startup continues",
                definition.key,
            )


def sync_module_role_definitions(db: Session) -> None:
    """Mirrors every currently-registered module's `ModuleRoleDefinition`
    entries into the `module_role_definitions` table (module system
    Phase 2), upserting on `(module_key, role_key)`.

    Called once at process startup, right after `run_bootstrap` in
    `app.main`'s `lifespan` — the same "self-heal at every process start"
    pattern `run_migrations`/`run_bootstrap` already establish there, so a
    freshly-registered module's roles are queryable/grantable immediately
    without a separate seed step.

    For each `(module_key, role_key)` pair declared by the live registry,
    an existing row has its `name`/`description`/`scope` updated in place;
    a missing one is inserted. **Rows are never deleted for a module or
    role no longer present in the live registry** — this table is a
    deliberately append-only mirror, not a strict reflection of
    `get_module_registry()`'s current contents. The reasoning is the same
    "don't silently drop historical display data" philosophy this plan
    applies elsewhere (see Phase 8's evidence-revalidation history, which
    "must not overwrite the historical record"): a `UserModuleRole` grant
    made while a module was registered must stay resolvable to a real
    display name/description even if that module is later removed from
    `INSTALLED_MODULES` (a deployment downgrade, a third-party module
    uninstalled, ...) — an orphaned grant with no definition row to join
    against would otherwise render as a bare, meaningless role key in any
    admin UI or audit-log detail that looks it up. `list_enabled_module_
    roles` (the function that actually decides which roles are *offered*/
    *displayed as currently grantable*) filters by live registry
    membership and current org enablement separately — this function's own
    job is purely "keep the mirror caught up," not "decide what's active."

    Args:
        db: An active database session. Commits once at the end (mirrors
            `run_bootstrap`'s own single-commit-per-call shape); callers
            should not assume anything about the transaction state
            beforehand.
    """
    # Deferred import: `app.models.module_role` doesn't import this
    # module, but importing it eagerly at the top of this file would still
    # be an unnecessary coupling for a registry module whose other
    # functions don't need it (same rationale `is_module_entitled`/
    # `is_module_enabled` already use for their own deferred imports).
    from app.models.module_role import ModuleRoleDefinitionRow

    for definition in get_module_registry().values():
        for role in definition.roles:
            existing = db.scalar(
                select(ModuleRoleDefinitionRow).where(
                    ModuleRoleDefinitionRow.module_key == definition.key,
                    ModuleRoleDefinitionRow.role_key == role.role_key,
                )
            )
            if existing is None:
                db.add(
                    ModuleRoleDefinitionRow(
                        module_key=definition.key, role_key=role.role_key,
                        name=role.name, description=role.description, scope=role.scope,
                    )
                )
            else:
                existing.name = role.name
                existing.description = role.description
                existing.scope = role.scope
    db.commit()


def get_frontend_manifest(module_key: str) -> ModuleFrontendManifest | None:
    """Returns `module_key`'s `ModuleFrontendManifest`, or `None` if it has
    none, the module itself isn't registered, or (Tier B only) its declared
    `frame_url` doesn't resolve to an origin in `Settings.module_frame_
    allowed_origins` (module system Phase 3).

    This last check is deliberately mechanical, at the point of use, rather
    than trusted from the module's own declaration — the same "verify,
    don't trust a self-declared field" principle Phase 4 already applies to
    MCP tools' `path_template`/`is_approval_action`. A misconfigured or
    malicious `frame_url` outside the operator's own allowlist is logged
    and treated as "this module has no usable frontend integration," not
    silently rendered — the browser's own `Content-Security-Policy: frame-
    src` (built from the same allowlist, see `app.main`'s security-headers
    middleware) would refuse to load it anyway; this just gives a clear,
    attributable log line and an empty manifest instead of a
    browser-blocked, confusing-to-debug broken iframe.

    Args:
        module_key: The module's registry key.

    Returns:
        The module's `ModuleFrontendManifest` if it declares one and (for
        `tier == "remote"`) its origin is allowlisted; otherwise `None`.
    """
    definition = get_module(module_key)
    if definition is None or definition.frontend_manifest is None:
        return None
    manifest = definition.frontend_manifest
    if manifest.tier == "installed":
        return manifest

    from urllib.parse import urlsplit

    origin = urlsplit(manifest.frame_url).scheme + "://" + urlsplit(manifest.frame_url).netloc
    settings = get_settings()
    if origin not in settings.module_frame_allowed_origin_list:
        logger.warning(
            "Module %r declares a Tier B frame_url %r whose origin %r is not in "
            "MODULE_FRAME_ALLOWED_ORIGINS; excluding its frontend manifest",
            module_key, manifest.frame_url, origin,
        )
        return None
    return manifest


def list_enabled_module_roles(
    db: Session, organization_id: uuid.UUID, scope: Literal["org", "project"]
) -> list[tuple[str, ModuleRoleDefinition]]:
    """Lists `(module_key, ModuleRoleDefinition)` pairs for every role of
    the given `scope`, declared by a module that is currently *effectively
    enabled* (`is_module_enabled`) for `organization_id` (module system
    Phase 2).

    This is what backs the "available module roles" read endpoints
    (`GET /orgs/{id}/module-roles`, `GET /projects/{id}/module-roles`) and
    the enabled-modules-only filtering `list_org_users`/`GET .../effective-
    members` apply to a user's existing `module_roles` grants — a role
    whose module has since been disabled for this organisation is excluded
    from both the option list and any already-held grant's display, even
    though the underlying `UserModuleRole` row is left untouched (see
    `sync_module_role_definitions`'s docstring for the same "filter, don't
    delete" principle applied one layer up, at the definition-mirror
    level).

    Args:
        db: An active database session.
        organization_id: The organisation to resolve module enablement
            against.
        scope: `"org"` or `"project"` — only roles declared with this
            scope are returned.

    Returns:
        A list of `(module_key, ModuleRoleDefinition)` tuples, one per
        matching role, in registry iteration order.
    """
    result: list[tuple[str, ModuleRoleDefinition]] = []
    for definition in get_module_registry().values():
        if not is_module_enabled(db, organization_id, definition.key):
            continue
        for role in definition.roles:
            if role.scope == scope:
                result.append((definition.key, role))
    return result
