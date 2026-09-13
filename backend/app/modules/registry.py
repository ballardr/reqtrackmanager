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
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings

if TYPE_CHECKING:
    from alembic.config import Config
    from app.models.file import FileAsset
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.user import User
    from app.services.bundle_common import BundleImportWarnings, UserResolver

logger = logging.getLogger(__name__)

# `backend/` — the directory `alembic.ini`/`app.migrations.run_migrations`
# already treat as this project's own migration-tooling root. `migrations_
# dir` (on `ModuleDefinition`) and `configure_alembic_version_locations`
# (below) resolve every path relative to this, the same root `app.
# migrations._BACKEND_DIR` already anchors to, so both places agree on what
# a module's declared path is relative to regardless of the caller's own
# current working directory.
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

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
        scope: `"org"` (an organisation-scoped role, granted via
            `UserModuleRole` with `project_id`/`scope_entity_id` both
            `NULL`) and `"project"` (project-scoped, granted with a
            specific `project_id`) are the two core-recognised scopes —
            `require_module_role` auto-composes each with the matching
            core-role override (`OrgRole.ORG_ADMIN` for `"org"`,
            `ProjectRole.PROJECT_MANAGER` for `"project"`) and each is
            listed by its matching "available module roles" read endpoint
            (`GET /orgs/{id}/module-roles` / `GET /projects/{id}/module-
            roles`).

            A module may also declare **any other string** as `scope` —
            a module-owned entity scope (compliance-module-plan.md Phase
            22's own example: `"standard"`, one role per `ComplianceStandard`
            row) — for a role tied to one specific row of a first-class
            entity the module itself owns, narrower than "the whole org."
            This is the generalisation Phase 22 added specifically so a
            *future* module's own first-class entity gets the identical
            capability for free, rather than compliance's `"standard"`
            scope being hardcoded into this dataclass or into `require_
            module_role` by name (exactly the failure mode `CLAUDE.md`'s
            "Modular Feature System Boundary" section calls out). A
            non-core scope **must** also set `resolve_entity_organization_id`
            — see that field's own docstring — since there is no path
            parameter named after an arbitrary scope string for `require_
            module_role` to bind an `organization_id`/`project_id` from the
            way it can for `"org"`/`"project"`.
        overridden_by: Additional `(scope, role_key)` pairs, each another
            role *this same module* declares, whose grant also satisfies a
            check for *this* role — e.g. compliance's `standards_manager`
            (scope `"standard"`) declares `overridden_by=(("org",
            "compliance_manager"),)` so an org-wide Compliance Manager
            never needs a redundant per-standard grant too, the same "a
            higher tier already retains full access" principle core roles
            get for free one level up (`OrgRole.ORG_ADMIN` overriding every
            project's `ProjectRole.PROJECT_MANAGER`), extended one tier
            further down for a module-owned entity scope where there is no
            core-role equivalent to reuse. Checked *in addition to* (never
            instead of) the core `is_server_admin`/`OrgRole.ORG_ADMIN`/
            `ProjectRole.PROJECT_MANAGER` overrides, which always apply
            regardless of this field. Empty by default — most roles have no
            module-owned override tier above them.
        resolve_entity_organization_id: Required when `scope` is anything
            other than `"org"`/`"project"` — resolves the scoped entity's
            id (read by `require_module_role`'s generic entity-scope branch
            from the request's own path parameters, at the key
            `f"{scope}_id"`, e.g. `"standard_id"` for `scope="standard"`)
            to its owning organisation's id, or `None` if no such entity
            exists (surfaced as 404, matching every other module-gated
            dependency's "module disabled or entity absent -> 404, not
            403/500" posture). `None` for `"org"`/`"project"` roles, which
            resolve their organisation from the path directly instead.
    """

    role_key: str
    name: str
    description: str
    scope: str
    overridden_by: tuple[tuple[str, str], ...] = ()
    resolve_entity_organization_id: Callable[[Session, uuid.UUID], uuid.UUID | None] | None = None


@dataclass(frozen=True)
class ModuleFrontendManifest:
    """Declares a module's frontend integration (compliance-module-plan.md
    Phase 3's two-tier frontend module system, extended with a third tier —
    "Tier C" — in a same-system follow-up, 2026-09-07: Module Federation for
    a genuinely third-party, not-compiled-in, no-rebuild-required module.
    See `docs/decisions.md`'s "Module system follow-up: Tier C (Module
    Federation)" entries and `docs/modules.md`'s "Tier C" section for the
    full account and worked examples.

    Attributes:
        tier: `"installed"` (Tier A — the module ships route components and
            a nav entry compiled directly into the frontend bundle,
            registered in `frontend/src/modules/registry.ts`; this manifest
            carries only the nav-entry metadata, since the actual React
            components live in that frontend registry, not here — a Python
            backend value has no way to reference a React component),
            `"remote"` (Tier B — the module is rendered in a sandboxed
            `<ModuleFrame>` iframe pointed at `frame_url`, with the Host UI
            Bridge relaying real shared-component chrome over `postMessage`),
            or `"federated"` (Tier C — the module ships a self-contained
            Module Federation remote, built entirely outside this repo's own
            build, and is `import()`-ed at runtime by the host frontend,
            sharing the host's own React/component-library instances rather
            than an isolated iframe. **Only ever produced by a module
            discovered through the third-party pipeline (`Settings.
            allow_external_modules`'s entry-point/path sources) — never by
            an `INSTALLED_MODULES` (first-party) entry.** `get_frontend_
            manifest` mechanically enforces this (logs an error and excludes
            the manifest, the same "verify, don't trust a self-declared
            field" treatment Tier B's `frame_url` already gets) rather than
            trusting a module not to misdeclare it, since a first-party
            module has no legitimate reason to use Tier C at all — it can
            use Tier A directly, with full build-time review. **This is a
            materially wider trust concession than either Tier A or Tier
            B**: unlike Tier A, the code was never in this repo and got no
            build-time review at all; unlike Tier B, there is no iframe
            sandbox whatsoever — a federated module shares the same origin,
            DOM, cookies, and live component tree as the host. The trust
            falls entirely to the deployment operator to review and vet any
            such plugin before enabling it, exactly as `Settings.
            allow_external_modules`'s own docstring and `docs/soc2/policies/
            vendor-and-subprocessor-management-policy.md` already require
            for any third-party module — Tier C raises the stakes of that
            same existing gate rather than opening a new, separately-gated
            one (see `remote_entry_url`/`exposed_module` below for why no
            second, independent frontend flag was added).
        nav_label: Display label for this module's nav-rail entry.
        nav_path: The frontend route path this module's nav entry links to
            (e.g. `"/compliance"` or `"/projects/{project_id}/modules/
            compliance"`). For `"remote"` modules this is the path the host
            mounts the generic `<ModuleFrame>` route at; for `"installed"`
            and `"federated"` modules it must match the path the module's
            own Tier A/Tier C route registration uses (a `"federated"`
            module registers its route the same way a Tier A module does —
            see `remote_entry_url` below — once its remote entry has loaded).
        frame_url: Required (and only meaningful) when `tier == "remote"` —
            the full origin+path the sandboxed iframe loads. Must resolve to
            an origin present in `Settings.module_frame_allowed_origins`, or
            `get_frontend_manifest` rejects it (logs a warning and returns
            `None` instead of this manifest) — mechanically enforced at the
            point of use, not trusted from the module's own declaration,
            mirroring Phase 4's path-prefix enforcement for MCP tools.
            `None` for every other tier.
        remote_entry_url: Required (and only meaningful) when `tier ==
            "federated"` — the URL of the remote's Module Federation entry
            script (e.g. `"/external-modules/my-module/remoteEntry.js"`, the
            documented same-origin nginx-served convention — see `docs/
            deployment.md`'s "Adding a Tier C (federated) frontend module" —
            or an absolute URL at an externally-hosted location, mirroring
            Tier B's `frame_url`-is-any-URL precedent). **Deliberately not
            allowlist-checked the way Tier B's `frame_url` is**: there is no
            `MODULE_FRAME_ALLOWED_ORIGINS`-equivalent setting for Tier C.
            This is a considered omission, not an oversight — see `Settings.
            allow_external_modules`'s own docstring for the reasoning
            (`get_frontend_manifest` below can only ever see a `"federated"`
            manifest at all for a module that already came from the gated
            third-party discovery pipeline, so the discovery gate itself is
            what stands in for a second, independent allowlist here; unlike
            Tier B, which a first-party module can also legitimately use and
            therefore does need a *separate* origin check). `None` for every
            other tier.
        exposed_module: Required (and only meaningful) when `tier ==
            "federated"` — the Module Federation "exposed module" name the
            remote publishes (e.g. `"./Module"`), `import()`-ed from the
            container the host dynamically loads from `remote_entry_url`.
            `None` for every other tier.
    """

    tier: Literal["installed", "remote", "federated"]
    nav_label: str
    nav_path: str
    frame_url: str | None = None
    remote_entry_url: str | None = None
    exposed_module: str | None = None

    def __post_init__(self) -> None:
        if self.tier == "remote":
            if not self.frame_url:
                raise ValueError("ModuleFrontendManifest: tier 'remote' requires frame_url.")
            if self.remote_entry_url or self.exposed_module:
                raise ValueError(
                    "ModuleFrontendManifest: tier 'remote' must not set remote_entry_url/exposed_module "
                    "(those are Tier C 'federated'-only fields)."
                )
        elif self.tier == "installed":
            if self.frame_url or self.remote_entry_url or self.exposed_module:
                raise ValueError(
                    "ModuleFrontendManifest: tier 'installed' must not set frame_url/remote_entry_url/"
                    "exposed_module."
                )
        elif self.tier == "federated":
            if self.frame_url:
                raise ValueError(
                    "ModuleFrontendManifest: tier 'federated' must not set frame_url (that is Tier B's "
                    "field — use remote_entry_url/exposed_module instead)."
                )
            if not self.remote_entry_url or not self.exposed_module:
                raise ValueError(
                    "ModuleFrontendManifest: tier 'federated' requires both remote_entry_url and exposed_module."
                )


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


@dataclass(frozen=True)
class ModuleScheduledJob:
    """Declares one date-driven background sweep a module needs run
    periodically (compliance-module-plan.md Phase 10) — e.g. Compliance's
    evidence-expiry/review-due/required-action-due/target-date sweeps
    (§18, §28). `app.services.scheduler.start_scheduler` registers every
    registered module's declared jobs generically, alongside its own two
    core jobs, so a module needing scheduled processing doesn't require a
    hand-written edit to that core file — the same "core code shouldn't
    need much modification per module" goal `get_router`/`resolve_file_
    owner_project_id` already serve for other concerns, applied here to
    APScheduler wiring.

    Attributes:
        job_id: A short, module-unique identifier (e.g. `"evidence_expiry_
            reminders"`) — `start_scheduler` prefixes it with the
            declaring module's own key (`"compliance_evidence_expiry_
            reminders"`) when registering it with APScheduler, so two
            modules can never collide on a job id even if they pick the
            same short name.
        hour / minute: When this job runs, in the container's local time —
            mirrors `start_scheduler`'s own two core jobs (`hour=1,
            minute=0`/`15`), which stagger their run times rather than
            firing simultaneously; a module should do the same relative to
            existing jobs to avoid an unnecessary DB-load spike, though
            nothing enforces this mechanically.
        run: A callable taking one open `Session` and performing the sweep
            — mirrors `services.reviews.send_due_review_reminders`'s own
            `(db: Session) -> None` shape exactly. `start_scheduler` opens
            and closes the session around this call; the callable itself
            never opens its own.
    """

    job_id: str
    hour: int
    minute: int
    run: Callable[[Session], None]


@dataclass(frozen=True)
class ModuleOrgBundleHooks:
    """Declares a module's contribution to `app.services.org_export`'s
    organisation export/import bundle — the same "core code shouldn't need
    much modification per module" goal `get_router`/`resolve_file_owner_
    project_id`/`scheduled_jobs` already serve, applied to bundle export/
    import (added when Compliance's own Phase 15 content was pulled out of
    `org_export.py` directly importing `app.modules.compliance`, mirroring
    the same module-self-containment principle `resolve_file_owner_
    project_id` already established one concern earlier).

    A module with content that belongs at the *organisation* level in a
    bundle (e.g. Compliance's standards/versions/requirements, which are
    org-level reusable resources per its own §31) declares this; a module
    with no org-level bundle content of its own simply leaves `ModuleDefinition.
    org_bundle_hooks` at its default `None`.

    Attributes:
        export: `(db, org) -> dict` — collects this module's own
            organisation-scoped content as plain JSON-serialisable data,
            keyed however the module likes (Compliance uses `compliance_*`
            keys); merged into `org_export.build_org_bundle`'s own returned
            `org_json` dict via `**`, alongside every other registered
            module's contribution and the core sections `org_export.py`
            itself still owns directly (settings, members, groups, report
            templates).
        import_: `(db, org, data, users, warnings, resolutions) -> None` —
            writes this module's content from a parsed bundle's `data` dict
            into `org`, resolving user references via the shared `users`
            (`app.services.bundle_common.UserResolver`) and recording
            anything skipped/unresolved via `warnings`. Called by both
            `org_export.import_org_bundle` (fresh organisation,
            `resolutions=None`: every entity is new) and `org_export.
            merge_org_bundle` (existing organisation, `resolutions` a real
            conflict-id -> resolution-value map) — a hook implementation
            branches on whether `resolutions` is `None` the same way
            `org_export.py`'s own core `_import_*` helpers already do for
            report templates/projects.
        compute_merge_conflicts: Optional `(db, target_org, data) -> list[dict]`
            — this module's own name/reference-collision conflicts (the
            same `{"id", "kind", "name", "existing_id"}` shape `org_export.
            _compute_merge_conflicts`'s core entries use), extended onto
            that function's own `conflicts` list. `None` for a module whose
            content is always purely additive on merge (never a namable
            collision), like Compliance's own vocabulary import.
        merge_resolution_choices: `{kind: {allowed resolution values}}` for
            every conflict `kind` this module's `compute_merge_conflicts`
            can report — merged into `org_export.merge_org_bundle`'s own
            `_resolution_choices_by_kind` dict, so a conflict this module
            reports is validated the same way a core `"project"`/`"report_
            template"` conflict already is. Empty for a module with no
            `compute_merge_conflicts` of its own.
        summarize_merge: Optional `(data, conflicts, resolutions) -> dict[str, int]`
            — this module's own named counts (e.g. `{"compliance_standards_
            imported": ..., "compliance_standards_skipped": ...}`) merged
            into `merge_org_bundle`'s own returned/audit-logged summary
            dict. `None` for a module with nothing worth summarising
            separately from its raw import.
    """

    export: Callable[[Session, Organization], dict[str, Any]]
    import_: Callable[
        [Session, Organization, dict[str, Any], UserResolver, BundleImportWarnings, dict[str, str] | None], None
    ]
    compute_merge_conflicts: Callable[[Session, Organization, dict[str, Any]], list[dict[str, Any]]] | None = None
    merge_resolution_choices: Mapping[str, frozenset[str]] = field(default_factory=dict)
    summarize_merge: Callable[[dict[str, Any], list[dict[str, Any]], dict[str, str]], dict[str, int]] | None = None


@dataclass(frozen=True)
class ModuleProjectBundleHooks:
    """Declares a module's contribution to `app.services.project_export`'s
    project export/import bundle — `ModuleOrgBundleHooks`'s project-scoped
    counterpart (a project's own compliance *assessment* content is
    project-scoped per Compliance's own Phase 15 notes, unlike the standard
    *definitions* `ModuleOrgBundleHooks` carries).

    Attributes:
        export: `(db, project) -> (dict, {file_id: FileAsset})` — collects
            this module's own project-scoped content plus any `FileAsset`
            rows it references, in the same `(json, file_assets_by_id)`
            shape `project_export.collect_project_data` itself returns;
            merged into that function's own two return values via `**`/
            `dict.update` respectively.
        import_: `(db, project, data, file_bytes_by_ref, current_user, users,
            warnings) -> None` — writes this module's content from a parsed
            bundle's `data` dict into `project`, resolving attachment bytes
            via `file_bytes_by_ref` and user references via `users`
            (`app.services.bundle_common.UserResolver`), called from
            `project_export.apply_project_data` after every core section
            has already run.
    """

    export: Callable[[Session, Project], tuple[dict[str, Any], dict[uuid.UUID, FileAsset]]]
    import_: Callable[
        [Session, Project, dict[str, Any], dict[str, bytes], User, UserResolver, BundleImportWarnings], None
    ]


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
    - `path_template` must fall inside one of the declaring module's own
      router mount prefixes (`get_router()`'s, or `get_project_router()`'s
      when the module declares one too — compliance-module-plan.md Phase 7
      is the first module with both) and must name a real route on
      *that same router* with a matching `method` — a module with no
      router at all can declare no legal tools; a `path_template` outside
      every one of its own routers, or with no matching route, is excluded
      (logged), regardless of what the module's own declaration claims.
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

        routers = [
            r for r in (
                definition.get_router(),
                definition.get_project_router() if definition.get_project_router is not None else None,
                definition.get_global_router() if definition.get_global_router is not None else None,
            )
            if r is not None
        ]
        if not routers:
            logger.warning(
                "Module %r declares %d MCP tool(s) but has no router (get_router()/"
                "get_project_router()/get_global_router()) to validate them against; "
                "excluding all of them",
                definition.key, len(definition.mcp_tools),
            )
            continue

        router_prefixes = [r.prefix for r in routers]
        routes_by_path_and_method: dict[tuple[str, str], object] = {}
        for r in routers:
            for route in r.routes:
                path = getattr(route, "path", None)
                methods = getattr(route, "methods", None) or ()
                if path is None:
                    continue
                for method in methods:
                    routes_by_path_and_method[(path, method.upper())] = route

        for tool in definition.mcp_tools:
            full_name = f"{definition.key}_{tool.name}"
            declared_method = tool.method.upper()

            if not any(tool.path_template.startswith(p) for p in router_prefixes):
                logger.warning(
                    "Module %r's MCP tool %r declares path_template %r outside its own "
                    "router prefix(es) %r; excluding",
                    definition.key, tool.name, tool.path_template, router_prefixes,
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
        get_project_router: Like `get_router`, but for a second, optional
            router mounted at a genuinely different path root (compliance-
            module-plan.md Phase 7). Phases 0-6 only ever needed one router
            per module, always org-scoped (`/api/v1/orgs/{organization_id}/
            modules/<key>/...`). Phase 7 is the first module surface that
            also needs project-scoped endpoints living at their own,
            unprefixed-by-org path root (`/api/v1/projects/{project_id}/
            modules/<key>/...`) — required so that an MCP tool proxying to
            one of them can declare `project_id` as its only path
            parameter (mirroring hand-written tools like `get_project
            (project_id)`), which is impossible if the underlying route
            also carries an `{organization_id}` placeholder. `None` for a
            module with no project-scoped router of its own (every module
            before Phase 7). `build_mcp_tool_manifest` validates a tool's
            `path_template` against **either** of a module's two router
            prefixes, not just `get_router`'s — see that function's own
            docstring. `app.main`'s mount loop mounts both, the same way,
            with no second gate applied at the mount-loop level (see this
            module's own docstring).
        get_global_router: Like `get_router`, but for a third, optional
            router mounted at a path root carrying **neither** an
            `organization_id` nor a `project_id` placeholder at all
            (compliance-module-plan.md Phase 18). `get_router`/`get_
            project_router` both assume the module's endpoint is reachable
            through *some* resource id already present in the URL; Phase 18
            needed two endpoints with no such id to key off in the first
            place — `GET /api/v1/compliance/nav-visibility` (aggregates
            across every org the caller belongs to, so no single
            `organization_id` applies) and `GET /api/v1/compliance/
            standards/{standard_id}` (deliberately un-prefixed by org,
            mirroring how a project's own id already resolves to its org
            without an `organization_id` segment — see `app.routers.
            projects.get_project`). `None` for a module with no such
            router of its own (every module before Phase 18). Mounted by
            `app.main`'s mount loop exactly like the other two, with no
            second gate applied at the mount-loop level; a route in this
            router must therefore perform whatever org/project resolution
            and access checks it needs *internally*, the same way `get_
            router`'s/`get_project_router`'s own routes already do for
            their path-parameter-derived scope — see `app.services.rbac.
            require_org_access_and_module_enabled` for the reusable,
            non-dependency-factory sibling of `require_org_module_enabled`
            this shape needs (a route here resolves its own
            `organization_id` from some other identifier first, so it
            can't bind a FastAPI dependency directly off an
            `organization_id` path parameter the way `get_router`'s routes
            do). `build_mcp_tool_manifest` validates a tool's
            `path_template` against **any** of a module's three router
            prefixes, not just `get_router`'s/`get_project_router`'s — see
            that function's own docstring.
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
            applied to a live database; see `migrations_dir`/`migrations_
            import_path` below for the two (differently-restricted)
            mechanisms that do that.
        migrations_dir: Path (relative to `backend/`, e.g. `"app/modules/
            compliance/migrations"`) to this **first-party** module's own
            directory of real Alembic revision scripts, or `None` for a
            module with no migration of its own. `configure_alembic_
            version_locations` (below) adds every registered module's
            declared directory, plus the core `alembic/versions` directory,
            to Alembic's own multi-directory `version_locations` — added in
            a compliance-module-plan.md Phase 11 follow-up, after Phase 1's
            original design placed every first-party migration in
            `backend/alembic/versions/` regardless of which module it
            belonged to, and direct feedback observed that colocating a
            module's migration alongside the rest of that module's own code
            (models/service/router/tests) would read more coherently as
            more first-party modules accumulate. **This does not reopen or
            weaken the trust boundary Phase 1 established** — it is a pure
            *file-location* change, not a change to *what gets reviewed or
            how*: Alembic still builds exactly one linear revision graph,
            tracked by exactly one `alembic_version` row in the target
            database, regardless of how many directories its component
            files are split across (each file's own `down_revision` string
            is what defines chain order, not its directory); every first-
            party module's migration file still goes through this repo's
            normal PR review the same as any other in-repo Python file,
            wherever it physically lives. `migrations_dir` is honoured for
            *any* module present in the live registry — first-party or,
            unlike `migrations_import_path` below, an externally-discovered
            one too — since merely *locating* a directory of files Alembic
            will scan is a categorically smaller trust grant than *executing
            arbitrary SQL against a live database* (which is exactly what
            `migrations_import_path` gates far more narrowly): an
            externally-discovered module's migration files still only run
            through Alembic's own normal apply-and-track-one-row-per-
            revision mechanism, the same scrutiny every other revision in
            the chain gets, not a silent side-channel.
        migrations_import_path: Dotted import path to a Python module
            exposing a `run_migrations(connection) -> None` function that
            applies this module's own database schema changes outside the
            Alembic-tracked chain entirely — or `None` for a module with no
            migration of its own (e.g. one with no models, or a first-party
            module, which always uses `migrations_dir` above instead — see
            below for why these are two genuinely different mechanisms, not
            two names for the same thing). Applied by `apply_external_
            module_migrations`, called once at startup right after `alembic
            upgrade head` completes.

            **This is honoured only for a module discovered via `Settings.
            allow_external_modules`'s entry-point/path sources — never for
            an `INSTALLED_MODULES` (first-party) module**, even if one sets
            this field: `apply_external_module_migrations` checks registry
            *source*, not merely presence of the field, and logs a warning
            and skips it for any module whose `key` is also in `INSTALLED_
            MODULES`. A first-party module's schema changes must keep going
            through a real, Alembic-tracked revision file reviewed the same
            as any other in-repo Python file (`migrations_dir` above,
            regardless of which directory that file happens to live in) —
            this field exists to let an *externally discovered* module (one
            the deployment operator has already, separately, opted into via
            `allow_external_modules`) apply its own schema changes without
            a second, per-module core-repo edit, not to give a first-party
            module a second, less-reviewed path to the same end. The
            categorical difference from `migrations_dir` is *tracking*, not
            trust: a `migrations_dir` revision is a permanent, ordered node
            in the one Alembic-tracked chain (applied once, ever, recorded
            in `alembic_version`); `run_migrations(connection)` here is
            **not** tracked against any revision history at all and must
            therefore be idempotent (safe to call on every process start,
            the same `CREATE TABLE IF NOT EXISTS`/`CREATE INDEX IF NOT
            EXISTS` convention every Alembic revision in this project
            already follows) — it runs fresh, unconditionally, every single
            startup, which is precisely why this mechanism is reserved for
            a module whose own code the deployment operator has *already*
            separately decided to trust (`allow_external_modules`), not
            extended to every module merely because it's convenient.
        resolve_file_owner_project_id: Optional hook (compliance-module-
            plan.md Phase 8) letting a module authorize downloads of files
            it owns through the single generic `GET /api/v1/files/{id}`
            endpoint (`app.routers.files.download_file`), without that
            core, module-agnostic router needing to import anything from
            the module directly — the same "core code shouldn't need much
            modification per module" goal `get_router`/`get_project_router`
            already serve for HTTP endpoints, applied to this one
            remaining core file that every module sharing the existing
            file-attachment mechanism (§13's own "reuse ReqTrackManager's
            existing attachment/file mechanisms") needs a hook into.
            `download_file` calls `resolve_module_file_project_id` (below),
            which tries this hook, in registry order, across every
            registered module until one returns a project id or all
            return `None`. Takes `(db, file_id)`, returns the owning
            project's id if this module's own file-link table (e.g.
            Compliance's `ComplianceEvidenceFile`) references `file_id`,
            else `None`. `None` for a module with no file attachments of
            its own (every module before Phase 8).
        scheduled_jobs: Module-contributed APScheduler jobs (compliance-
            module-plan.md Phase 10) — each a `ModuleScheduledJob`.
            Registered generically by `app.services.scheduler.
            start_scheduler`, job-id-prefixed with this module's own `key`.
            Empty tuple for a module with no scheduled processing of its
            own (every module before Phase 10).
        org_bundle_hooks: Optional `ModuleOrgBundleHooks` — this module's
            contribution to `app.services.org_export`'s organisation bundle
            export/import, read via `get_all_module_org_bundle_hooks`.
            `None` for a module with no org-level bundle content of its own.
        project_bundle_hooks: Optional `ModuleProjectBundleHooks` — this
            module's contribution to `app.services.project_export`'s
            project bundle export/import, read via `get_all_module_
            project_bundle_hooks`. `None` for a module with no project-level
            bundle content of its own.
        on_org_created: Optional hook (module boundary cleanup, 2026-09-08 —
            see `docs/decisions.md`'s "Module system follow-up: on_org_created
            / project_nav_visible hooks" entry) called once, synchronously,
            right after a brand-new `Organization` row is flushed —
            `app.routers.orgs.create_organization` and
            `app.services.bootstrap.run_bootstrap` (the only two places an
            organisation is ever created outside a bundle import) both call
            `run_on_org_created_hooks` (below) instead of importing any
            specific module to seed its own org-scoped defaults, the same
            "core code shouldn't need to know a specific module exists" goal
            `resolve_file_owner_project_id` already serves for file
            downloads. Takes `(db, organization_id)`, returns nothing;
            the module owns its own transaction participation (add rows,
            don't commit — the caller commits once for the whole org-creation
            transaction, same convention `seed_project_statuses`/
            `seed_link_types` already follow). `None` for a module with
            nothing to seed at org-creation time (every module before
            Compliance's `seed_compliance_action_types`). Deliberately not
            an "on module enabled" hook — the module system has no such
            callback (enablement is a boolean row toggle, not an event), and
            org-creation time is the one deterministic point that can't race
            or double-seed regardless of a module's own default-enabled
            policy; see `seed_compliance_action_types`'s own docstring.
        project_nav_visible: Optional hook (same 2026-09-08 cleanup) letting
            a module hide its own already-enabled project-scoped nav
            entry/route for a specific project, beyond simple enablement
            (which `app.routers.projects.list_project_enabled_modules`
            already checks via `is_module_enabled` before ever consulting
            this) — e.g. Compliance hides its nav entry until its owning
            organisation has at least one `PUBLISHED` standard version, so a
            project isn't sent to an "assign a standard" screen with nothing
            to pick from. Takes `(db, project)`, returns `True` if the
            already-enabled entry should still show. `None` (the default)
            means "always visible once enabled," preserving every module's
            prior behaviour without needing to declare this hook at all.
        on_project_created: Optional hook (docs/compliance-module-plan.md
            Phase 20) called once, synchronously, right after a brand-new
            `Project` row is flushed — `app.routers.projects.create_project`
            calls `run_on_project_created_hooks` (below) instead of
            importing any specific module, mirroring `on_org_created`'s own
            "core code shouldn't need to know a specific module exists"
            reasoning exactly, one lifecycle event later. Compliance uses
            this to reconcile the new project against every `applies_to_
            all_projects` standard in its organisation (`service.py::
            reconcile_new_project_for_all_standards`) — a project created
            after a standard was switched to that mode must get the same
            treatment a pre-existing project already got, at the moment of
            its own creation, never a lazily-computed "in scope but no real
            row" state. Takes `(db, project, actor_id)` — `actor_id` is the
            project's own creator, attributed on any row this hook creates
            (a real human action, unlike a hypothetical future passive
            sweep) — and returns nothing; the module owns its own
            transaction participation (add rows, don't commit — the caller
            commits once for the whole project-creation transaction, same
            convention `on_org_created` already follows). `None` for a
            module with nothing to react to at project-creation time (every
            module before Compliance's Phase 20).
        validate_org_group_member_removal: Compliance-module-plan.md Phase
            22's own generic hook — `app.routers.orgs.remove_org_group_
            member` calls every registered module's copy of this (via
            `run_org_group_member_removal_hooks`, below) before actually
            removing a *user* member (never a nested-group member) from an
            `OrgGroup`, so a module that treats a specific group as some
            kind of fallback/floor-satisfying membership (compliance's own
            "default compliance-managers group," Phase 22 §3) can block a
            removal that would leave one of its own floors unsatisfiable —
            the exact same "can't leave zero" reasoning `routers/projects.
            py`'s project-manager-floor guards already apply, generalised
            so *this* core endpoint never needs to import a specific
            module's own models to enforce a module-owned invariant (the
            Modular Feature System Boundary this plan's own `CLAUDE.md`
            section names by number). Takes `(db, org_group_id,
            member_user_id)`; returns a human-readable block message (the
            endpoint 400s with it) or `None` to allow the removal. `None`
            for a module with no group-based floor concept of its own
            (every module before Compliance's Phase 22).
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
    migrations_dir: str | None = None
    migrations_import_path: str | None = None
    get_project_router: Callable[[], APIRouter | None] | None = None
    get_global_router: Callable[[], APIRouter | None] | None = None
    resolve_file_owner_project_id: Callable[[Session, uuid.UUID], uuid.UUID | None] | None = None
    scheduled_jobs: tuple[ModuleScheduledJob, ...] = field(default=())
    org_bundle_hooks: ModuleOrgBundleHooks | None = None
    project_bundle_hooks: ModuleProjectBundleHooks | None = None
    on_org_created: Callable[[Session, uuid.UUID], None] | None = None
    project_nav_visible: Callable[[Session, Project], bool] | None = None
    on_project_created: Callable[[Session, Project, uuid.UUID], None] | None = None
    validate_org_group_member_removal: Callable[[Session, uuid.UUID, uuid.UUID], str | None] | None = None


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
    still lands in the single, reviewed, linear Alembic revision chain
    exactly as before — see `configure_alembic_version_locations` below for
    where its *file* now lives, a Phase 11 follow-up that changed nothing
    about how many chains exist or how reviewed a revision is, only which
    directory it's physically written in; an externally-discovered module's
    own schema changes are applied by `apply_external_module_migrations`
    (below), a materially more restricted mechanism than either — see its
    own docstring for why running SQL against a real database is a
    categorically different risk than importing an inert Python class, and
    is gated accordingly.
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


def configure_alembic_version_locations(cfg: Config) -> None:
    """Points an Alembic `Config` at every registered module's own
    `migrations_dir` (if any), in addition to the core `alembic/versions`
    directory this project has always used — the mechanism `migrations_dir`
    (on `ModuleDefinition`, above) describes, added in a compliance-module-
    plan.md Phase 11 follow-up so a first-party module's own migration file
    can live alongside the rest of that module's code instead of always
    landing in one flat, ever-growing core directory shared by every module.

    Call this on a freshly constructed `Config` — before it is used for
    *any* Alembic operation (`command.upgrade`/`revision`/`history`/etc.) —
    exactly once per `Config` instance. Every caller in this codebase
    (`app.migrations.run_migrations` for the boot-time auto-upgrade;
    `scripts/db.py` for the developer-facing CLI wrapper — see that script's
    own module docstring for why bare `alembic <command>` is no longer this
    project's documented way to touch migrations) goes through this
    function rather than each hand-rolling the same `version_locations`
    string, so a module's own migration directory only ever needs declaring
    once, on its own `ModuleDefinition`, to be picked up everywhere.

    Sets exactly two Alembic config options, both read by `ScriptDirectory.
    from_config` when it is first built (i.e. before any module's own
    `env.py`-level code could set them dynamically — this is why this must
    run against the `Config` object itself, before it is handed to any
    `alembic.command.*` call, not from inside `alembic/env.py`):
    - `version_locations`: the core `alembic/versions` directory, followed
      by every registered module's own `migrations_dir` (skipping `None`),
      each an absolute path so this works regardless of the caller's own
      current working directory.
    - `version_path_separator`: `"os"` — required by Alembic whenever more
      than one location is configured (its own default separator, `" "`,
      cannot disambiguate a path containing a space; `"os"` uses `os.
      pathsep`, this project's own operating convention, matching Alembic's
      documented recommendation for exactly this multi-location case).

    This does **not** recursively scan every file under `app/modules/` —
    only the *specific* directories each module's own `ModuleDefinition`
    names are added. Alembic's revision loader executes (not merely greps)
    every `.py` file it finds in a configured location to read that file's
    own `revision`/`down_revision` module-level assignments, so scanning
    something as broad as the whole `app/modules/` tree would attempt to
    execute this module's own `models.py`/`service.py`/`router.py` etc. as
    if each were a candidate revision script — a real risk, deliberately
    avoided by only ever adding the exact, finite list of directories the
    registry actually declares, the same "explicit, not implicit" principle
    `models_import_path`'s own dotted-path (not directory-scan) design
    already applies one mechanism up.
    """
    core_versions_dir = _BACKEND_DIR / "alembic" / "versions"
    locations = [str(core_versions_dir)]
    for definition in get_module_registry().values():
        if not definition.migrations_dir:
            continue
        locations.append(str(_BACKEND_DIR / definition.migrations_dir))
    cfg.set_main_option("version_locations", os.pathsep.join(locations))
    cfg.set_main_option("version_path_separator", "os")


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
    none, the module itself isn't registered, (Tier B only) its declared
    `frame_url` doesn't resolve to an origin in `Settings.module_frame_
    allowed_origins`, or (Tier C only) it's declared by a first-party
    `INSTALLED_MODULES` entry, which has no legitimate reason to use Tier C
    at all (module system Phase 3, extended with Tier C in a same-system
    follow-up — see `ModuleFrontendManifest`'s own docstring).

    These checks are deliberately mechanical, at the point of use, rather
    than trusted from the module's own declaration — the same "verify,
    don't trust a self-declared field" principle Phase 4 already applies to
    MCP tools' `path_template`/`is_approval_action`. A misconfigured or
    malicious `frame_url` outside the operator's own allowlist is logged
    and treated as "this module has no usable frontend integration," not
    silently rendered — the browser's own `Content-Security-Policy: frame-
    src` (built from the same allowlist, see `app.main`'s security-headers
    middleware) would refuse to load it anyway; this just gives a clear,
    attributable log line and an empty manifest instead of a
    browser-blocked, confusing-to-debug broken iframe. A `"federated"`
    manifest declared on a first-party module is a **config error to catch,
    not a case to support** — logged at `ERROR` (louder than Tier B's
    `WARNING`, since this is an authoring bug in reviewed in-repo code, not
    an environment/deployment misconfiguration) and excluded the same way.

    Args:
        module_key: The module's registry key.

    Returns:
        The module's `ModuleFrontendManifest` if it declares one and (for
        `tier == "remote"`) its origin is allowlisted, or (for `tier ==
        "federated"`) it was discovered via the third-party pipeline rather
        than declared by a first-party module; otherwise `None`.
    """
    definition = get_module(module_key)
    if definition is None or definition.frontend_manifest is None:
        return None
    manifest = definition.frontend_manifest
    if manifest.tier == "installed":
        return manifest

    if manifest.tier == "federated":
        installed_keys = {installed.key for installed in INSTALLED_MODULES}
        if module_key in installed_keys:
            logger.error(
                "First-party module %r declares a Tier C 'federated' frontend_manifest; excluding it. "
                "A first-party module has no reason to use Tier C — it can use Tier A directly, with full "
                "build-time review. Fix this module's own module.py; this is a config error, not a "
                "supported case.",
                module_key,
            )
            return None
        # Unlike Tier B's frame_url, there is no separate allowlist setting
        # to check here — see ModuleFrontendManifest.remote_entry_url's own
        # docstring for why: a "federated" manifest can only ever reach this
        # point at all for a module that already came from the
        # Settings.allow_external_modules-gated discovery pipeline (the
        # check just above), so that existing gate is the whole gate.
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


def resolve_module_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Tries every registered module's `resolve_file_owner_project_id` hook
    (compliance-module-plan.md Phase 8), in registry iteration order,
    returning the first non-`None` project id found — the mechanism
    `app.routers.files.download_file` calls to authorize a module-owned
    file attachment (e.g. Compliance evidence) without that core,
    module-agnostic router importing anything from any specific module.

    A module with no `resolve_file_owner_project_id` of its own (the
    default `None`) is simply skipped, the same as one declaring no
    `mcp_tools`/`roles`. Two modules should never legitimately claim the
    same `file_id` (each module's own file-link table only ever contains
    files it created), so "first match wins" is a defensive tie-break, not
    a meaningful precedence rule.

    Args:
        db: An active database session.
        file_id: The `FileAsset` id being resolved.

    Returns:
        The owning project's id, or `None` if no registered module's hook
        recognises this file.
    """
    for definition in get_module_registry().values():
        if definition.resolve_file_owner_project_id is None:
            continue
        project_id = definition.resolve_file_owner_project_id(db, file_id)
        if project_id is not None:
            return project_id
    return None


def run_on_org_created_hooks(db: Session, organization_id: uuid.UUID) -> None:
    """Calls every registered module's `on_org_created` hook (module
    boundary cleanup, 2026-09-08), in registry iteration order, right after
    a brand-new `Organization` row is flushed — the mechanism
    `app.routers.orgs.create_organization` and `app.services.bootstrap.
    run_bootstrap` both call instead of importing a specific module (e.g.
    Compliance's `seed_compliance_action_types`) to seed its own org-scoped
    defaults, mirroring `resolve_module_file_project_id`'s identical
    "core code shouldn't need to know a specific module exists" reasoning.

    A module with no `on_org_created` of its own (the default `None`) is
    simply skipped. Does not commit — each hook only adds rows, the same
    convention `seed_project_statuses`/`seed_link_types` already follow;
    the caller commits once for the whole org-creation transaction.

    Args:
        db: An active database session, mid-transaction (the new
            `Organization` row must already be flushed so hooks can
            reference its id via foreign keys).
        organization_id: The newly created organisation's id.
    """
    for definition in get_module_registry().values():
        if definition.on_org_created is None:
            continue
        definition.on_org_created(db, organization_id)


def run_on_project_created_hooks(db: Session, project: Project, actor_id: uuid.UUID) -> None:
    """Calls every registered module's `on_project_created` hook
    (docs/compliance-module-plan.md Phase 20), in registry iteration order,
    right after a brand-new `Project` row is flushed — `app.routers.
    projects.create_project` calls this instead of importing a specific
    module (e.g. Compliance's `reconcile_new_project_for_all_standards`) to
    react to a new project, mirroring `run_on_org_created_hooks`'s identical
    "core code shouldn't need to know a specific module exists" reasoning
    one lifecycle event later.

    A module with no `on_project_created` of its own (the default `None`)
    is simply skipped. Does not commit — each hook only adds/modifies rows,
    the same convention `run_on_org_created_hooks` already follows; the
    caller commits once for the whole project-creation transaction.

    Args:
        db: An active database session, mid-transaction (the new `Project`
            row must already be flushed so hooks can reference its id and
            read its own fields, e.g. `organization_id`).
        project: The newly created project.
        actor_id: The user who created the project — attributed on any row
            a hook creates as a result (a real human action).
    """
    for definition in get_module_registry().values():
        if definition.on_project_created is None:
            continue
        definition.on_project_created(db, project, actor_id)


def run_org_group_member_removal_hooks(db: Session, org_group_id: uuid.UUID, member_user_id: uuid.UUID) -> str | None:
    """Calls every registered module's `validate_org_group_member_removal`
    hook (docs/compliance-module-plan.md Phase 22), in registry iteration
    order, stopping at the first one that returns a block message —
    `app.routers.orgs.remove_org_group_member` calls this instead of
    importing a specific module (e.g. Compliance's own fallback-group floor
    check) to decide whether removing a *user* member from an `OrgGroup`
    would break some module-owned invariant, mirroring `run_on_org_created_
    hooks`'s identical "core code shouldn't need to know a specific module
    exists" reasoning.

    A module with no `validate_org_group_member_removal` of its own (the
    default `None`) is simply skipped. Read-only — never mutates or
    commits.

    Args:
        db: An active database session.
        org_group_id: The group a member is about to be removed from.
        member_user_id: The user being removed (never a nested-group
            member — the caller only invokes this for a genuine user
            removal, see that endpoint's own docstring).

    Returns:
        The first non-`None` block message from any module's hook, or
        `None` if every module allows the removal.
    """
    for definition in get_module_registry().values():
        if definition.validate_org_group_member_removal is None:
            continue
        message = definition.validate_org_group_member_removal(db, org_group_id, member_user_id)
        if message is not None:
            return message
    return None


def get_all_module_scheduled_jobs() -> list[tuple[str, ModuleScheduledJob]]:
    """Every registered module's declared `scheduled_jobs` (compliance-
    module-plan.md Phase 10), each paired with its declaring module's own
    `key` — what `app.services.scheduler.start_scheduler` iterates to
    register module-contributed APScheduler jobs generically, alongside its
    own two core jobs. A module with no `scheduled_jobs` of its own (the
    default empty tuple) simply contributes nothing.

    Returns:
        A list of `(module_key, job)` pairs, in registry iteration order.
    """
    jobs: list[tuple[str, ModuleScheduledJob]] = []
    for definition in get_module_registry().values():
        for job in definition.scheduled_jobs:
            jobs.append((definition.key, job))
    return jobs


def get_all_module_org_bundle_hooks() -> list[tuple[str, ModuleOrgBundleHooks]]:
    """Every registered module's declared `org_bundle_hooks`, each paired
    with its declaring module's own `key` — what `app.services.org_export`
    iterates to fold module-contributed content into an organisation bundle
    export/import generically, without importing any specific module
    directly. A module with no `org_bundle_hooks` of its own (the default
    `None`) simply contributes nothing.

    Returns:
        A list of `(module_key, hooks)` pairs, in registry iteration order.
    """
    hooks: list[tuple[str, ModuleOrgBundleHooks]] = []
    for definition in get_module_registry().values():
        if definition.org_bundle_hooks is not None:
            hooks.append((definition.key, definition.org_bundle_hooks))
    return hooks


def get_all_module_project_bundle_hooks() -> list[tuple[str, ModuleProjectBundleHooks]]:
    """Every registered module's declared `project_bundle_hooks`, each
    paired with its declaring module's own `key` — `app.services.
    project_export`'s equivalent of `get_all_module_org_bundle_hooks`
    above. A module with no `project_bundle_hooks` of its own (the default
    `None`) simply contributes nothing.

    Returns:
        A list of `(module_key, hooks)` pairs, in registry iteration order.
    """
    hooks: list[tuple[str, ModuleProjectBundleHooks]] = []
    for definition in get_module_registry().values():
        if definition.project_bundle_hooks is not None:
            hooks.append((definition.key, definition.project_bundle_hooks))
    return hooks


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
