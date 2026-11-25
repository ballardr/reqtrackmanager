"""
Module: modules.registry

Builds and serves the merged module registry: which modules exist, read by
`app.main` (router mounting), `app.services.rbac` and the admin endpoints.
Sources in priority order (an earlier `key` wins): `INSTALLED_MODULES`, then
`reqtrackmanager.modules` entry points and `Settings.extra_modules_path`; the
last two load only when `Settings.allow_external_modules` is true (SOC 2 CC6.8).
Each module's router applies its own enablement checks.
"""

from __future__ import annotations

import contextvars
import functools
import importlib.metadata
import importlib.util
import logging
import os
import re
import uuid
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import get_settings
from app.models.enums import LinkFlow, LinkNestingScope
from app.modules.seams import (
    BaselineCheckProvider,
    GovernanceSeam,
    ModuleAdministrativePermission,
    PolicyResolver,
    ProfileContributor,
    RecordSubtypeResolver,
    ReviewAdapter,
)

if TYPE_CHECKING:
    from alembic.config import Config
    from app.models.file import FileAsset
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.user import User
    from app.services.bundle_common import BundleImportWarnings, UserResolver
    from app.services.report_framework import ReportContext, ReportResult

logger = logging.getLogger(__name__)

# `backend/`: the migration-tooling root (as `app.migrations._BACKEND_DIR`); a
# module's declared `migrations_dir` is relative to it, whatever the working directory.
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

ENTRY_POINT_GROUP = "reqtrackmanager.modules"

# Module availability is resolved in tiers, each a small query. A read-only caller
# resolving it for many projects opts in to `memoize_module_state()` so each tier
# is read once; outside that block nothing is cached.
_module_state_memo: contextvars.ContextVar[dict | None] = contextvars.ContextVar("module_state_memo", default=None)


def module_state_memo() -> dict | None:
    """The active `memoize_module_state()` block's cache, or `None` outside one. Read-only code that wants to keep a
    bulk-loaded answer for the rest of an export (the tags or attachments of every record of a type) stores it here."""
    return _module_state_memo.get()


def scoped_memo(fn: Callable) -> Callable:
    """Memoises `fn(db, *args)` while `memoize_module_state()` is active (keyed by its arguments after `db`).

    Use only on a pure read of module or project state. Without an active block it calls straight through.
    """

    @functools.wraps(fn)
    def wrapper(db, *args, **kwargs):
        memo = _module_state_memo.get()
        if memo is None:
            return fn(db, *args, **kwargs)
        key = (fn.__name__, args, tuple(sorted(kwargs.items())))
        if key not in memo:
            memo[key] = fn(db, *args, **kwargs)
        return memo[key]

    return wrapper


@contextmanager
def memoize_module_state() -> Iterator[None]:
    """Caches module-availability lookups for the duration of the block. Use only around read-only code:
    nothing inside may change module, entitlement or project settings and then rely on re-reading them."""
    token = _module_state_memo.set({})
    try:
        yield
    finally:
        _module_state_memo.reset(token)


def prefetch_project_module_state(db: Session, project_ids: Collection[uuid.UUID]) -> None:
    """Loads, in three queries, the per-project lookups `is_module_enabled_for_project` and
    `is_module_subcomponent_enabled` make for each of `project_ids` (the owning organisation and the project's
    own module and sub-component overrides). A no-op outside `memoize_module_state()`.

    Args:
        db: Active session (read only).
        project_ids: The projects about to be resolved.
    """
    memo = _module_state_memo.get()
    ids = set(project_ids)
    if memo is None or not ids:
        return
    from app.models.module import ProjectModuleEnablement, ProjectModuleSubComponentEnablement
    from app.models.project import Project

    for project_id, organization_id in db.execute(select(Project.id, Project.organization_id).where(Project.id.in_(ids))).all():
        memo[("_project_organization_id", (project_id,), ())] = organization_id
    module_rows = {
        (row.project_id, row.module_key): row
        for row in db.scalars(select(ProjectModuleEnablement).where(ProjectModuleEnablement.project_id.in_(ids)))
    }
    sub_rows = {
        (row.project_id, row.module_key, row.subcomponent_key): row
        for row in db.scalars(select(ProjectModuleSubComponentEnablement).where(ProjectModuleSubComponentEnablement.project_id.in_(ids)))
    }
    for definition in get_module_registry().values():
        for project_id in ids:
            memo[("_project_module_override", (project_id, definition.key), ())] = module_rows.get((project_id, definition.key))
            for sub in definition.sub_components:
                memo[("_project_subcomponent_override", (project_id, definition.key, sub.key), ())] = sub_rows.get(
                    (project_id, definition.key, sub.key)
                )


@dataclass(frozen=True)
class ModuleRoleDefinition:
    """Declares one module-contributed RBAC role, a module's analogue of an
    `OrgRole`/`ProjectRole` member that extends neither enum. At startup
    `sync_module_role_definitions` mirrors the live set into
    `module_role_definitions` so a grant's display name stays resolvable if the
    module is unregistered; at request time `require_module_role` reads `scope`
    from the in-process registry.

    Attributes:
        role_key: Stable identifier, unique within its module (e.g.
            `"compliance_manager"`); the `role_key` column value in
            `UserModuleRole`/`ModuleRoleDefinitionRow`, so it never changes
            once grants are keyed on it.
        name: Display name shown in admin UIs (API data, not a frontend label map).
        description: Short description shown beside `name`.
        scope: `"org"` (granted with `project_id`/`scope_entity_id` `NULL`) or
            `"project"` (granted with a `project_id`); `require_module_role`
            composes each with `OrgRole.ORG_ADMIN` or
            `ProjectRole.PROJECT_MANAGER`, and the "available module roles"
            endpoints list them. Any other string is a module-owned entity scope
            (e.g. `"standard"`, one role per `ComplianceStandard`) tied to one
            row of an entity the module owns; it must set
            `resolve_entity_organization_id`, since no path parameter named
            after an arbitrary scope exists to bind an organisation from.
        overridden_by: Further `(scope, role_key)` pairs of this same module
            whose grant also satisfies a check for this role (an org-wide
            `compliance_manager` needs no per-standard grant). Checked in
            addition to the core `is_server_admin`, `OrgRole.ORG_ADMIN` and
            `ProjectRole.PROJECT_MANAGER` overrides. Empty by default.
        resolve_entity_organization_id: Required for a scope other than
            `"org"`/`"project"`: resolves the entity id (read from the path
            parameter `f"{scope}_id"`) to its organisation id, or `None` if
            absent (surfaced as 404, like every module-gated dependency).
        permissions: Fine-Grained Access Control permission-atom strings
            (`app.services.permissions.encode_permission`, e.g.
            `"decision:approve_baseline:"`, or a bare key such as
            `"grant_roles"`) a holder additionally gets, unioned with direct and
            group `CustomRoleDefinition` grants in
            `app.services.rbac.get_effective_permissions`. Empty by default.
    """

    role_key: str
    name: str
    description: str
    scope: str
    overridden_by: tuple[tuple[str, str], ...] = ()
    resolve_entity_organization_id: Callable[[Session, uuid.UUID], uuid.UUID | None] | None = None
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityScopeDefinition:
    """Declares one module-owned entity scope as centrally discoverable, so code
    outside `require_module_role` can resolve an arbitrary
    `(scope_kind, entity_id)` pair. `CustomRoleDefinition.scope` and the
    `entity_scope` parameter of `app.services.rbac.get_effective_permissions`/
    `require_permission` resolve against `get_all_registered_entity_scopes()`.
    A module registers the same resolver here and in
    `ModuleRoleDefinition.resolve_entity_organization_id`, which
    `require_module_role` keeps reading directly.

    Attributes:
        resolve_organization_id: Same contract as
            `ModuleRoleDefinition.resolve_entity_organization_id`: one entity's
            id to its owning organisation's id, or `None` if it does not exist.
        label: Display name of the scope kind (e.g. "Standard"), shown in the
            Role Management scope and entity pickers.
        list_entities: Every entity of this kind in an organisation, as
            `(id, display_name)` pairs, powering the entity picker generically.
    """

    resolve_organization_id: Callable[[Session, uuid.UUID], uuid.UUID | None]
    label: str
    list_entities: Callable[[Session, uuid.UUID], list[tuple[uuid.UUID, str]]]


@dataclass(frozen=True)
class ModuleSubComponentDefinition:
    """Declares one independently toggleable sub-component of a module. A
    module declares a tuple of these on `ModuleDefinition.sub_components`
    instead of a core file keeping a per-module list.
    `is_module_subcomponent_enabled`/`is_org_module_subcomponent_enabled`
    resolve a `(module_key, subcomponent_key)` pair: project override, then
    organisation default, then `default_enabled`.

    Attributes:
        key: Stable identifier, unique within its module; it is the
            `subcomponent_key` column value in the enablement tables, so it
            never changes once rows are keyed on it.
        name: Display name shown in admin UIs.
        default_enabled: Whether a project or organisation with no override row
            has it enabled.
        organization_only: The sub-component belongs to the organisation, so
            projects get no switch, the project API rejects a write for it and
            `is_module_subcomponent_enabled` returns the organisation's state.
        artefact_types: The artefact types this sub-component serves when its
            key is not the type's name (it may serve several, e.g. a diagram
            and its states). A key equal to a type name serves it implicitly.
            Core reads of a record (link graph, tags, search, record tables,
            overview) treat a type as switched off when its sub-component is.
        requires: Keys of other sub-components of the same module this one needs. While any of them is not in effect
            (switched off, or itself waiting on one that is) this one is not in effect either, at every tier, and
            its own switch and stored rows are kept. The settings lists name what it is waiting on.
            `ModuleDefinition` rejects an unknown key, a reference to itself and a cycle.
    """

    key: str
    name: str
    default_enabled: bool = True
    organization_only: bool = False
    artefact_types: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleNavEntry:
    """One additional nav-rail entry a Tier A ("installed") module contributes
    beyond the manifest's primary `nav_label`/`nav_path` pair, so a module
    needing several top-level entries (Context & Strategy has five) needs no
    module-specific code in `Layout.tsx`. `all_nav_entries` returns the
    full, ordered list.

    Tier A only: `__post_init__` rejects a non-empty `additional_nav_entries`
    on any other tier, because Tier B mounts one iframe at one `frame_url` and
    Tier C loads one federated remote.

    Attributes:
        nav_label: Display label for this nav-rail entry.
        nav_path: The frontend route path, with the same `"{project_id}"`
            placeholder convention as `ModuleFrontendManifest.nav_path`.
        nav_icon: Icon name resolved client-side by
            `frontend/src/modules/navIcons.ts`; defaults to `"puzzle"`.
        sub_component: Key of the `ModuleDefinition.sub_components` entry this
            entry leads to, or `None` for the module as a whole. The nav rail
            hides the entry while that sub-component is disabled for the project.
        sub_components_any: For one page serving several sub-components: the
            entry is hidden only while every listed key is disabled. Combined
            with `sub_component` it needs both conditions.
    """

    nav_label: str
    nav_path: str
    nav_icon: str = "puzzle"
    sub_component: str | None = None
    sub_components_any: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleFrontendManifest:
    """Declares a module's frontend integration in one of three tiers
    (`docs/modules.md`, "Tier C").

    Attributes:
        tier: `"installed"` (Tier A): route components and nav entry compiled
            into the frontend bundle and registered in
            `frontend/src/modules/registry.ts`, so this manifest carries only
            nav metadata. `"remote"` (Tier B): a sandboxed `<ModuleFrame>`
            iframe at `frame_url`, with the Host UI Bridge over `postMessage`.
            `"federated"` (Tier C): a Module Federation remote built outside
            this repo and `import()`-ed at runtime, sharing the host's origin,
            DOM, cookies and React instances (no sandbox, no build-time
            review). Tier C is produced only by modules from the third-party
            discovery pipeline (`Settings.allow_external_modules`);
            `get_frontend_manifest` logs an error and excludes a first-party
            one. Trust rests with the operator, as for any external module
            (`docs/soc2/policies/vendor-and-subprocessor-management-policy.md`).
        nav_label: Display label of the module's nav-rail entry.
        nav_path: The route the nav entry links to (e.g.
            `"/projects/{project_id}/modules/compliance"`). For `"remote"` it
            is where the host mounts `<ModuleFrame>`; otherwise it matches the
            module's own route registration.
        frame_url: Tier B only: the origin and path the iframe loads. Its
            origin must be in `Settings.module_frame_allowed_origins`, or
            `get_frontend_manifest` logs a warning and returns `None`. `None`
            for other tiers.
        remote_entry_url: Tier C only: the remote's Module Federation entry
            script (a same-origin nginx path such as
            `"/external-modules/my-module/remoteEntry.js"`, or an absolute
            URL). Not allowlist-checked: a federated manifest only exists for a
            module that passed the gated discovery pipeline, which is the gate
            (see `Settings.allow_external_modules`). `None` for other tiers.
        exposed_module: Tier C only: the exposed module name the remote
            publishes (e.g. `"./Module"`). `None` for other tiers.
        additional_nav_entries: Further `ModuleNavEntry` rows beyond the primary
            pair; Tier A only (`__post_init__` rejects them elsewhere).
            `all_nav_entries()` returns the full list, primary first.
        nav_icon: Icon name of the primary entry (`ModuleNavEntry.nav_icon`);
            defaults to `"puzzle"`.
        nav_sub_component: `ModuleNavEntry.sub_component` for the primary entry.
        nav_sub_components_any: `ModuleNavEntry.sub_components_any` for the primary entry.
    """

    tier: Literal["installed", "remote", "federated"]
    nav_label: str
    nav_path: str
    frame_url: str | None = None
    remote_entry_url: str | None = None
    exposed_module: str | None = None
    additional_nav_entries: tuple[ModuleNavEntry, ...] = ()
    nav_icon: str = "puzzle"
    nav_sub_component: str | None = None
    nav_sub_components_any: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.tier == "remote":
            if not self.frame_url:
                raise ValueError("ModuleFrontendManifest: tier 'remote' requires frame_url.")
            if self.remote_entry_url or self.exposed_module:
                raise ValueError(
                    "ModuleFrontendManifest: tier 'remote' must not set remote_entry_url/exposed_module "
                    "(those are Tier C 'federated'-only fields)."
                )
            if self.additional_nav_entries:
                raise ValueError(
                    "ModuleFrontendManifest: tier 'remote' must not set additional_nav_entries — a Tier B "
                    "module mounts exactly one <ModuleFrame> iframe at one frame_url."
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
            if self.additional_nav_entries:
                raise ValueError(
                    "ModuleFrontendManifest: tier 'federated' must not set additional_nav_entries — a Tier C "
                    "module loads exactly one Module Federation remote at one remote_entry_url/exposed_module."
                )

    def all_nav_entries(self) -> tuple[ModuleNavEntry, ...]:
        """This manifest's full, order-preserving list of nav-rail entries —
        its own primary `nav_label`/`nav_path` pair, followed by every
        `additional_nav_entries` row (empty for a module with a single nav entry). The one place that combines the
        two so a consumer never needs to special-case "the first entry comes
        from different fields than the rest."
        """
        return (
            ModuleNavEntry(
                nav_label=self.nav_label, nav_path=self.nav_path, nav_icon=self.nav_icon,
                sub_component=self.nav_sub_component, sub_components_any=self.nav_sub_components_any,
            ),
            *self.additional_nav_entries,
        )


@dataclass(frozen=True)
class McpToolDefinition:
    """Declares one module-contributed `mcp-server/` tool (see docs/modules.md,
    "Module-contributed MCP tools"). `build_mcp_tool_manifest` re-derives or
    verifies every security-relevant part instead of trusting the declaration.

    Attributes:
        name: A short local name (e.g. `"list_standards"`); the manifest always
            prefixes it with the module key, so tools never collide.
        description: Shown to the calling AI assistant as the tool description.
        method: The HTTP method of the proxied endpoint; `mutates` (`GET` ->
            `False`, else `True`) is derived from it, never declared.
        path_template: The backend path proxied, e.g.
            `"/api/v1/orgs/{organization_id}/modules/compliance/standards/{standard_id}"`.
            It must fall inside one of the module's router prefixes and name a
            real route with a matching `method`, or the tool is excluded
            (logged). It must name an explicit `{organization_id}` or
            `{project_id}`: there is no implicit current organisation.
        params: One dict per parameter: `{"name", "type", "required", "in":
            "path" | "query" | "body", "description"}` (`description` may be
            omitted). `type` is a JSON-Schema display hint, not a security
            boundary; the proxied endpoint validates. A malformed entry
            excludes only that parameter (logged).
    """

    name: str
    description: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path_template: str
    params: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedMcpTool:
    """One module-contributed MCP tool that has survived `build_mcp_tool_
    manifest`'s mechanical verification
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
class OrgCreationChoiceOption:
    """Declares one optional, module-contributed seeding choice offered when an
    organisation is created, so `routers.orgs.create_organization` and its
    listing endpoint hardcode no module's choices. `get_org_creation_choices`
    merges every module's tuple in registry order;
    `default_org_creation_choice_keys` returns the `default_selected` subset.

    Attributes:
        key: Stable identifier, unique across modules (convention
            `f"{module_key}:{short_name}"`, e.g. `"decisions:adr_madr"`); passed
            in `POST /orgs`'s `module_choice_keys` and to
            `ModuleDefinition.on_org_created_with_choices`.
        group_label: Heading the form groups this option under; options sharing
            a label share one heading, in first-seen order.
        label: Display label of this option.
        description: One-line explanation shown under the label.
        default_selected: Whether the option is pre-checked and included when a
            caller passes no `module_choice_keys` (see `run_on_org_created_hooks`).
    """

    key: str
    group_label: str
    label: str
    description: str
    default_selected: bool = True


@dataclass(frozen=True)
class ModuleScheduledJob:
    """Declares one date-driven background sweep a module runs periodically
    (e.g. Compliance's evidence-expiry and review-due sweeps).
    `app.services.scheduler.start_scheduler` registers every module's jobs, so
    scheduled processing needs no core edit.

    Attributes:
        job_id: Short module-unique identifier; `start_scheduler` prefixes it
            with the module's `key` for APScheduler, so ids never collide.
        hour / minute: When the job runs, in the container's local time. Stagger
            against existing jobs to avoid a load spike (not enforced).
        run: A callable taking one open `Session` and performing the sweep, as
            `services.reviews.send_due_review_reminders` does;
            `start_scheduler` opens and closes the session.
    """

    job_id: str
    hour: int
    minute: int
    run: Callable[[Session], None]


@dataclass(frozen=True)
class ModuleOrgBundleHooks:
    """Declares a module's contribution to `app.services.org_export`'s
    organisation export/import bundle, so `org_export.py` imports no module. A
    module with no organisation-level bundle content leaves
    `ModuleDefinition.org_bundle_hooks` as `None`.

    Attributes:
        export: `(db, org) -> dict`: the module's organisation-scoped content as
            JSON-serialisable data under keys it chooses, merged into
            `org_export.build_org_bundle`'s `org_json`.
        import_: `(db, org, data, users, warnings, resolutions) -> None`: writes
            the module's content from the bundle's `data` into `org`, resolving
            users through `users` (`bundle_common.UserResolver`) and recording
            skipped items in `warnings`. Called by `import_org_bundle` (fresh
            organisation, `resolutions=None`) and `merge_org_bundle` (existing
            organisation, `resolutions` a conflict-id -> value map).
        compute_merge_conflicts: Optional `(db, target_org, data) -> list[dict]`
            of the module's name/reference conflicts (`{"id", "kind", "name",
            "existing_id"}`), added to `org_export._compute_merge_conflicts`.
            `None` when the content is purely additive on merge.
        merge_resolution_choices: `{kind: {allowed resolution values}}` for each
            conflict `kind` it can report, merged into the merge validation.
        summarize_merge: Optional `(data, conflicts, resolutions) -> dict[str, int]`
            of named counts merged into the merge summary.
        export_files: Optional `(db, org, assets) -> dict` for a module whose
            organisation content includes files (the Architecture symbol
            library): returns more `org.json` sections and adds each referenced
            `FileAsset` to `assets` so the bundle embeds its bytes. `export` is
            still called.
        import_files: Optional `(db, org, data, file_bytes_by_ref, acting_user,
            warnings) -> None`, called just before `import_` with the embedded
            bytes (keyed by `file_ref`). It treats every file it stores as
            untrusted input.
        export_with_projects: Optional `(db, org, project_ref_by_id) -> dict` for
            content that names the organisation's projects (a profile's targets
            and exemptions): `project_ref_by_id` maps each project id to the
            bundle's portable reference (`P-1`), and the returned sections are
            merged into `org_json` after `export`.
        import_with_projects: Optional `(db, org, data, project_id_by_ref, users,
            warnings, resolutions) -> None`, called after every project of the
            bundle has been imported, with the new project id of each bundle
            reference (a project skipped by a merge is absent). `resolutions` is
            `None` for a fresh organisation and a conflict-id -> value map for a
            merge, so a hook can tell the two apart.
    """

    export: Callable[[Session, Organization], dict[str, Any]]
    import_: Callable[
        [Session, Organization, dict[str, Any], UserResolver, BundleImportWarnings, dict[str, str] | None], None
    ]
    compute_merge_conflicts: Callable[[Session, Organization, dict[str, Any]], list[dict[str, Any]]] | None = None
    merge_resolution_choices: Mapping[str, frozenset[str]] = field(default_factory=dict)
    summarize_merge: Callable[[dict[str, Any], list[dict[str, Any]], dict[str, str]], dict[str, int]] | None = None
    export_files: Callable[[Session, Organization, dict[uuid.UUID, FileAsset]], dict[str, Any]] | None = None
    import_files: Callable[[Session, Organization, dict[str, Any], dict[str, bytes], User, BundleImportWarnings], None] | None = None
    export_with_projects: Callable[[Session, Organization, Mapping[uuid.UUID, str]], dict[str, Any]] | None = None
    import_with_projects: (
        Callable[
            [Session, Organization, dict[str, Any], Mapping[str, uuid.UUID], UserResolver, BundleImportWarnings, dict[str, str] | None],
            None,
        ]
        | None
    ) = None


@dataclass(frozen=True)
class ModuleProjectBundleHooks:
    """Declares a module's contribution to `app.services.project_export`'s
    project export/import bundle, the project-scoped counterpart of
    `ModuleOrgBundleHooks`.

    Attributes:
        export: `(db, project) -> (dict, {file_id: FileAsset})`: the module's
            project-scoped content and the files it references, in the shape of
            `project_export.collect_project_data`, which merges them.
        import_: `(db, project, data, file_bytes_by_ref, current_user, users,
            warnings) -> None`: writes the module's content from the bundle's
            `data` into `project`, resolving file bytes and users
            (`bundle_common.UserResolver`); called from
            `project_export.apply_project_data` after the core sections.
        import_late: Optional callable with `import_`'s signature, run after
            every module's `import_`, for content referring to another module's
            records that do not exist yet (per-persona Pain Point scores refer
            to Personas). `None` when `import_` suffices.
        template_configuration_keys: `export` keys that are project configuration
            (vocabularies, hidden organisation defaults, scoring definitions,
            settings), copied unchanged when a project is created from a template.
        template_record_keys: `export` keys holding starter records and their
            links, copied after `template_reset` returns them to a starting state.
        template_excluded: `{export key: reason}` for keys a template never
            copies. Every exported key is in exactly one of the three sets; a
            test fails otherwise.
        template_reset: Called on the filtered export before import: resets the
            starter records in place to fresh drafts (initial status, no
            archive, review, vote or history). `None` without record keys.
    """

    export: Callable[[Session, Project], tuple[dict[str, Any], dict[uuid.UUID, FileAsset]]]
    import_: Callable[
        [Session, Project, dict[str, Any], dict[str, bytes], User, UserResolver, BundleImportWarnings], None
    ]
    import_late: (
        Callable[[Session, Project, dict[str, Any], dict[str, bytes], User, UserResolver, BundleImportWarnings], None] | None
    ) = None
    template_configuration_keys: frozenset[str] = frozenset()
    template_record_keys: frozenset[str] = frozenset()
    template_excluded: Mapping[str, str] = field(default_factory=dict)
    template_reset: Callable[[dict[str, Any]], None] | None = None


#: `openapi_extra` key marking a route as an approval/decision-type action;
#: `build_mcp_tool_manifest` excludes any tool resolving to such a route,
#: whatever the module's declaration claims.
APPROVAL_ACTION_EXTRA_KEY = "x-approval-action"
APPROVAL_ACTION_ROUTE_EXTRA: dict = {APPROVAL_ACTION_EXTRA_KEY: True}

_VALID_MCP_TOOL_PARAM_LOCATIONS = {"path", "query", "body"}


def build_mcp_tool_manifest() -> list[ResolvedMcpTool]:
    """Builds the verified manifest of every module-contributed MCP tool across
    the live registry: the list `GET /api/v1/system/modules/mcp-tools` returns
    and all `mcp-server` sees of a module's `mcp_tools`.

    Nothing about a tool's safety is trusted from its declaration:
    - The registered name is the module `key`, an underscore and the local name,
      so a module cannot claim another's or core's tool name.
    - `path_template` must fall inside one of the module's own router prefixes
      (`get_router()`, `get_project_router()`, `get_global_router()`) and name a
      real route on that router with a matching `method`; otherwise the tool is
      excluded (logged).
    - `mutates` is derived from `method` (`GET` -> `False`, else `True`).
    - Whether the route is an approval/decision-type action is read from the
      route's own `openapi_extra` (`APPROVAL_ACTION_EXTRA_KEY`); such tools are
      excluded entirely.

    The guarantee is mechanical for first-party endpoints. For an external
    module's own endpoints it reduces to the trust the operator grants by
    setting `Settings.allow_external_modules`.

    Returns:
        Every `ResolvedMcpTool` that passed verification, in registry then
        declaration order.
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
            for router_route in r.routes:
                path = getattr(router_route, "path", None)
                methods = getattr(router_route, "methods", None) or ()
                if path is None:
                    continue
                for method in methods:
                    routes_by_path_and_method[(path, method.upper())] = router_route

        # A report that failed registry validation (unknown sub-component or role) answers 404 and is
        # not catalogued; its generated MCP tool (`report_mcp_tools`) must not be offered either.
        invalid_report_paths = {
            f"/reports/{r.slug}" for r in definition.reports
        } - {f"/reports/{r.slug}" for r in get_module_reports(definition.key)}

        for tool in definition.mcp_tools:
            full_name = f"{definition.key}_{tool.name}"
            declared_method = tool.method.upper()

            if any(tool.path_template.endswith(path) for path in invalid_report_paths):
                logger.warning(
                    "Module %r's MCP tool %r targets a report that failed validation; excluding",
                    definition.key, tool.name,
                )
                continue

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


# --- Scoring schemes (generic scoring-matrix core) -----

# The fixed design-system palette a rating band may be coloured with — the
# same tone vocabulary as the frontend's `.badge--*` modifiers, not a
# per-module list, so no module ever needs an entry added here.
SCORING_BAND_TONES: frozenset[str] = frozenset({"muted", "info", "accent", "warning", "danger"})
_SCORING_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_SCORING_BANDS = 10


def validate_scoring_bands(bands: list[tuple[str, float, str]]) -> None:
    """Validates one rating-band set (shared by registry defaults and the
    org/project band-override endpoints, so both obey the same rules).

    Args:
        bands: `(label, min_score, tone)` triples in ascending order.
            `min_score` is a *normalised* threshold (score ÷ the model's
            maximum possible score), so bands survive an org re-weighting
            its levels.

    Raises:
        ValueError: If the set is empty or longer than `MAX_SCORING_BANDS`,
            the first threshold isn't 0, thresholds aren't strictly
            increasing within [0, 1), a label is blank/duplicated, or a
            tone isn't in `SCORING_BAND_TONES`.
    """
    if not bands or len(bands) > MAX_SCORING_BANDS:
        raise ValueError(f"A band set needs between 1 and {MAX_SCORING_BANDS} bands.")
    if bands[0][1] != 0:
        raise ValueError("The first band must start at 0.")
    labels: set[str] = set()
    previous = -1.0
    for label, min_score, tone in bands:
        if not label.strip():
            raise ValueError("Band labels must not be blank.")
        if label.strip().lower() in labels:
            raise ValueError(f"Duplicate band label '{label}'.")
        labels.add(label.strip().lower())
        if not 0 <= min_score < 1 or min_score <= previous:
            raise ValueError("Band thresholds must be strictly increasing and within [0, 1).")
        previous = min_score
        if tone not in SCORING_BAND_TONES:
            raise ValueError(f"Unknown band tone '{tone}'.")


def validate_scoring_model_maths(model: ScoringModelDefinition) -> None:
    """Checks how a model combines its axes.

    Raises:
        ValueError: For an unknown combination; a product model with an exponent that is not in (0, 10] or names
            an axis the model does not use, or with weighted-sum settings; a weighted-sum model with exponents,
            an importance missing for an axis or naming another, a non-positive importance, a total other than
            100, or an inverted axis it does not sum.
    """
    used = {*model.axis_keys, *model.divisor_axis_keys}
    if model.combination == "product":
        if model.importance or model.inverted_axis_keys:
            raise ValueError(f"Model '{model.key}' is a product, so it takes no importance or inverted axes.")
        for axis_key, exponent in model.exponents:
            if axis_key not in used or not 0 < exponent <= 10:
                raise ValueError(f"Model '{model.key}': exponent for '{axis_key}' must be in (0, 10] on a used axis.")
        if len({axis_key for axis_key, _ in model.exponents}) != len(model.exponents):
            raise ValueError(f"Model '{model.key}' lists an exponent twice.")
    elif model.combination == "weighted_sum":
        if model.exponents:
            raise ValueError(f"Model '{model.key}' is a weighted sum, so it takes no exponents.")
        percentages = dict(model.importance)
        if set(percentages) != set(model.axis_keys) or len(percentages) != len(model.importance):
            raise ValueError(f"Model '{model.key}' needs one importance for each summed axis.")
        if any(p <= 0 for p in percentages.values()) or abs(sum(percentages.values()) - 100) > 0.01:
            raise ValueError(f"Model '{model.key}' importance must be positive and total 100%.")
        if not set(model.inverted_axis_keys) <= set(model.axis_keys):
            raise ValueError(f"Model '{model.key}' can only invert an axis it sums.")
    else:
        raise ValueError(f"Model '{model.key}' has an unknown combination '{model.combination}'.")


@dataclass(frozen=True)
class ScoringLevelDefault:
    """One seeded level of a scoring axis (e.g. Severity "Blocker", weight 5).

    Attributes:
        name: Display name, unique within the axis.
        weight: Positive numeric weight, unique within the axis; levels are
            always ordered by weight, so the highest weight is the axis's
            top level.
        description: Optional guidance shown beside the level when scoring.
        threshold: Only on a derived axis (`ScoringAxisDefinition.derived_source`): the lowest derived value that
            falls in this level. The levels' thresholds are unique.
    """

    name: str
    weight: float
    description: str = ""
    threshold: float | None = None


@dataclass(frozen=True)
class ScoringAxisDefinition:
    """One scoring input (e.g. Severity) a module registers.

    Attributes:
        key: Stable machine key, unique within its scheme.
        label: Display label.
        description: Optional guidance for scorers.
        default_levels: Levels seeded into every organisation (at least 2).
        derived_source: Names the module-computed number this axis is read from (e.g. a weighted demand) instead
            of being chosen manually; core only stores the name. Each level then has a `threshold`, and the level
            for a value is the one with the highest threshold not above it (the lowest level takes anything below). A scorer may still pick a level by
            hand, which then wins. `None` = an ordinary, manually chosen axis.
        per_target: Only on a scheme with targets (`ScoringSchemeDefinition.target_label`): whether the axis is
            scored separately for each target (a persona) rather than once for the whole record. A per-target
            axis scored for the whole record is the default for the targets that are not scored individually.
    """

    key: str
    label: str
    default_levels: tuple[ScoringLevelDefault, ...]
    description: str = ""
    derived_source: str | None = None
    per_target: bool = False


@dataclass(frozen=True)
class ScoringBandDefault:
    """One default rating band (e.g. "High" from normalised score 0.5).

    Attributes:
        label: Display label.
        min_score: Normalised lower bound in [0, 1).
        tone: One of `SCORING_BAND_TONES`.
    """

    label: str
    min_score: float
    tone: str


@dataclass(frozen=True)
class ScoringModelDefinition:
    """A named combination of axes (e.g. S×F) whose score is the product of
    the chosen levels' weights, divided by the product of any divisor axes'
    weights (e.g. RICE: Reach × Impact × Confidence ÷ Effort).

    Attributes:
        key: Stable machine key, unique within its scheme.
        label: Display label.
        axis_keys: The axes multiplied together (≥1); the first two are the
            matrix chart's rows (Y) and columns (X).
        default_bands: Optional default rating bands (empty = no banding
            until an org/project defines some).
        divisor_axis_keys: Axes the product is divided by (an axis where a
            *higher* weight is worse, such as Effort); disjoint from
            `axis_keys`. The normalised score divides by the best case: every
            multiplied axis at its top weight and every divisor at its lowest.
        combination: `"product"` (the default: multiplied axes over divisors) or `"weighted_sum"` (each axis
            scaled to 0..1 and summed by its importance, then divided by any divisor axes, as in WSJF).
        exponents: Product only: `(axis key, exponent)` pairs raising an axis's weight to a power, so a more
            important criterion counts for more; an axis not listed has exponent 1.
        importance: Weighted sum only: `(axis key, percentage)` for every axis in `axis_keys`, totalling 100.
        inverted_axis_keys: Weighted sum only: axes where a *lower* weight is better (they score lowest weight
            ÷ the chosen weight), the sum's counterpart of a divisor axis.
    """

    key: str
    label: str
    axis_keys: tuple[str, ...]
    default_bands: tuple[ScoringBandDefault, ...] = ()
    divisor_axis_keys: tuple[str, ...] = ()
    combination: str = "product"
    exponents: tuple[tuple[str, float], ...] = ()
    importance: tuple[tuple[str, float], ...] = ()
    inverted_axis_keys: tuple[str, ...] = ()

    def exponent(self, axis_key: str) -> float:
        """The exponent applied to `axis_key` in a product model (1 unless listed)."""
        return dict(self.exponents).get(axis_key, 1.0)

    def importance_of(self, axis_key: str) -> float:
        """The percentage `axis_key` carries in a weighted-sum model (0 if it is not part of it)."""
        return dict(self.importance).get(axis_key, 0.0)

    @property
    def supports_cell_ratings(self) -> bool:
        """Whether per-cell rating overrides apply: only a plain two-axis product has a matrix of cells."""
        return len(self.axis_keys) == 2 and not self.divisor_axis_keys and self.combination == "product"


@dataclass(frozen=True)
class ScoringSchemeDefinition:
    """A module's scoring scheme: its axes, models and defaults, resolved
    generically by `app.services.scoring` (core) so no module-specific code
    lives in core and no core enum is hand-edited per module.

    Attributes:
        key: Globally unique scheme key (also its URL segment).
        label: Display label.
        axes: The scheme's scoring axes.
        models: Named axis combinations.
        default_model_key: The system default model (bottom of the
            project → ancestor → org → system resolution chain).
        admin_role_key: Optional key of one of the registering module's
            own roles whose holders (plus org admins) may edit the org-level
            configuration. `None` = org admins only.
        count_level_usage: Optional `(db, level_id) -> int` returning how
            many module rows reference a level, so core can block or
            reassign a delete. `None` = levels are never referenced.
        reassign_level_usage: Optional `(db, from_level_id, to_level_id)`
            moving those references. Required whenever `count_level_usage`
            is set.
        allow_custom_criteria: Whether an organisation (and a project) may define its own axes and models on this
            scheme, beside the registered ones, which then can only be hidden, never deleted. Off keeps a scheme
            exactly as registered.
        side_by_side_models: Whether the module offers only the enabled models (`enabled_model_keys`) when scoring
            or viewing, or shows several at once, so the administrator chooses which models are enabled. Off hides
            that setting from the scoring screens, because nothing would read it.
        target_label: Names what a record may be scored for individually (`"persona"`), or `None` when a record
            has one score set. A scheme with a target lets each axis choose whether it is scored per target
            (`ScoringAxisDefinition.per_target`), and the custom-axis form asks which.

    Raises:
        ValueError: On construction, if keys are malformed or duplicated,
            an axis has fewer than 2 levels or duplicate names/weights, a
            model references an unknown axis, the default model is unknown,
            default bands are invalid, or only one usage hook is supplied.
    """

    key: str
    label: str
    axes: tuple[ScoringAxisDefinition, ...]
    models: tuple[ScoringModelDefinition, ...]
    default_model_key: str
    admin_role_key: str | None = None
    count_level_usage: Callable[[Session, uuid.UUID], int] | None = None
    reassign_level_usage: Callable[[Session, uuid.UUID, uuid.UUID], None] | None = None
    allow_custom_criteria: bool = False
    side_by_side_models: bool = False
    target_label: str | None = None

    def __post_init__(self) -> None:
        """Validates the scheme's internal consistency (see class docstring)."""
        if not _SCORING_KEY_PATTERN.match(self.key):
            raise ValueError(f"Invalid scoring scheme key '{self.key}'.")
        axis_keys = [a.key for a in self.axes]
        if not axis_keys or len(set(axis_keys)) != len(axis_keys):
            raise ValueError(f"Scheme '{self.key}' needs at least one axis and unique axis keys.")
        for axis in self.axes:
            if not _SCORING_KEY_PATTERN.match(axis.key):
                raise ValueError(f"Invalid scoring axis key '{axis.key}'.")
            names = {lvl.name.strip().lower() for lvl in axis.default_levels}
            weights = {lvl.weight for lvl in axis.default_levels}
            count = len(axis.default_levels)
            if count < 2 or len(names) != count or len(weights) != count or min(weights) <= 0:
                raise ValueError(f"Axis '{axis.key}' needs ≥2 levels with unique names and unique positive weights.")
            thresholds = [lvl.threshold for lvl in axis.default_levels]
            if axis.derived_source is None:
                if any(t is not None for t in thresholds):
                    raise ValueError(f"Axis '{axis.key}' is not derived, so its levels take no threshold.")
            elif None in thresholds or len(set(thresholds)) != count:
                raise ValueError(f"Derived axis '{axis.key}' needs a unique threshold on every level.")
        model_keys = [m.key for m in self.models]
        if not model_keys or len(set(model_keys)) != len(model_keys):
            raise ValueError(f"Scheme '{self.key}' needs at least one model and unique model keys.")
        for model in self.models:
            if not _SCORING_KEY_PATTERN.match(model.key):
                raise ValueError(f"Invalid scoring model key '{model.key}'.")
            if not model.axis_keys or not set(model.axis_keys) <= set(axis_keys) or len(set(model.axis_keys)) != len(model.axis_keys):
                raise ValueError(f"Model '{model.key}' must combine distinct axes of scheme '{self.key}'.")
            divisors = model.divisor_axis_keys
            if not set(divisors) <= set(axis_keys) or len(set(divisors)) != len(divisors) or set(divisors) & set(model.axis_keys):
                raise ValueError(f"Model '{model.key}' divisors must be distinct axes of scheme '{self.key}' not also multiplied.")
            validate_scoring_model_maths(model)
            if model.default_bands:
                validate_scoring_bands([(b.label, b.min_score, b.tone) for b in model.default_bands])
        if self.default_model_key not in model_keys:
            raise ValueError(f"Default model '{self.default_model_key}' is not one of scheme '{self.key}'s models.")
        if self.target_label is None and any(a.per_target for a in self.axes):
            raise ValueError(f"Scheme '{self.key}' has per-target axes but no target_label.")
        if (self.count_level_usage is None) != (self.reassign_level_usage is None):
            raise ValueError("count_level_usage and reassign_level_usage must be supplied together.")

    def axis(self, axis_key: str) -> ScoringAxisDefinition | None:
        """Returns the axis with `axis_key`, or `None`."""
        return next((a for a in self.axes if a.key == axis_key), None)

    def model(self, model_key: str) -> ScoringModelDefinition | None:
        """Returns the model with `model_key`, or `None`."""
        return next((m for m in self.models if m.key == model_key), None)


@dataclass(frozen=True)
class ScoringTarget:
    """One record a module offers as something another module scores
    against (e.g. a Persona, for per-persona Pain Point scoring), returned
    by a `ModuleDefinition.scoring_target_providers` callable.

    Attributes:
        id: The target record's id (the scoring module stores it as a plain
            `target_id`, never an FK, since it can't import the owning
            module).
        label: Display name.
        weight: The target's resolved importance for the requesting project,
            or `None` when none is set (the scoring module then weights
            every target equally).
        is_active: Whether the target is still current (`False` for a
            retired/archived record, which scoring should skip).
    """

    id: uuid.UUID
    label: str
    weight: float | None
    is_active: bool


@dataclass(frozen=True)
class DemandParty:
    """One party (a person or a persona) a record stands for when another module counts demand, returned by a
    `ModuleDefinition.demand_party_providers` callable.

    A record of the provider's own type expands to one or more parties: a Stakeholder or Persona is its own
    party, an Engagement is the Stakeholders who took part and the Personas it covered. The counting module
    de-duplicates parties by `(artefact_type, id)`, so a party reached twice counts once.

    Attributes:
        artefact_type: The party's own registered artefact type (e.g. `"stakeholder"`).
        id: The party record's id.
        label: Display name.
        weight: The party's resolved importance in the requesting project, or `None` when none is set (the
            counting module then weights it as 1).
        weight_source: Where the weight comes from, as a short key the counting module passes on for display (the
            stakeholders provider uses `influence`, `project`, `ancestor_project`, `persona` or `none`); empty when
            the provider does not say.
    """

    artefact_type: str
    id: uuid.UUID
    label: str
    weight: float | None
    weight_source: str = ""


@dataclass(frozen=True)
class ActivityLinkEnds:
    """The two records one link audit event joins, read from the event's `detail` (see `activity_link_ends`).

    Attributes:
        source: `(artefact type, id)` of the end the relationship is read from.
        target: `(artefact type, id)` of the other end.
        link_type_id: The link type's id when the event names one; its forward name is looked up.
        link_type_label: The relationship's forward name when the reader knows it without a lookup.
    """

    source: tuple[str, uuid.UUID]
    target: tuple[str, uuid.UUID]
    link_type_id: uuid.UUID | None = None
    link_type_label: str | None = None


#: Reads the ends of one link event's `detail`; returns `None` when the detail does not name two records.
ActivityLinkEndsReader = Callable[[dict[str, Any]], ActivityLinkEnds | None]


@dataclass(frozen=True)
class ArtefactSummary:
    """A minimal, module-neutral description of one artefact, returned by an
    `ArtefactSummaryProvider` so one module can link to, validate and label
    another module's records without importing them.

    Attributes:
        id: The artefact's id.
        project_id: The project the artefact belongs to (links are validated
            against the linking record's own project); `None` for a record
            owned by an organisation rather than a project (an org-level
            Persona, say), which therefore never matches a project check.
        label: Display name (a code plus title where the artefact has one).
        status: The artefact's lifecycle status as a plain string, or `None`.
        is_archived: Whether the artefact is archived.
        organization_id: The owning organisation for an org-owned record,
            else `None`.
        facets: The classifications the record carries for the scoped finder,
`{level key: (option id, option label)}`, e.g.
            `{"status": ("draft", "Draft")}`. Read by facet-derived `BrowseLevel`s
            and by the default narrowing; excluded from equality and hashing.
    """

    id: uuid.UUID
    project_id: uuid.UUID | None
    label: str
    status: str | None = None
    is_archived: bool = False
    organization_id: uuid.UUID | None = None
    facets: Mapping[str, tuple[str, str]] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class BrowseLevel:
    """One step of the scoped finder an artefact type offers when choosing a link
    target "Standard" -> "Version" -> "Requirement",
    "Component" -> "Category", or just "Status".

    A type's levels are ordered and each is optional: the user may stop after any
    level and search what is left. The owning module declares them, so the dialog
    needs no per-type code.

    Attributes:
        key: Stable identifier of the level within its type (`"standard"`). For a
            facet-derived level it is also the key in `ArtefactSummary.facets`.
        label: Singular display name shown above the picker (`"Standard"`).
        list_options: `(db, project_id, selected, query) -> [(option_id, label)]`: the
            options of this level given the options already chosen at earlier levels
            (`selected`: `{level key: option id}`), narrowed by the label text `query`
            (may be empty). `project_id` is the project whose records are being
            searched. Called only after the caller has been authorised to view the
            type in that project; it must compute its options from `selected` alone
            and never from anything the client could widen. It returns every match
            (callers cap what they send, but validate a selection against the full
            list). `None` (the default) derives the options from the facet `key` of
            the records the provider offers for the project, which suits any
            classification the records themselves carry (a status, a type).
    """

    key: str
    label: str
    list_options: Callable[[Session, uuid.UUID, Mapping[str, str], str], list[tuple[str, str]]] | None = None


@dataclass(frozen=True)
class ArtefactSummaryProvider:
    """How a module exposes one of its own `artefact_types` as a link target.

    Attributes:
        get: `(db, artefact_id) -> ArtefactSummary | None`; `None` when the
            record does not exist.
        list_for_project: `(db, project_id) -> list[ArtefactSummary]`, the
            records a picker can offer for the project.
        get_many_in_project: `(db, project_id, ids) -> list[ArtefactSummary]`,
            optional batch lookup (one query, not one per id) that returns
            only the records `project_id` may see: owned by that project, or
            owned by its organisation and not hidden from it. The owning
            module applies its own visibility rules here (e.g. per-project
            hiding of an org Persona), so the artefact link graph can ask
            "which of these are visible here" without knowing them. When
            omitted, callers fall back to `get` per id and keep records
            whose `project_id` equals the project.
        list_for_organization: Optional `(db, organization_id) -> list[ArtefactSummary]` of
            the records the *organisation itself* owns (no project), for a type that
            exists at organisation scope. It lets core resolve an organisation-qualified
            code (`ACME-PER-001`) to a record without knowing the module's tables; a type
            with no organisation-scoped records leaves it unset.
        browse_levels: The ordered `BrowseLevel`s of the type's scoped finder.
Every registered type declares at least one; a backend
            coverage test fails otherwise, so a new type cannot ship search-only.
        filter: Optional `(db, project_id, selected, query, limit) -> summaries`
            narrowing the records offered by the options chosen at the levels
            (`selected`: `{level key: option id}`) and the label text `query`. Must
            return only records `list_for_project` would offer, at most `limit` + 2
            (one more shows the result was cut, one allows for the page's own record
            being dropped). When omitted, the finder narrows by the summaries' `facets`.
    """

    get: Callable[[Session, uuid.UUID], ArtefactSummary | None]
    list_for_project: Callable[[Session, uuid.UUID], list[ArtefactSummary]]
    get_many_in_project: Callable[[Session, uuid.UUID, Sequence[uuid.UUID]], list[ArtefactSummary]] | None = None
    browse_levels: tuple[BrowseLevel, ...] = ()
    filter: Callable[[Session, uuid.UUID, Mapping[str, str], str, int], list[ArtefactSummary]] | None = None
    list_for_organization: Callable[[Session, uuid.UUID], list[ArtefactSummary]] | None = None


@dataclass(frozen=True)
class SearchField:
    """One column of a record type that the global search may match.

    Searchable fields are opt-in: a column not declared here is never matched, so a
    Restricted-classified or consent-sensitive column is excluded by omission.

    Attributes:
        key: Stable identifier shared by types that carry the same field (`"description"`),
            so the field picker lists it once. `"id"`, `"title"` and `"tags"` are reserved
            for the record's code, title and tags, which the search builds itself.
        label: User-facing name (`"Description"`, `"Mitigation"`).
        column: A SQL text expression over `ArtefactSearchProvider.from_clause`.
        markdown: The column holds Markdown, so a result's snippet shows its plain text (`services.markdown_text.
            plain_text`, diagram source included) and never the marks. The match itself is on the stored source.
    """

    key: str
    label: str
    column: Any
    markdown: bool = False


#: The longest value, in characters, a Markdown field may hold unless its declaration says otherwise.
DEFAULT_MARKDOWN_LIMIT = 50_000


@dataclass(frozen=True)
class MarkdownImages:
    """Where the pictures a Markdown field may hold come from: the attachments of the record the field belongs to.

    A field that carries this declaration accepts `![alt](attachment:<file id>)`, and the write refuses a reference to a
    file that is not attached to the record (`services.markdown_fields`). A field without it holds no pictures.

    Attributes:
        artefact_type: The record's registered type; its `RecordAttachmentProvider` names the attachment table.
        record_id: The attribute of the declared model that holds the record's id (`Decision.id`, or the version row's
            `RequirementVersion.requirement_id`).
        resolve: Instead of `record_id`, a function from the stored row to the record's id, for a row that reaches the
            record through another (a change request's proposed text is the requirement's own, so its pictures are the
            requirement's attachments); `None` result means no record, so no picture.
    """

    artefact_type: str
    record_id: Any = None
    resolve: Callable[[Any], Any] | None = None

    def record_of(self, row: Any) -> Any:
        """The id of the record whose attachments `row`'s text may show, or `None`."""
        if self.resolve is not None:
            return self.resolve(row)
        return getattr(row, self.record_id.key, None) if self.record_id is not None else None


@dataclass(frozen=True)
class MarkdownField:
    """One long free-text column whose stored value is Markdown source.

    Every long-text column (a `Text` column, or a string of 1,000 characters or more) is declared here or named in a
    `plain_text_fields` map with a reason, and a backend test fails for one that is neither. The declaration is also
    what limits the value: the ORM refuses a write that breaks the size, nesting or diagram limits
    (`services.markdown_fields`), so the endpoints, an import, a bundle and an MCP tool all store what the others do.

    Attributes:
        column: The ORM attribute (`Risk.statement`); its table and name identify the field.
        limit: The most characters the value may hold.
        math: Whether people write equations in it (`\\( x \\)` and `$$ x $$`); the screen draws them and the
            visual editor leaves such a text in Write.
        images: Whether people put the record's attached pictures in it (`MarkdownImages`); `None` for a field that is
            text only (a comment, a configuration prompt).
    """

    column: Any
    limit: int = DEFAULT_MARKDOWN_LIMIT
    math: bool = False
    images: MarkdownImages | None = None


def markdown_columns(
    model: Any, *names: str, limit: int = DEFAULT_MARKDOWN_LIMIT, math: bool = False, images: MarkdownImages | None = None,
) -> tuple[MarkdownField, ...]:
    """`MarkdownField`s for several columns of one model that share a limit.

    Args:
        model: The ORM class.
        names: Attribute names on `model`.
        limit: The character limit of each.
        math: Whether each holds equations.
        images: Whether each holds the record's attached pictures (the record they belong to).

    Returns:
        One declaration per name, in order.
    """
    return tuple(MarkdownField(getattr(model, name), limit, math, images) for name in names)


@dataclass(frozen=True)
class SearchColumns:
    """The SQL expressions a provider exposes for every record, read by the search service.

    Attributes:
        id / project_id / code / title / status / is_archived / updated_at: The record's
            identity, owning project (`NULL` for an organisation-owned record), human-readable
            code, display title, status value, archived flag and last-change time (UTC).
        organization_id: The owning organisation, for a type that can be organisation-owned.
        owner_id: The id of the record to open instead, for a type without a page of its own
            (see `ArtefactSearchProvider.open_owner_type`).
        version: The current version number, for a versioned type (`None` for one with no versions). A
            generated report records it so the report names the exact version of each record it shows.
    """

    id: Any
    project_id: Any
    code: Any
    title: Any
    status: Any
    is_archived: Any
    updated_at: Any
    organization_id: Any | None = None
    owner_id: Any | None = None
    version: Any | None = None


@dataclass(frozen=True)
class SearchComments:
    """Where a record type keeps its comments, so the global search can match them.

    Comments are matched only when a person asks for them (the reserved field key `comments`), never by
    default and never as a stored default: one `EXISTS` over a table per record type is much dearer than
    matching the record's own columns. A comment carries the same read gate as its record.

    Attributes:
        model: The comment table's ORM model (or table).
        record_id: The comment column that holds the commented record's id.
        body: The comment's text column.
        where: Extra conditions picking this type's comments from a shared table (`target_type`).
        created_at: Column that orders the comments, so the first match is the earliest.
    """

    model: Any
    record_id: Any
    body: Any
    created_at: Any
    where: tuple[Any, ...] = ()


@dataclass(frozen=True)
class ArtefactSearchProvider:
    """How a module makes one of its `artefact_types` findable by the global search.

    The provider describes the SQL (what to select from, which columns mean what, which
    are searchable); the search service owns scoping, authorisation, matching, ranking and
    paging, so a new type needs no search logic of its own.

    Attributes:
        from_clause: The table or join the records are read from (a version table joined
            in for a versioned type, restricted to the current version by `where`).
        columns: The expressions for each record's identity and display data.
        fields: The extra searchable fields beyond the code, title and tags.
        where: Conditions that always apply (`valid_to IS NULL` for a versioned type).
        status_labels: `{status value: display label}`, so a result is never labelled with
            a raw enum string.
        organization_owned: Whether records may be owned by the organisation (`project_id`
            `NULL`); such a record is found only through a project that is allowed to see it
            (the owning module's `get_many_in_project` rule, e.g. per-project hiding).
        open_owner_type: For a type with no page of its own (an engagement finding), the
            artefact type whose page opens instead; `columns.owner_id` then names that record.
        organization_subcomponent: For a type whose organisation-owned records have their own
            organisation-level surface rather than a project's (an organisation Strategy, listed and
            opened from the organisation overview): the sub-component of the owning module whose
            organisation-level state gates it. Such a record is searched in the "all projects" scope
            for every member of an organisation where that sub-component is on, exactly as the
            organisation's own list is read, and opens at its organisation page.
        comments: Where the type's comments live (`SearchComments`), making the opt-in `comments`
            field available; `None` for a type with no comments.
    """

    from_clause: Any
    columns: SearchColumns
    fields: tuple[SearchField, ...] = ()
    where: tuple[Any, ...] = ()
    status_labels: Mapping[str, str] = field(default_factory=dict)
    organization_owned: bool = False
    open_owner_type: str | None = None
    organization_subcomponent: str | None = None
    comments: SearchComments | None = None


#: The value kinds a report field may have; the renderer formats each (`services.report_fields.format_value`).
REPORT_FIELD_KINDS = ("text", "number", "date", "instant", "bool", "enum", "principal")


@dataclass(frozen=True)
class ReportField:
    """One field of a record type that a custom report layout may print, filter or group by.

    Report fields are opt-in, like search fields: a column not declared is never reachable from a
    layout, so a Restricted-classified or consent-sensitive column is excluded by omission.

    Attributes:
        key: Stable identifier a layout names (`{{record.description}}`); a field shared by several
            types reuses one key and label. `"code"`, `"title"`, `"status"` and `"tags"` are reserved
            for what the engine builds itself from the provider's `SearchColumns`.
        label: User-facing name for the field picker.
        column: A SQL expression over `ReportFieldProvider.from_clause`. For a `principal` field, the
            `<name>_type` column.
        kind: One of `REPORT_FIELD_KINDS`. `date` is a calendar date, `instant` a past UTC time.
        labels: For an `enum`, `{stored value: display label}`; a value is never shown raw.
        id_column: For a `principal` field, the `<name>_id` column (a user or a group).
        math: For a `text` field, whether people write equations in it (`\\( x \\)`, `$$ x $$`), so a layout's
            text block that prints it draws them. Opt-in per field; any other text stays literal.
        markdown: For a `text` field, whether it holds Markdown (declared for the column in `markdown_fields`; a search field
            that is Markdown makes its report field so), so a layout's text block that prints only this field draws its
            headings, lists, tables, code and diagrams, and a cell or a sentence shows its words.
        domain: For a field whose values come from a closed list a project defines (a component's name, a type
            definition's name), `(db, project ids) -> the values on offer`, so a run-time variable can offer them as
            options. An `enum` needs none (its `labels` are the domain); a field with neither takes free input.
            `project ids` are the projects the report is for (one, or the readable projects of an organisation run).
        core: Whether the field is part of the type's core detail: the few fields that say what a record is and who
            answers for it (the person responsible, the main descriptive text). The default workbook starter prints
            code, title, status and tags plus every core field of each type, so a new type's sheet is never empty.
    """

    key: str
    label: str
    column: Any
    kind: str = "text"
    labels: Mapping[str, str] = field(default_factory=dict)
    id_column: Any | None = None
    math: bool = False
    markdown: bool = False
    domain: Callable[[Session, Sequence[uuid.UUID]], list[str]] | None = None
    core: bool = False


@dataclass(frozen=True)
class RecordAttachmentProvider:
    """How a record type's directly attached files are found, so a report's record-images block can print them.

    The files are those a person attaches to the record itself (the type's own file-link table), never those on a comment
    thread. The report engine reads only for records the layout's traversal already showed the caller, so a file prints
    only when the caller could open it from the record's page.

    Attributes:
        link: The file-link table's model: it has a `file_id` column (a `FileAsset`) and the column below.
        record_column: The link table's column holding the record's id (`PainPointFile.pain_point_id`).
    """

    link: Any
    record_column: Any


@dataclass(frozen=True)
class ReportFieldProvider:
    """How a module makes one of its `artefact_types` reportable by a custom report layout.

    The provider describes the SQL (what the records are, which fields exist); the engine
    (`services.report_fields`) owns batching, formatting and the rule that it is only ever asked
    for records the caller was already shown by the link graph's authorisation.

    Attributes:
        from_clause: The table or join the records are read from (a version table joined in
            for a versioned type, restricted to the current version by `where`).
        columns: The record's identity and display columns (the shape the search uses).
        fields: The fields a layout may use beyond code, title, status and tags.
        where: Conditions that always apply (`valid_to IS NULL` for a versioned type).
        status_labels: `{status value: display label}`.
    """

    from_clause: Any
    columns: SearchColumns
    fields: tuple[ReportField, ...] = ()
    where: tuple[Any, ...] = ()
    status_labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ScopeResolution:
    """What a module-defined search scope covers.

    Attributes:
        project_ids: The projects the unit spans; the search still keeps only those the
            caller can read.
        restrictions: Per artefact type, an extra SQL condition on that type's query. A type
            absent from this mapping is not searched in the scope.
    """

    project_ids: tuple[uuid.UUID, ...]
    restrictions: Mapping[str, Any]


@dataclass(frozen=True)
class SearchScope:
    """A search scope a module offers beyond the built-in "This project" and "All projects"
    (Compliance's "This standard").

    Attributes:
        label: The scope's display name.
        narrowness: Which scope is the default where several match the current page: the
            highest wins. Built-ins are All projects 0 and This project 100.
        resolve: `(db, user_id, ref_id) -> ScopeResolution | None`. `None` means "not found
            or not allowed", answered identically either way so a ref in another organisation
            or one the caller cannot read reveals nothing.
    """

    label: str
    resolve: Callable[[Session, uuid.UUID, uuid.UUID], ScopeResolution | None]
    narrowness: int = 200


RECORD_SENSITIVITY_TAGS: tuple[str, ...] = ("personal", "contact", "free_text_people")
"""The closed vocabulary of `RecordColumn.sensitivity` besides `"none"`: `personal` (names and identifiers of
people), `contact` (ways to reach a person) and `free_text_people` (free text that can quote people). A closed core
concept, not a per-module value: a module classifies its own columns with these, it never adds a tag."""


class RecordCellError(ValueError):
    """Raised by a `RecordColumn.parse` (or a provider's create/update) when a cell cannot be used; the message is
    shown to the person as the row's error, so it names the problem in their terms and never echoes other rows' data."""


@dataclass(frozen=True)
class RecordFilters:
    """The list filters of an export, as the query parameters the type's own list endpoint takes.

    Attributes:
        values: `{parameter name: [values]}` for the provider's `filter_params` only (the engine has
            already taken `tag`, `tag_mode`, `project_scope` and `format`, and rejects any other name).
    """

    values: Mapping[str, Sequence[str]] = field(default_factory=dict)

    def one(self, key: str) -> str | None:
        """The first value of `key`, or `None` when absent or blank."""
        found = [v for v in self.values.get(key, ()) if v.strip()]
        return found[0].strip() if found else None

    def many(self, key: str) -> list[str]:
        """Every non-blank value of `key`."""
        return [v.strip() for v in self.values.get(key, ()) if v.strip()]

    def flag(self, key: str) -> bool | None:
        """`key` as a boolean (`true`/`1`/`yes`), `None` when absent."""
        value = self.one(key)
        return None if value is None else value.lower() in ("true", "1", "yes")


@dataclass
class RecordImportContext:
    """What a provider's `parse`, `create` and `update` get for one import.

    Attributes:
        db: The session. Providers never commit: the engine owns the transaction (a savepoint per row, one
            commit at the end of an apply, a rollback for a preview).
        project: The project being imported into; `None` when the import is into the organisation's own records
            (`OrganizationRecordTable`), whose providers read `organization` instead.
        user: The person importing; the actor for the type's own audit events.
        cache: Per-import scratch for lookups (a user by email), so a 5,000-row file does not repeat them.
        organization: The organisation being imported into (set for both tiers by the engine).
    """

    db: Session
    project: Any
    user: Any
    cache: dict[str, Any] = field(default_factory=dict)
    organization: Any = None

    @property
    def organization_id(self) -> uuid.UUID:
        """The organisation being imported into: the project's, or the organisation itself at the organisation tier."""
        return self.project.organization_id if self.project is not None else self.organization.id

    @property
    def project_id(self) -> uuid.UUID | None:
        """The project being imported into, or `None` at the organisation tier."""
        return self.project.id if self.project is not None else None


@dataclass(frozen=True)
class RecordColumn:
    """One column of a record type's table, shared by export, import and the bulk edit grid.

    A column is **importable** when it has a `parse`; one without is export-only (a status the approval gate
    owns, a derived value, an instant). The provider is the only place a column is classified.

    Attributes:
        key: The CSV header (stable; a rename breaks people's files).
        label: The name a person sees.
        get: `(prepared, record) -> str`: the cell text, **unprefixed** (the engine adds the formula guard);
            also the "before" value an import compares against. Dates `YYYY-MM-DD`, instants UTC ISO 8601,
            enums by the label users see, a person as an email (user) or `Name (Organisation group)` (group).
        parse: `(ctx, text) -> value`: the cell text (whitespace stripped, may be empty) to the value
            `create`/`update` receive; raises `RecordCellError`. `None` for an export-only column.
        kind: `text`, `enum`, `principal`, `date`, `number`, `bool`, `instant` or `list`, for the UI.
        editable: Whether the bulk edit grid may offer it; only an importable column can be editable. The grid
            edits the closed-value kinds (`enum`, `number`, `date`, `bool`); a free-text column is edited in the
            record's form, where a long text has room to grow.
        required: Whether a create needs a value (the form's `*`); a column that is present must not be blank.
        sensitivity: `"none"` or one of `RECORD_SENSITIVITY_TAGS`.
        choices: The cell texts the column accepts when they are a closed list (enum labels, the project's
            stage names), so the import wizard offers a pick list for "same value for every row".
            `None` for free text and for values that are not a short closed list (a person, a date).
        cell_lock: `(prepared, record) -> str | None`: why the bulk edit grid cannot edit this one cell of this row (a
            Pain Point scored per persona has no single severity to set), or `None`. The grid shows the cell disabled
            with the reason, and a save of it is refused with the same reason. Does not affect export or import.
        tones: Badge tone per cell text (`{"Approved": "accent"}`, tone names as `report_model.TONE_FILL`), so the
            record-list report's PDF and Word fill the cell as the screen's badge does. A cell text not listed is
            left plain; the text itself still names the value, so a greyscale print reads.
        markdown: The cell holds Markdown source. The CSV carries the source both ways (it is the import file); the
            record-list report's screen, PDF and Word show its plain text (`services.markdown_text.plain_text`), so a
            cell never shows `**` or a pipe table.
    """

    key: str
    label: str
    get: Callable[[Any, Any], str]
    parse: Callable[[RecordImportContext, str], Any] | None = None
    kind: str = "text"
    editable: bool = False
    required: bool = False
    sensitivity: str = "none"
    choices: tuple[str, ...] | None = None
    cell_lock: Callable[[Any, Any], str | None] | None = field(default=None, compare=False)
    tones: Mapping[str, str] = field(default_factory=dict, compare=False)
    markdown: bool = False

    @property
    def importable(self) -> bool:
        """Whether an import may write this column."""
        return self.parse is not None


@dataclass(frozen=True)
class OrganizationRecordTable:
    """How a record type offers the records its **organisation** owns (a Strategy or a Persona shared by every
    project) as a table, for the organisation-level lists. The engine's organisation routes
    (`/orgs/{id}/records/{type}/...`) use it exactly as the project routes use the provider, and the same
    `RecordColumn`s: a column is declared once and serves both tiers.

    Every callable takes the `Organization` where the project tier takes a project; nothing here commits.

    Attributes:
        subcomponent: The owning module's sub-component whose organisation-level state gates the list (the same
            one the organisation list endpoint requires); the route answers 404 while it is off. `None` for a module
            that declares no sub-components: the module being enabled for the organisation is then the whole gate.
        columns: `(db, organization) -> columns` (first column excluded; the engine adds `code`).
        list_records: `(db, user, organization, filters) -> records`: the organisation's own records, with the
            filters of the organisation list (the endpoint and the provider share one query).
        find: `(db, organization, unique_code) -> record | None`, searching **this organisation's own records only**.
        find_many: `(db, organization, codes) -> {UPPER code: record}`: `find` for many codes in one statement (see
            `services.record_tables.find_many_by_code`), so an import reads the named records once, not once per row. `None`
            falls back to `find` per code.
        prepare: `(db, organization, records) -> prepared`: batch lookups handed to every column's `get`.
        create: `(ctx, values) -> record` through the organisation endpoint's own create path (`ctx.project` is
            `None`; use `ctx.organization`). `None` for a type import cannot create.
        update: `(ctx, record, values) -> None` through its own update path. `None` for a type import cannot update.
        filter_params: The organisation list's filter parameter names; any other is refused.
        can_create / can_update: `(db, user, organization_id) -> bool`, the same check as the organisation
            endpoint's create / update. `None` falls back to the fine-grained `propose_create` / `manage` permission.
    """

    subcomponent: str | None
    columns: Callable[[Session, Any], Sequence[RecordColumn]]
    list_records: Callable[[Session, Any, Any, RecordFilters], list[Any]]
    find: Callable[[Session, Any, str], Any | None]
    find_many: Callable[[Session, Any, Sequence[str]], dict[str, Any]] | None = None
    prepare: Callable[[Session, Any, list[Any]], Any] | None = None
    create: Callable[[RecordImportContext, Mapping[str, Any]], Any] | None = None
    update: Callable[[RecordImportContext, Any, Mapping[str, Any]], None] | None = None
    filter_params: frozenset[str] = frozenset()
    can_create: Callable[[Session, Any, uuid.UUID], bool] | None = None
    can_update: Callable[[Session, Any, uuid.UUID], bool] | None = None


@dataclass(frozen=True)
class RecordTableProvider:
    """How a record type offers its list as a table that leaves as CSV (PDF and Word through the
    record-list report) and, for an authored type, comes back as an import that creates and updates.

    The engine (`services.record_tables`) owns authorisation, the project scope, tags, the file format, caps,
    the formula guard, the preview, the per-row transaction and the audit events; a provider says only what
    the type's rows and columns are and how its **own** create/update path is called, so a type's version
    lock, validation, approval gate and audit event are never bypassed by a file.

    Attributes:
        label: The plural name for the UI and file name (`"Requirements"`).
        columns: `(db, project) -> columns`, first column excluded (the engine adds `code`). A callable because
            some columns are the project's own (custom fields).
        list_records: `(db, user, project_id, filters) -> records` for one project, with the filters of the type's
            list endpoint (the endpoint and the provider share one query function, so a filter reaches both).
            Archived rows only when asked, as the list does.
        find: `(db, project, unique_code) -> record | None`, searching **this project only**.
        find_many: `(db, project, codes) -> {UPPER code: record}`: `find` for many codes in one statement
            (`services.record_tables.find_many_by_code`), so an import reads the named records once, not once per row.
            `None` falls back to `find` per code.
        prepare: `(db, project, records) -> prepared`: batch lookups handed to every column's `get`.
        create: `(ctx, values) -> record` through the type's own create path; `values` holds every importable
            column in the file, parsed. `None` for a type that import cannot create.
        update: `(ctx, record, values) -> None` through the type's own update path; `values` holds the
            changed columns only. Raises `RecordCellError` or `HTTPException` for a row it refuses (a locked
            requirement). `None` for a type that import cannot update.
        filter_params: The list endpoint's filter parameter names this provider understands; any other
            parameter is rejected, so a filtered-looking screen never downloads an unfiltered file.
        gate: `(module_key, sub_component_key | None)`: the list endpoint's module gate, used for the project
            scope; `None` for a core type.
        can_create / can_update: `(db, user, project_id) -> bool`, the same check as the type's own create /
            update endpoint. `None` falls back to the fine-grained `propose_create` / `manage` permission.
        id_of: Reads a record's id (tag filter, scope de-duplication).
        code_of: Reads a record's `unique_code`.
        approval_gated: The type has an approval gate, so import never writes its status (a test asserts no
            importable column is named `status`).
        organization_owned: `(record) -> bool` for a type whose list also shows records the organisation owns
            (a persona shared by every project): such a row is exported with the organisation-qualified code
            (`ACME-PER-001`, always qualified, since its bare code could equal a project record's), and is
            never matched by an import into a project, whose `find` searches the project's own records only.
            `None` for a type that has no organisation-owned records.
        organization: The type's table at the organisation tier (`OrganizationRecordTable`): the organisation's own
            records on the organisation-level lists. `None` for a type the organisation cannot own.
        read_only_reason: `(prepared, record) -> str | None`: why the bulk edit grid shows this row read-only
            (a Pain Point at a terminal outcome), or `None` when it can be edited. The grid greys such a row and
            says the reason; a save of it is refused with the type's own message either way, so this is a courtesy
            to the person, not the gate. `None` for a type whose rows are always editable in principle.
        count: `(db, user, project_id) -> int`: how many records of this type the project itself holds, as its
            default list shows them (archived rows left out), **excluding** organisation-owned rows. The project
            overview's record total calls it for every type, so a type with a cheap query supplies one; `None`
            counts the rows of `list_records` with no filters.
        in_overview: Whether the type is a record a person authored in the project and so counts in the overview's
            total. `False` for rows derived from something else (a project's assessment of each clause of an
            assigned standard, the standard's own clauses): a count of them describes the standard, not the work.
        title_column: The key of the column the **Title** sort uses (`"name"`, `"question"`); the column whose text
            names the record in the list. Every type's list offers Code, Title, Created and Modified
            (`services.list_sort`); the other keys are the type's own columns, ordered by their cell text.
        sort_keys: `{key: (prepared, record) -> text, number, instant or None}`: a key the default reading cannot
            give. The defaults are the code (`code_of`), the record's `created_at` and `updated_at`, and any column
            by its cell text; a type whose rows are not plain records (a row assembled from several tables) supplies
            `created` and `modified` here.
    """

    label: str
    columns: Callable[[Session, Any], Sequence[RecordColumn]]
    list_records: Callable[[Session, Any, uuid.UUID, RecordFilters], list[Any]]
    find: Callable[[Session, Any, str], Any | None]
    find_many: Callable[[Session, Any, Sequence[str]], dict[str, Any]] | None = None
    prepare: Callable[[Session, Any, list[Any]], Any] | None = None
    create: Callable[[RecordImportContext, Mapping[str, Any]], Any] | None = None
    update: Callable[[RecordImportContext, Any, Mapping[str, Any]], None] | None = None
    filter_params: frozenset[str] = frozenset()
    gate: tuple[str, str | None] | None = None
    can_create: Callable[[Session, Any, uuid.UUID], bool] | None = None
    can_update: Callable[[Session, Any, uuid.UUID], bool] | None = None
    id_of: Callable[[Any], Any] = lambda record: record.id
    code_of: Callable[[Any], str] = lambda record: record.unique_code
    approval_gated: bool = False
    organization_owned: Callable[[Any], bool] | None = None
    organization: OrganizationRecordTable | None = None
    read_only_reason: Callable[[Any, Any], str | None] | None = None
    count: Callable[[Session, Any, uuid.UUID], int] | None = None
    in_overview: bool = True
    title_column: str = "title"
    sort_keys: Mapping[str, Callable[[Any, Any], Any]] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class PerfDatasetGenerator:
    """How a module's own records are generated in bulk for the performance tooling (`perf/`), so a dataset
    scaled to thousands of requirements also scales this module's records and their links.

    Attributes:
        generate: Called once per generated project with a `services.perf_dataset.context.PerfProjectContext`;
            writes the type's rows (bulk inserts through `insert_rows`, populating every column the application's
            own create path populates, and a never-reused code through the project's sequence counter) and returns
            the rows written by table name.
        order: Lower runs first. Core requirements run at 10 and actions at 20; a type that links to requirements
            runs after them and finds their ids in `ctx.shared["requirement"]`.
    """

    generate: Callable[[Any], dict[str, int]]
    order: int = 100


@dataclass(frozen=True)
class ScalingProbe:
    """How the scaling-shape guard fills and reads one artefact type through its public API, so a test can
    compare the cost of the type's list, detail, comments and link graph at two data sizes.

    Attributes:
        list_path: The type's project list endpoint, relative to `/api/v1/projects/{project_id}/` (for example
            `modules/risk_management/risks`). Its detail is `<list_path>/{id}` and its comments
            `<list_path>/{id}/comments`.
        create: `create(api, project_id, start, count)` creates `count` records through the real create endpoint
            (`start` numbers them, so titles stay distinct across calls) and returns their ids. It fetches any
            prerequisite (a type vocabulary, a parent record) itself, since it is called once per size. `api` is
            a `ScalingProbeApi`.
        has_comments: Whether the type has a comment thread at `<detail>/comments`.
        has_detail: Whether the type has a detail endpoint at `<list_path>/{id}`.
    """

    list_path: str
    create: Callable[[Any, str, int, int], list[str]]
    has_comments: bool = True
    has_detail: bool = True


@dataclass(frozen=True)
class LifecycleDefinition:
    """The state path of one record type, so a project can turn off its optional states and an organisation can
    require them (`services.lifecycles`).

    Attributes:
        label: The record type's singular name, used in messages and the settings panels.
        path: The main path in order (first = the start, last = the end).
        transitions: Every legal move as `{state: {next states}}`, the same table the type's own transition
            function enforces, with state keys as plain strings. A move to a turned-off state is stepped over.
        labels: The formal label of each state, for the settings panels and messages.
        optional: States a project may turn off. Never the first or last of `path`, never an off-path state and never
            a gated state, so a type opts in explicitly (the default is none).
        gated: States whose move needs a permission or a second person's decision of its own; never optional.
        entry_guard: `entry_guard(db, user, project, record_id, state)` raises a 403 `HTTPException` when `user` may
            not move this record into `state`, the same check the type's own move endpoint makes. A skip of steps
            runs it for every step passed over, so a person never skips into a step they could not enter in turn.
            A type without one cannot have steps skipped.
        record_model: The SQLAlchemy model of the type (an `id`, a `creator_id` and a `project_id`), so the approval
            separation rule can read who created a record (`services.approval_separation`). Required for a type with
            a gated state.
    """

    label: str
    path: tuple[str, ...]
    transitions: Mapping[str, frozenset[str]]
    labels: Mapping[str, str]
    optional: tuple[str, ...] = ()
    gated: tuple[str, ...] = ()
    entry_guard: Callable[[Session, User, Project, uuid.UUID, str], None] | None = None
    record_model: Any = None


@dataclass(frozen=True)
class RecordCommentProvider:
    """How a module opts one of its `artefact_types` into the generic record comments (`services.record_comments`).

    Reading and commenting follow the record's own visibility (`ArtefactResolver`, as the Links panel does) and the
    project view right, so a provider declares only where a comment may be pinned on the record's drawing. A type
    with an empty `anchor_kinds` takes ordinary comments and no pins.

    Attributes:
        anchor_kinds: The pin anchors the record's drawing offers: `node` (a box), `edge` (a line); a free spot
            (`none`) is always allowed where the type allows any pin.
        validate_anchor: `validate_anchor(db, project_id, record_id, kind, key)` is true when `key` names a box or
            line that exists for the record in that project; called for every new or moved pin with a `node` or
            `edge` anchor. Required when `anchor_kinds` is not empty.
    """

    anchor_kinds: tuple[str, ...] = ()
    validate_anchor: Callable[[Session, uuid.UUID, uuid.UUID, str, str], bool] | None = None


@dataclass(frozen=True)
class BaselineSnapshotRecord:
    """One record a `BaselineSnapshotProvider` captured.

    Attributes:
        item_id: The live record's id when the snapshot was taken.
        content: A self-contained JSON object describing the record as it stood (never a reference that needs the live
            record to read, and never a Restricted-classified or personal-data value, since the baseline outlives the
            record and travels in the project bundle).
    """

    item_id: uuid.UUID
    content: dict[str, Any]


@dataclass(frozen=True)
class BaselineSnapshotContext:
    """What a snapshot provider is told about the baseline being written.

    Attributes:
        kind: `stage` (a stage entered a locked phase) or `manual` (taken on request).
        stage_id: The stage being baselined, for a `stage` baseline.
        component_id: Set when the baseline is one component's own (component phases); a provider whose records do not
            belong to a component returns nothing then, so the project-wide baseline is the only one that holds them.
        actor_id: The person who triggered it.
    """

    kind: str
    stage_id: uuid.UUID | None
    component_id: uuid.UUID | None
    actor_id: uuid.UUID | None


@dataclass(frozen=True)
class BaselineSnapshotProvider:
    """How a module's records enter a baseline (`services.baseline`), for one of its own `artefact_types`.

    Attributes:
        snapshot: `snapshot(db, project, context)` returns the project's records of this type as they stand, one
            `BaselineSnapshotRecord` each, in a stable order. It reads through the module's own visibility rules and
            never flushes or commits; it runs inside the caller's transaction, so a failure stores no baseline.
        permission: The permission atom (`services.permissions.encode_permission`) a person needs to put this type in a
            manual baseline. An automatic stage baseline is written for the person who moved the stage and is not
            subject to it.
    """

    snapshot: Callable[[Session, Any, BaselineSnapshotContext], list[BaselineSnapshotRecord]]
    permission: str


class ScalingProbeApi:
    """The calls a `ScalingProbe.create` makes: `post(path, body)`, `put(path, body)` and `get(path)` return the decoded
    JSON and raise on a failure status. Paths are absolute from `/api/v1`. The guard supplies the implementation. A
    probe's last `post` must be the request that creates the record under test, because the creation-permission check
    runs that one as another person; a `put` never takes that role."""

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def put(self, path: str, body: dict[str, Any] | None = None) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def get(self, path: str) -> Any:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class OverviewMetricValue:
    """What one overview metric returns for one evaluation (`OverviewMetric.evaluate`).

    Attributes:
        value: The single figure, or `None` when the metric has none (a breakdown-only metric).
        breakdown: `(key, label, value)` rows for a chart; `None` when the metric has no breakdown.
        detail: Optional text per breakdown key (a stage's phase name).
    """

    value: float | None = None
    breakdown: list[tuple[str, str, float]] | None = None
    detail: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OverviewMetric:
    """One figure the project overview can show, from the bounded catalogue (never an arbitrary query).

    A widget names a metric by key and passes `params`; the server checks the key against the catalogue and every
    parameter against `params`, so a manager's configuration cannot reach data the metric does not define.

    Attributes:
        label: Name shown in the widget editor and as the default widget title.
        unit: `count` or `percent`; decides the gauge's default range and the value's suffix.
        evaluate: `(ctx, params) -> OverviewMetricValue`. `ctx` is a `services.overview_metrics.MetricContext`
            (session, caller, project, project scope). Read-only; must not add a statement per record.
        params: The configuration keys the metric accepts (`record_type`, `filters`); any other is refused.
        breakdown: Whether the result carries a breakdown, so chart widgets offer the metric.
        scalar: Whether the result carries a single value, so tile and gauge widgets offer the metric.
        gate: `(module_key, sub_component_key | None)` that must be open for the project, `None` for a core metric.
    """

    label: str
    unit: str
    evaluate: Callable[[Any, Mapping[str, Any]], OverviewMetricValue]
    params: frozenset[str] = frozenset()
    breakdown: bool = False
    scalar: bool = True
    gate: tuple[str, str | None] | None = None


@dataclass(frozen=True)
class OverviewWidgetType:
    """A widget type a module contributes to the project overview (`ModuleDefinition.overview_widgets`).

    The module's frontend registers the renderer under the same key (`TierAModuleDefinition.overviewWidgets`); this
    declaration lets the server validate stored layouts and offer the type only where the module is enabled.

    Attributes:
        label: Name in the "Add widget" list.
        description: One sentence on what it shows (the `(?)` help in the editor).
        width: The width in columns (of 12) a new widget of this type starts with.
        height: The height in rows a new widget of this type starts with.
        in_default_layout: Whether the built-in overview includes one of this type while the module is enabled (placed
            after the key tiles), so a project that has set no layout shows the module's contribution. A layout a
            person has saved is never changed when a module is enabled later; they add the widget themselves.
    """

    label: str
    description: str
    width: int = 4
    height: int = 4
    in_default_layout: bool = False


@dataclass(frozen=True)
class LinkTypeSeed:
    """A link type a module wants to exist in every organisation, so its
    artefact types can be linked meaningfully without a core edit
    (`ModuleDefinition.link_type_seeds`).

    Seeds describe, they do not gate: a type is created lazily when first
    needed or listed (`services.link_types.ensure_org_link_type`) and **only
    when the organisation has no type with that `forward_name`**, so an admin's
    edit (renamed phrases, changed flow, a different restriction) is never
    overwritten. Seeds that share a `forward_name` (several modules sharing
    "Supersedes", or a legacy kind reusing "Drives") are merged: the restriction
    lists are unioned and the phrases must agree.

    Attributes:
        forward_name / reverse_name: The phrase read from the source / target.
        flow: Direction in a traceability chain (`LinkFlow`).
        allowed_source_types / allowed_target_types: Artefact types the link
            may run from / to; `None` = any.
        dedicated_endpoint: The type has a fixed meaning with its own action
            (e.g. "Supersedes" flips a status), so the generic link endpoints
            neither offer nor delete it.
        nesting_scope: Whether the type may join a project and its ancestor or
            descendant, and which end may sit higher (`LinkNestingScope`).
            `UPSTREAM_IN_ANCESTOR` needs a `flow` other than `NONE`. Applied only
            when the seed creates the type, never to an existing one.
    """

    forward_name: str
    reverse_name: str
    flow: LinkFlow = LinkFlow.NONE
    allowed_source_types: tuple[str, ...] | None = None
    allowed_target_types: tuple[str, ...] | None = None
    dedicated_endpoint: bool = False
    nesting_scope: LinkNestingScope = LinkNestingScope.ANCESTOR_EITHER_WAY


@dataclass(frozen=True)
class NotificationTypeDefinition:
    """A notification type a module sends (`ModuleDefinition.notification_types`).

    Core's `NotificationType` enum is closed, so a module declares its own kinds
    here instead of adding members to it. A kind is stored as a plain string on
    `Notification`/`NotificationPreference`, validated against the core enum plus
    every registered module's declarations (`get_all_notification_types`), and
    shows up in each user's notification preferences under `label`.

    Attributes:
        key: The stored value, unique across core and all modules. Prefix it with
            the module key (`"risk_review_due"`) so two modules cannot collide.
        label: The sentence-case name shown in notification preferences.
        target_kinds: Where opening the notification takes the person, as ordered target kinds the
            frontend resolves (`services.notification_targets` lists the core ones; a kind only this
            module can open goes in `ModuleDefinition.notification_target_kinds`). The first kind whose
            data the notification carries wins. Required: a test fails for a type with none.
    """

    key: str
    label: str
    target_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtefactChange:
    """One change to an artefact, handed to every module's
    `ModuleDefinition.on_artefact_changed` hook (`services.artefact_changes`).

    Attributes:
        artefact_type: The changed artefact's registered type (e.g. `"requirement"`).
        artefact_id: Its id.
        project_id: The project that owns it.
        kind: What happened: `"content_changed"` (a new version altered what the
            artefact says) or `"archived"`.
        summary: One line for a human, e.g. the artefact's code and what changed.
        actor_id: Who made the change, or `None` for a system change.
    """

    artefact_type: str
    artefact_id: uuid.UUID
    project_id: uuid.UUID
    kind: Literal["content_changed", "archived"]
    summary: str
    actor_id: uuid.UUID | None


@dataclass(frozen=True)
class RegisteredScoringScheme:
    """A scoring scheme paired with the key of the module that registered
    it — the module key drives enablement gating and `admin_role_key`
    resolution."""

    module_key: str
    scheme: ScoringSchemeDefinition


# --- Reports (core report framework) ---------------------------------------

REPORT_PARAM_TYPES: frozenset[str] = frozenset({"string", "integer", "boolean", "date", "uuid"})
REPORT_ORG_SCOPES: frozenset[str] = frozenset({"readable_projects", "all_org_projects"})
# Query names the framework owns; a declared parameter may not shadow one.
RESERVED_REPORT_PARAM_NAMES: frozenset[str] = frozenset({
    "format", "include_children", "project_id", "organization_id", "current_user", "db",
    "request",
})
_REPORT_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_REPORT_PARAM_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_REPORT_PART_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Parts every report offers without declaring them: its headline figures and its caveat notes.
BUILT_IN_REPORT_PARTS: tuple[str, ...] = ("figures", "notes")


@dataclass(frozen=True)
class ReportPartDefinition:
    """One table of a report that a custom report layout can embed on its own (a widget).

    A widget is a component, not a whole report: the layout supplies the headings and prose around it.

    Attributes:
        key: The `ReportSection.key` the collector gives the table (`[a-z][a-z0-9_]*`, unique within the report,
            not `figures` or `notes`, which every report offers).
        title: Short name shown in the layout designer's widget list.
        description: Optional one line about what the table holds.
    """

    key: str
    title: str
    description: str = ""



@dataclass(frozen=True)
class ReportParamDefinition:
    """One typed query parameter of a report.

    Core validates the query value from this declaration (so a collector only
    ever sees a clean value) and derives the OpenAPI parameter and the MCP tool
    parameter from it.

    Attributes:
        name: Query parameter name (`[a-z][a-z0-9_]*`, not in
            `RESERVED_REPORT_PARAM_NAMES`).
        type: One of `REPORT_PARAM_TYPES`.
        default: Value used when the parameter is absent (`None` = no value).
            Must itself satisfy `type`, `choices` and the bounds.
        choices: Allowed values (`string`/`integer` only); a value outside the
            set is rejected with 400.
        minimum: Inclusive lower bound (`integer` only); violation is 422.
        maximum: Inclusive upper bound (`integer` only); violation is 422.
        description: One line shown in the catalogue, OpenAPI and MCP.
        label: Human label for the generated form control; empty falls back
            to a humanised `name`.
        choice_labels: Human labels keyed by choice value, for the generated
            select; a choice without one falls back to its humanised value.
            Keys must be among `choices`.
        choices_for: `(db, organization_id, project_id) -> [(value, label), ...]` for a value set that differs by
            project or organisation (the scoring models a project offers). The catalogue calls it for the project
            (`project_id` set) or organisation (`project_id` `None`) it is built for and shows the result as the
            select's options, so a person picks a name instead of typing a key. It is for display only: the value
            is not checked against it (the collector checks it against each project reported on), so the
            parameter must not also declare `choices`. A provider that raises leaves the control a text box.
    """

    name: str
    type: Literal["string", "integer", "boolean", "date", "uuid"]
    default: Any = None
    choices: tuple[Any, ...] | None = None
    minimum: int | None = None
    maximum: int | None = None
    description: str = ""
    label: str = ""
    choice_labels: Mapping[Any, str] | None = None
    choices_for: Callable[[Session, uuid.UUID, uuid.UUID | None], Sequence[tuple[Any, str]]] | None = None


@dataclass(frozen=True)
class ReportStarterSection:
    """A part of a starter report layout (Business Requirements Document, Engineering Specification, Review
    Package) that a module contributes for its own records.

    Attributes:
        starter: The starter's key (`services.report_starters`, e.g. `business-requirements-document`).
        order: Where the part sits among the starter's parts (ascending; the core's own parts leave gaps).
        nodes: The layout blocks of the part (headings, text, tables, widgets), written against the report
            field registry and widget catalogue. The core wraps them in an `if` on this module, so a project
            where the module is off leaves them out; the nodes do not test for that.
    """

    starter: str
    order: int
    nodes: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ReportSnippetParameter:
    """One choice a person makes when inserting a report snippet (`ReportSnippet.parameters`).

    A parameter names where its value goes as **paths into the fragment** (`nodes[0].file`), never as a token parsed
    out of text, so the fragment is always a valid tree, a value cannot land in the wrong field, and a snippet is
    checked whole when it is defined.

    Attributes:
        key: Stable key, unique within the snippet.
        label: What the form calls it.
        kind: `image` (a picture from the layout's library; required), `record_type` (a reportable record type the scope
            can use; required) or `text` (a short text; `default` is used when the person leaves it empty).
        targets: Paths in the fragment that receive the value, `nodes[...]` or `page_styles[...]` style
            (`nodes[0].children[1].source.record_type`).
        help: One or two sentences: what it is and what it affects.
        default: The value used when none is given (`text` only; an image and a record type are never defaulted).
        record_types: For `record_type`: `reportable` (any type the scope can report) or `attachments` (only types whose
            attached files a report can print).
        max_length: Longest text accepted (`text`).
    """

    key: str
    label: str
    kind: str
    targets: tuple[str, ...]
    help: str
    default: str | None = None
    record_types: Literal["reportable", "attachments"] = "reportable"
    max_length: int = 200


@dataclass(frozen=True)
class ReportSnippet:
    """A named fragment of a report layout that the designer inserts by copying its blocks (nothing links back).

    Attributes:
        key: Stable key, unique across core and modules.
        name: Display name.
        description: One sentence about what it adds.
        category: Group the picker lists it under.
        blocks: The blocks inserted (a tree fragment, valid against the block schemas when applied).
        family: `document` or `table`, the layout family it belongs to.
        root: Root-level things the blocks depend on, added to the layout: `page_styles` (a list of page styles) and
            `variables` (a list of variable definitions). A name the layout already uses is reused when identical, and
            otherwise a page style is renamed (the blocks' references follow) and a variable refused.
        parameters: What the person chooses on insert.
        formats: The output formats the result is true in (`html`, `pdf`, `docx`, `odt`), shown in the picker.
        layout_aware: Optional hook `(fragment, values, tree, image_aspect) -> None` that adjusts the fragment to the layout
            it goes into (the page's width, a picture's shape) before the value targets are filled. Built-in snippets only.
    """

    key: str
    name: str
    description: str
    category: str
    blocks: tuple[dict[str, Any], ...]
    family: str = "document"
    root: Mapping[str, Any] = field(default_factory=dict)
    parameters: tuple[ReportSnippetParameter, ...] = ()
    formats: tuple[str, ...] = ("html", "pdf", "docx", "odt")
    layout_aware: Callable[..., None] | None = None


@dataclass(frozen=True)
class ReportDefinition:
    """Declares one report a module contributes (see docs/modules.md,
    "Reports"). Core generates the routes (`?format=json|pdf|csv`), access
    gating, parameter validation, MCP tool and catalogue entry from this; the
    module supplies only the `collector`.

    Attributes:
        key: Short stable key, unique within the module (e.g. `"r1"`).
        slug: URL segment under the module's `/reports/` prefix
            (`[a-z][a-z0-9-]*`), unique within the module.
        title: Display title.
        description: One line shown in the catalogue and to MCP clients.
        subcomponent: A key of the module's own `sub_components` that must be
            enabled for the report to be offered, or `None` when only the
            module itself must be enabled (the collector then reports
            `eligible_projects` itself).
        any_subcomponents: Keys of the module's own `sub_components` for a report that spans several of them (a
            summary of Strategy, Future State and Guiding Principles): it is offered while at least one is enabled and
            hidden once every one is off. Exclusive with `subcomponent`.
        org_level: Whether an organisation-wide variant exists.
        org_role_key: The org-scoped `ModuleRoleDefinition.role_key` of this
            module a caller must hold to run the organisation-wide variant.
            Required when `org_level` (an aggregate across projects is never
            gated by project access alone).
        org_scope: Which projects an organisation-wide run covers:
            `"readable_projects"` (the default, only projects the caller holds
            a project role on) or `"all_org_projects"` (every project in the
            organisation, for a role whose purpose is cross-project oversight).
            The wider choice is explicit and only meaningful with an
            `org_role_key`.
        params: Typed query parameters (see `ReportParamDefinition`).
        collector: `(db, ReportContext) -> ReportResult`. Must treat
            `ctx.projects` as the whole in-scope set and never widen it.
        record_types: The registered artefact types whose records the report
            names in its rows. Every such cell shows the record's code through
            `ReportContext.code` / `ReportContext.org_code` and the row's tags
            through `ReportContext.tag_text`, never a hand-formatted code; the
            declaration lets a test prove each type is registered and coded.
        view_only: True for a report meant to be read on screen and not downloaded as a file (a summary pack). A record
            list's "Download report" does not offer it; the Reports dialog still shows it, and its `parts` stay
            available as widgets.
        cell_tones: Badge colours for the PDF and Word output, by column heading: `{"Status": {"Approved": "accent"}}`
            tones every cell under a column headed "Status" whose text is a listed label, in every section of the
            report, as the screen's badge does. Build the inner maps with `report_framework.tones_by_label` from the
            module's label and tone maps. A cell whose text is not listed is left plain. Ratings are toned by the
            collector (`ReportSection.tones`), which wins over this.
        usual_widths: A usual width by column heading (`{"Priority": "8%", "Due": "9%"}`: `30%`, `4 cm` or `40 mm`) for
            a column whose content has a predictable size, in every table of the report. It sizes the report's tables
            when a custom report layout embeds them (a widget): those columns take the width, the others share the
            rest by content, and tables with the same headings still line up. A heading a table lacks is ignored.
            Only headings that a section of the report really has may be declared (`report_framework.unknown_usual_widths`
            checks a collected report in the module's tests).
        parts: The report's tables a custom report layout can embed one at a time (widgets), by the
            `ReportSection.key` the collector gives them. Declare every table whose key is fixed; a table whose
            key depends on the data is not embeddable. Every report also offers `figures` (its headline figures)
            and `notes` (its caveats) without declaring them.
        record_order: How the report orders the records it lists, `"code"` (default) or `"title"`, ascending, never the
            order a list on screen was sorted to. The collector reads it through `ReportContext.order_records`. A table
            that is a ranking on purpose (highest score first) keeps its ranking and is marked `# ranked:` in the collector.
    """

    key: str
    slug: str
    title: str
    description: str
    collector: Callable[[Session, ReportContext], ReportResult]
    subcomponent: str | None = None
    any_subcomponents: tuple[str, ...] = field(default=())
    org_level: bool = False
    org_role_key: str | None = None
    org_scope: Literal["readable_projects", "all_org_projects"] = "readable_projects"
    params: tuple[ReportParamDefinition, ...] = field(default=())
    record_types: tuple[str, ...] = field(default=())
    view_only: bool = False
    cell_tones: Mapping[str, Mapping[str, str]] = field(default_factory=dict, compare=False)
    usual_widths: Mapping[str, str] = field(default_factory=dict, compare=False)
    parts: tuple[ReportPartDefinition, ...] = field(default=())
    record_order: Literal["code", "title"] = "code"


@dataclass(frozen=True)
class PrincipalReference:
    """A column pair on a module's own model that holds a principal (a user,
    an organisation group or a project group — `services.principals`).

    Declared via `ModuleDefinition.principal_references` so core can answer
    "what still names this group?" without importing the module: deleting a
    group is blocked while anything names it, and offers to reassign (a
    mandatory field) or clear (an optional one).

    Attributes:
        model: The mapped class; it needs an `id` primary key and the columns
            `<field>_type` and `<field>_id` (`models.principal` helpers).
        field: Base name of the pair (`owner` for `owner_type`/`owner_id`).
        label: Plural noun for what the rows are, shown in the in-use dialog
            ("decision owners").
        audit_entity_type: `AuditEvent.entity_type` for the record, used when a
            reassignment or clear is audited per row.
        mandatory: True when the field cannot be left empty, so deletion needs a replacement.
        live_filter: Optional zero-argument callable returning a SQL condition that
            selects the rows that are current. Rows it excludes (older versions of
            a versioned record) are neither counted nor changed on deletion; they
            keep the group's id and display as a deleted group. Omit when every row is current.
        record_id_field: Column holding the id of the record the audit event is about, for a
            versioned record whose rows are versions (`"persona_id"`). Defaults to the row's own `id`.
        multi_valued: True when each row is one *entry* of a list field (a record's facilitators:
            one row per person, with `record_id_field` naming the record), not a slot on the record.
            Clearing then deletes the row, and a reassignment whose replacement is already on the same
            record deletes the row instead of creating a duplicate.
    """

    model: type[DeclarativeBase]
    field: str
    label: str
    audit_entity_type: str
    mandatory: bool = False
    live_filter: Callable[[], Any] | None = None
    record_id_field: str = "id"
    multi_valued: bool = False


@dataclass(frozen=True)
class ModuleDefinition:
    """Declares a single module, first-party or third-party, to the registry.

    Attributes:
        key: Stable unique identifier (e.g. `"compliance"`); it is the
            `module_key` column value in the entitlement and enablement tables,
            so it never changes once data is keyed on it.
        name: Display name shown in admin UIs.
        description: Short description shown in admin UIs.
        version: The module's own version string, logged at discovery.
        default_enabled: Whether an entitled organisation with no explicit
            `OrganizationModuleEnablement` row has the module enabled.
        implemented: Whether the module does anything yet; admin UIs show an
            unimplemented entry rather than hiding it.
        get_router: Zero-argument callable returning the org-scoped `APIRouter`
            (`/api/v1/orgs/{organization_id}/modules/<key>/...`), or `None`.
            Called lazily so a module can defer import-time work.
        get_project_router: Like `get_router`, for project-scoped endpoints
            (`/api/v1/projects/{project_id}/modules/<key>/...`), so an MCP tool
            can declare `project_id` as its only path parameter.
        get_global_router: Like `get_router`, for a path root with neither
            placeholder. Its routes resolve organisation or project access
            themselves (`services.rbac.require_org_access_and_module_enabled`).
            `app.main` mounts all three routers with no extra gate;
            `build_mcp_tool_manifest` accepts a tool path under any of them.
        roles: `ModuleRoleDefinition`s, synced into `module_role_definitions` at
            startup (`sync_module_role_definitions`).
        frontend_manifest: A `ModuleFrontendManifest`, or `None`. Read through
            `get_frontend_manifest`, which enforces the Tier B origin allowlist.
        mcp_tools: `McpToolDefinition`s that `build_mcp_tool_manifest` verifies
            against real routes and turns into the manifest `mcp-server` consumes.
        models_import_path: Dotted path to the module's ORM models, imported by
            `import_all_module_models` so `Base.metadata` includes its tables.
            Importing registers table shapes only; it applies nothing to a database.
        migrations_dir: Path relative to `backend/` of the module's Alembic
            revision scripts, added to Alembic's `version_locations`
            (`configure_alembic_version_locations`). Alembic still builds one
            linear revision graph from each file's `down_revision`; honoured for
            any module in the live registry.
        migrations_import_path: Dotted path to a module exposing
            `run_migrations(connection)`, applied outside the Alembic chain by
            `apply_external_module_migrations` after `alembic upgrade head`.
            Honoured only for externally discovered modules (never for
            `INSTALLED_MODULES`, whose schema changes go through `migrations_dir`).
            It is untracked, so it must be idempotent.
        resolve_file_owner_project_id: Optional `(db, file_id) -> project id | None`
            hook letting `GET /api/v1/files/{id}` authorise the module's files
            without importing it; `resolve_module_file_project_id` tries each
            module in registry order.
        scheduled_jobs: `ModuleScheduledJob`s registered by
            `services.scheduler.start_scheduler`, id-prefixed with `key`.
        org_bundle_hooks / no_org_bundle: `ModuleOrgBundleHooks` for the
            organisation bundle (`services.org_export`), or the reason there are none.
        project_bundle_hooks / no_project_bundle: `ModuleProjectBundleHooks` for
            the project bundle (`services.project_export`), or the reason there
            are none. A backend test fails for a module with neither.
        on_org_created: Optional `(db, organization_id)` hook run by
            `run_on_org_created_hooks` right after a new `Organization` row is
            flushed, so core never imports a module to seed its org defaults.
            It adds rows and never commits. There is no "on module enabled" hook:
            enablement is a row toggle, and creation time is the one point that
            cannot race or double-seed.
        org_creation_choices: `OrgCreationChoiceOption`s offered on the
            organisation-creation form (opt-in seeding, unlike `on_org_created`),
            read via `get_org_creation_choices`/`default_org_creation_choice_keys`.
        on_org_created_with_choices: Optional `(db, organization_id, selected_keys)`
            hook run alongside `on_org_created` for modules with choices;
            `selected_keys` spans every module, so filter to this module's own.
        project_nav_visible: Optional `(db, project) -> bool` hook that hides an
            already-enabled project nav entry (Compliance hides it until its
            organisation has a published standard version). `None` means always visible.
        on_project_created: Optional `(db, project, actor_id)` hook run by
            `run_on_project_created_hooks` right after a new `Project` row is
            flushed; `actor_id` is the project's creator. It adds rows and never commits.
        validate_org_group_member_removal: Optional `(db, org_group_id,
            member_user_id)` hook run before a user member is removed from an
            `OrgGroup`; returns a block message (the endpoint answers 400) or `None`.
        validate_org_group_deletion: Optional `(db, org_group_id)` hook run
            before an organisation group is deleted; same return contract.
        artefact_ids_in_organization: Optional `(db, organization_id)` returning
            the ids of this module's artefacts in the organisation, so
            `services.org_deletion` removes their polymorphic links, comments
            and subscriptions.
        artefact_types: The module's linkable artefact type strings, merged with
            the core types by `get_all_registered_artefact_types` and validated by
            `services.relationships.create_link`; `ArtefactLink` columns are plain
            strings, so no core enum is edited per module.
        subtype_providers: Maps an artefact type to `(db, organization_id) ->
            list[str]` returning the organisation's valid permission sub-types
            (e.g. Decision Type names); the registry holds the lookup, not the
            values (`get_subtype_providers`/`get_subtypes`).
        entity_scopes: Maps a module-owned `ModuleRoleDefinition.scope` to an
            `EntityScopeDefinition`, so custom roles and `app.services.rbac`
            can resolve and enumerate it.
        sub_components: Independently toggleable `ModuleSubComponentDefinition`s,
            resolved by `is_module_subcomponent_enabled`/`is_org_module_subcomponent_enabled`.
        scoring_schemes: Scoring schemes registered into `app.services.scoring`,
            merged by `get_all_registered_scoring_schemes`.
        scoring_target_providers: Maps an artefact type to `(db, project_id) ->
            list[ScoringTarget]` so one module scores against another's records
            without importing it (`get_scoring_targets`; `[]` when the owning
            module is disabled).
        demand_party_providers: Maps an artefact type to `(db, project_id, ids) ->
            {id: [DemandParty]}` giving the weighted parties each record stands
            for (`resolve_demand_parties`; `{}` when the owning module is disabled).
        artefact_summary_providers: Maps an artefact type to an
            `ArtefactSummaryProvider` (`get` + `list_for_project`) so other
            modules can validate, label and pick its records as link targets
            (`get_artefact_summary`/`list_artefact_summaries`).
        artefact_type_labels: Maps an artefact type to its singular display name
            (`get_artefact_type_label`); a missing type gets a title-cased fallback.
        default_code_prefixes: Maps an artefact type to its default `PREFIX-nnn`
            prefix (2 to 5 capitals). Organisations and projects may choose
            another (`services.code_prefixes`). Required of every type.
        no_code_prefix: `{type: reason}` for a type with no code.
        search_providers / not_searchable: `ArtefactSearchProvider`s making
            records findable by the global search, or the reason a type is not.
        markdown_fields / plain_text_fields: Long text columns whose value is
            Markdown, or `{"table.column": reason}` for those that stay plain.
            A backend test fails for an undeclared long-text column.
        activity_action_kinds: `{audit action: kind}` classifying this module's
            actions for the History page's Event filter; omitted actions show as Other.
        activity_link_ends: `{audit entity type: reader}` for each `*_link` event
            logged outside the generic link table; the reader returns the two
            joined records from the event `detail`.
        activity_metadata_types: `{audit entity type: group}` for logged entity
            types that are not artefact types, so the History Type filter lists
            them under `links`, `tags`, `access` or `structure`.
        search_scopes: `{scope key: SearchScope}` added to the search page's Scope
            filter, addressed as `<module_key>:<scope_key>:<ref_id>`; offered only
            where the module is on.
        report_fields / not_reportable: `ReportFieldProvider`s making records
            usable by custom report layouts, or the reason a type is not.
        record_attachments / no_record_attachments: `RecordAttachmentProvider`s
            for a report's record-images block (`get_record_attachment_providers`),
            or the reason a reportable type has none.
        report_starter_sections: `ReportStarterSection`s this module supplies to
            the starter report layouts (`get_report_starter_sections`).
        report_snippets: `ReportSnippet`s the report designer can insert, offered
            only where the module is on (`get_report_snippets`).
        record_tables / not_importable: `RecordTableProvider`s making a type's
            list exportable (CSV, PDF, Word) and, where the provider has
            `create`/`update`, importable. Export has no exemption; a type that
            cannot be imported gives its reason.
        record_comments: Maps an artefact type to a `RecordCommentProvider` giving
            its records the generic comments (`get_record_comment_providers`).
        baseline_snapshots: Maps an artefact type to a `BaselineSnapshotProvider`
            so its records are captured in project baselines; none means not part of baselines.
        not_placeable: `{type: reason}` for a type that cannot sit in the
            component/category tree; every other type uses `artefact_placements`.
        not_creatable_from_links: `{type: reason}` for a type a person cannot
            author, so the Links panel never offers "Create new" for it.
        perf_generators / no_perf_generator: `PerfDatasetGenerator`s scaling a
            type's records in the performance tiers, or the reason there is none.
        scaling_probes / no_scaling_probe: `ScalingProbe`s the scaling-shape guard
            uses, or the reason a type cannot be filled through the API.
        lifecycles: Maps an artefact type to its `LifecycleDefinition`; the type's transition functions call
            `services.lifecycles.check_move`, so a project's turned-off states and an organisation's required states
            apply on the server. A type with none keeps its fixed path.
        overview_metrics / overview_widgets: `OverviewMetric`s (served as
            `<module_key>:<key>`) and `OverviewWidgetType`s for project overviews;
            evaluated only where the module is enabled.
        org_overview_metrics / org_overview_widgets: The same for organisation
            dashboards; `evaluate(ctx, params)` receives an `OrgMetricContext`.
        reports: `ReportDefinition`s; the module mounts the routers from
            `report_framework.build_report_routers` and may expose `report_mcp_tools`.
            Definitions failing `validate_report_definitions` are excluded and logged.
        link_type_seeds: `LinkTypeSeed`s created lazily when absent (seeds sharing
            a `forward_name` merge, `get_all_link_type_seeds`). Any two types are
            linkable by default; seeds only ship vocabulary.
        notification_types: `NotificationTypeDefinition`s this module sends,
            merged by `get_all_notification_types` so core's enum stays closed.
        notification_targets: `{type key: ordered target kinds}` for types the
            module owns but core's enum defines.
        notification_target_kinds: Target kinds only this module's frontend can open.
        on_artefact_changed: Optional `(db, ArtefactChange)` hook called inside the
            changing request's transaction (never commit) when any artefact changes
            (`services.artefact_changes.notify_artefact_changed`), so a module can
            react to another module's change without importing it. Keep it cheap.
        principal_references: `PrincipalReference`s for columns holding a principal,
            so core can block deleting a group that owns records and reassign
            them. Actor fields (`created_by`) are not principals.
        mcp_guidance: Markdown guidance for AI agents on this module's MCP tools,
            embedded in the generated `module-tools.md`; required when the module
            declares MCP tools. Omit per-tool parameter lists.
        administrative_permissions: `ModuleAdministrativePermission`s: bare permission atoms the module adds to the
            vocabulary, held by the organisation and project roles each names (`get_module_administrative_permissions`).
            Core's `ADMINISTRATIVE_PERMISSIONS` never names a module's atom.
        record_subtypes: Maps an artefact type (any registered type, including a core one the module gives a sub-type)
            to a `RecordSubtypeResolver` returning each record's sub-type key, so a rule or policy can say "a
            Verification action" without core knowing the module (`resolve_record_subtypes`).
        review_adapters: Maps an artefact type to the `ReviewAdapter` the review engine reads its schedule through.
        baseline_check_providers: `BaselineCheckProvider`s run before a baseline is taken
            (`services.governance_seams.baseline_checks_for_project`).
        policy_resolvers: `PolicyResolver`s answering which policy applies at each core `GovernanceSeam`
            (`services.governance_seams.resolve_policy`).
        profile_contributors: `ProfileContributor`s: tables of policy rows a governance profile can own, counted, exported
            and imported by the profile mechanism without per-table code (`get_profile_contributors`).
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
    mcp_guidance: str = ""
    models_import_path: str | None = None
    migrations_dir: str | None = None
    migrations_import_path: str | None = None
    get_project_router: Callable[[], APIRouter | None] | None = None
    get_global_router: Callable[[], APIRouter | None] | None = None
    resolve_file_owner_project_id: Callable[[Session, uuid.UUID], uuid.UUID | None] | None = None
    scheduled_jobs: tuple[ModuleScheduledJob, ...] = field(default=())
    org_bundle_hooks: ModuleOrgBundleHooks | None = None
    no_org_bundle: str | None = None
    project_bundle_hooks: ModuleProjectBundleHooks | None = None
    no_project_bundle: str | None = None
    on_org_created: Callable[[Session, uuid.UUID], None] | None = None
    org_creation_choices: tuple[OrgCreationChoiceOption, ...] = field(default=())
    on_org_created_with_choices: Callable[[Session, uuid.UUID, frozenset[str]], None] | None = None
    project_nav_visible: Callable[[Session, Project], bool] | None = None
    on_project_created: Callable[[Session, Project, uuid.UUID], None] | None = None
    validate_org_group_member_removal: Callable[[Session, uuid.UUID, uuid.UUID], str | None] | None = None
    validate_org_group_deletion: Callable[[Session, uuid.UUID], str | None] | None = None
    artefact_types: tuple[str, ...] = field(default=())
    artefact_ids_in_organization: Callable[[Session, uuid.UUID], set[uuid.UUID]] | None = None
    subtype_providers: dict[str, Callable[[Session, uuid.UUID], list[str]]] = field(default_factory=dict)
    entity_scopes: dict[str, EntityScopeDefinition] = field(default_factory=dict)
    sub_components: tuple[ModuleSubComponentDefinition, ...] = field(default=())
    scoring_schemes: tuple[ScoringSchemeDefinition, ...] = field(default=())
    scoring_target_providers: dict[str, Callable[[Session, uuid.UUID], list[ScoringTarget]]] = field(
        default_factory=dict
    )
    demand_party_providers: dict[
        str, Callable[[Session, uuid.UUID, Sequence[uuid.UUID]], dict[uuid.UUID, list[DemandParty]]]
    ] = field(default_factory=dict)
    artefact_summary_providers: dict[str, ArtefactSummaryProvider] = field(default_factory=dict)
    artefact_type_labels: dict[str, str] = field(default_factory=dict)
    reports: tuple[ReportDefinition, ...] = field(default=())
    link_type_seeds: tuple[LinkTypeSeed, ...] = field(default=())
    notification_types: tuple[NotificationTypeDefinition, ...] = field(default=())
    notification_targets: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notification_target_kinds: tuple[str, ...] = field(default=())
    on_artefact_changed: Callable[[Session, ArtefactChange], None] | None = None
    principal_references: tuple[PrincipalReference, ...] = field(default=())
    default_code_prefixes: dict[str, str] = field(default_factory=dict)
    no_code_prefix: dict[str, str] = field(default_factory=dict)
    search_providers: dict[str, ArtefactSearchProvider] = field(default_factory=dict)
    not_searchable: dict[str, str] = field(default_factory=dict)
    markdown_fields: tuple[MarkdownField, ...] = field(default=())
    plain_text_fields: dict[str, str] = field(default_factory=dict)
    activity_action_kinds: dict[str, str] = field(default_factory=dict)
    activity_link_ends: dict[str, ActivityLinkEndsReader] = field(default_factory=dict)
    activity_metadata_types: dict[str, str] = field(default_factory=dict)
    search_scopes: dict[str, SearchScope] = field(default_factory=dict)
    report_fields: dict[str, ReportFieldProvider] = field(default_factory=dict)
    not_reportable: dict[str, str] = field(default_factory=dict)
    record_attachments: dict[str, RecordAttachmentProvider] = field(default_factory=dict)
    no_record_attachments: dict[str, str] = field(default_factory=dict)
    report_starter_sections: tuple[ReportStarterSection, ...] = field(default=())
    report_snippets: tuple[ReportSnippet, ...] = field(default=())
    record_tables: dict[str, RecordTableProvider] = field(default_factory=dict)
    not_importable: dict[str, str] = field(default_factory=dict)
    not_creatable_from_links: dict[str, str] = field(default_factory=dict)
    not_placeable: dict[str, str] = field(default_factory=dict)
    record_comments: dict[str, RecordCommentProvider] = field(default_factory=dict)
    baseline_snapshots: dict[str, BaselineSnapshotProvider] = field(default_factory=dict)
    perf_generators: dict[str, PerfDatasetGenerator] = field(default_factory=dict)
    scaling_probes: dict[str, ScalingProbe] = field(default_factory=dict)
    lifecycles: dict[str, LifecycleDefinition] = field(default_factory=dict)
    no_scaling_probe: dict[str, str] = field(default_factory=dict)
    no_perf_generator: dict[str, str] = field(default_factory=dict)
    overview_metrics: dict[str, OverviewMetric] = field(default_factory=dict)
    overview_widgets: dict[str, OverviewWidgetType] = field(default_factory=dict)
    org_overview_metrics: dict[str, OverviewMetric] = field(default_factory=dict)
    org_overview_widgets: dict[str, OverviewWidgetType] = field(default_factory=dict)
    administrative_permissions: tuple[ModuleAdministrativePermission, ...] = field(default=())
    record_subtypes: dict[str, RecordSubtypeResolver] = field(default_factory=dict)
    review_adapters: dict[str, ReviewAdapter] = field(default_factory=dict)
    baseline_check_providers: tuple[BaselineCheckProvider, ...] = field(default=())
    policy_resolvers: tuple[PolicyResolver, ...] = field(default=())
    profile_contributors: tuple[ProfileContributor, ...] = field(default=())

    def __post_init__(self) -> None:
        """Rejects a sub-component `requires` list that names an unknown key, the sub-component itself or forms a cycle,
        and a registration that names a sub-component the module does not declare.

        Raises:
            ValueError: On the first problem found, naming the module and key.
        """
        declared = {sub.key: sub for sub in self.sub_components}
        for sub in self.sub_components:
            for needed in sub.requires:
                if needed == sub.key:
                    raise ValueError(f"Module {self.key!r}: sub-component {sub.key!r} cannot require itself.")
                if needed not in declared:
                    raise ValueError(f"Module {self.key!r}: sub-component {sub.key!r} requires unknown {needed!r}.")
        for sub in self.sub_components:
            if _requires_cycle(declared, sub.key):
                raise ValueError(f"Module {self.key!r}: sub-component {sub.key!r} is part of a requires cycle.")
        named = [(p.sub_component, "policy resolver") for p in self.policy_resolvers]
        named += [(c.sub_component, f"baseline check {c.key!r}") for c in self.baseline_check_providers]
        named += [(c.sub_component, f"profile contributor {c.key!r}") for c in self.profile_contributors]
        for sub_key, what in named:
            if sub_key is not None and sub_key not in declared:
                raise ValueError(f"Module {self.key!r}: {what} names undeclared sub-component {sub_key!r}.")
        check_keys = [c.key for c in self.baseline_check_providers]
        if len(set(check_keys)) != len(check_keys):
            raise ValueError(f"Module {self.key!r}: duplicate baseline check key.")
        contributor_keys = [c.key for c in self.profile_contributors]
        if len(set(contributor_keys)) != len(contributor_keys):
            raise ValueError(f"Module {self.key!r}: duplicate profile contributor key.")
        atom_keys = [a.key for a in self.administrative_permissions]
        if len(set(atom_keys)) != len(atom_keys):
            raise ValueError(f"Module {self.key!r}: duplicate administrative permission key.")


def _requires_cycle(declared: Mapping[str, ModuleSubComponentDefinition], start: str) -> bool:
    """Whether following `requires` from `start` returns to `start`."""
    seen: set[str] = set()
    stack = list(declared[start].requires)
    while stack:
        key = stack.pop()
        if key == start:
            return True
        if key in seen or key not in declared:
            continue
        seen.add(key)
        stack.extend(declared[key].requires)
    return False


# First-party modules, always loaded regardless of `allow_external_modules`.
# Empty here because their `module.py` files import `ModuleDefinition` from
# this module; `app/modules/__init__.py` appends them afterwards.
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

    Loads `INSTALLED_MODULES` first (logged at `INFO`, `source=installed`).
    Only when `Settings.allow_external_modules` is `True` does it discover
    entry-point modules and, if `Settings.extra_modules_path` is set,
    path-based ones; otherwise neither discovery function is called and one
    `INFO` line records that discovery was skipped. An external module whose
    `key` is already registered is skipped with a `WARNING`: installed modules
    win, then the first external claimant.

    Args:
        force: Rebuild instead of using the process cache (for tests that
            patch `INSTALLED_MODULES`, the setting or the discovery functions).

    Returns:
        A mapping of `module_key -> ModuleDefinition` for the merged registry.
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


@scoped_memo
def is_module_entitled(db: Session, organization_id: uuid.UUID, module_key: str) -> bool:
    """Resolves whether `organization_id` is entitled to use `module_key` (the
    server-tier licensing lever): an explicit `OrganizationModuleEntitlement`
    row is authoritative, else the deployment-wide
    `ServerSettings.default_module_entitlement_policy`, else `True` when no
    `ServerSettings` row exists yet (early bootstrap).

    Args:
        db: An active database session.
        organization_id: The organisation to resolve entitlement for.
        module_key: The module's registry key.

    Returns:
        `True` if the organisation is entitled to the module.
    """
    # Deferred import: avoids an unnecessary top-level coupling for a registry
    # whose other functions do not need `app.models.organization`.
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


@scoped_memo
def is_module_enabled(db: Session, organization_id: uuid.UUID, module_key: str) -> bool:
    """Resolves the *effective* enabled state of `module_key` for
    `organization_id`: entitled(org, key) AND (org row `enabled` if present,
    else server default `org_enabled` if present, else registry `default_enabled`).

    Returns `False` without an enablement lookup when the module is not
    registered or the organisation is not entitled, so a disabled module is
    indistinguishable from a missing one (the RBAC dependencies answer 404).

    Args:
        db: An active database session.
        organization_id: The organisation to resolve enablement for.
        module_key: The module's registry key.

    Returns:
        `True` only if the module exists, the organisation is entitled and it
        is enabled (explicitly or by default).
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
    server_default = _server_module_default(db, module_key)
    if server_default is not None:
        return server_default.org_enabled
    return definition.default_enabled


@scoped_memo
def _server_module_default(db: Session, module_key: str):
    """Returns the `ServerModuleDefault` row for `module_key`, or `None` when
    the server has no explicit default for it (the registry's own
    `default_enabled` then applies)."""
    from app.models.module import ServerModuleDefault

    return db.scalar(select(ServerModuleDefault).where(ServerModuleDefault.module_key == module_key))


@scoped_memo
def resolve_default_project_enabled(db: Session, organization_id: uuid.UUID, module_key: str) -> bool:
    """Resolves the organisation-tier "default for a project with no override"
    value for `module_key`: an explicit
    `OrganizationModuleEnablement.default_project_enabled`, else
    `ServerModuleDefault.project_default_enabled`, else the registry's
    `default_enabled`.

    Not gated on `enabled`: the hard floor is checked by `is_module_enabled`
    and `is_module_enabled_for_project`, so call `is_module_enabled_for_project`
    for a real effective state.

    Args:
        db: An active database session.
        organization_id: The organisation to resolve the default for.
        module_key: The module's registry key.

    Returns:
        `True` if a project with no override gets this module on by default.
    """
    definition = get_module(module_key)
    if definition is None:
        return False

    from app.models.module import OrganizationModuleEnablement

    row = db.scalar(
        select(OrganizationModuleEnablement).where(
            OrganizationModuleEnablement.organization_id == organization_id,
            OrganizationModuleEnablement.module_key == module_key,
        )
    )
    if row is not None:
        return row.default_project_enabled
    server_default = _server_module_default(db, module_key)
    if server_default is not None:
        return server_default.project_default_enabled
    return definition.default_enabled


@scoped_memo
def _project_module_override(db: Session, project_id: uuid.UUID, module_key: str):
    """The project's own `ProjectModuleEnablement` row for `module_key`, or `None`."""
    from app.models.module import ProjectModuleEnablement

    return db.scalar(
        select(ProjectModuleEnablement).where(
            ProjectModuleEnablement.project_id == project_id,
            ProjectModuleEnablement.module_key == module_key,
        )
    )


@scoped_memo
def _project_subcomponent_override(db: Session, project_id: uuid.UUID, module_key: str, subcomponent_key: str):
    """The project's own `ProjectModuleSubComponentEnablement` row for one sub-component, or `None`."""
    from app.models.module import ProjectModuleSubComponentEnablement

    return db.scalar(
        select(ProjectModuleSubComponentEnablement).where(
            ProjectModuleSubComponentEnablement.project_id == project_id,
            ProjectModuleSubComponentEnablement.module_key == module_key,
            ProjectModuleSubComponentEnablement.subcomponent_key == subcomponent_key,
        )
    )


@scoped_memo
def is_module_enabled_for_project(db: Session, project_id: uuid.UUID, module_key: str) -> bool:
    """Resolves the *effective* enabled state of `module_key` for one project:

        effective = entitled AND org_hard_enabled AND
                    (project_override.enabled if a row exists else default_project_enabled)

    1. Entitlement and org hard enablement (`is_module_enabled`) are an absolute
       floor: if either is `False` the result is `False`, whatever a project row says.
    2. Above the floor, a project's own override row decides directly, in
       either direction (a project may turn on a module its organisation
       defaults off for new projects, or turn off one defaulted on).
    3. With no override, `resolve_default_project_enabled` is the state. Only
       a module registered after the project was created reaches this tier
       (projects get rows at creation, `snapshot_project_module_state`, and
       before an org default changes, `freeze_projects_module_default`).

    Write-time validation (`routers.projects.module_roles.update_project_module_enablement`)
    rejects `enabled=True` only when tier 1 is `False`. A stale override row is
    left in place; it never takes effect while tier 1 stays `False`.

    Returns `False` if `module_key` is unregistered or `project_id` does not
    resolve. `require_project_module_enabled(_dynamic)` and
    `is_module_subcomponent_enabled` call this, so a project-level whole-module
    override cascades to the module's sub-components.

    Args:
        db: An active database session.
        project_id: The project to resolve `module_key`'s state for.
        module_key: The module's registry key.

    Returns:
        The effective enabled state, per the formula above.
    """
    # Deferred import, same circular-import reason `is_module_subcomponent_
    # enabled` below documents on its own identical import.
    from app.services.rbac import _project_organization_id

    organization_id = _project_organization_id(db, project_id)
    if organization_id is None:
        return False
    if get_module(module_key) is None:
        return False

    # Tier 1: entitlement AND org hard enablement, already folded together
    # by `is_module_enabled` — an absolute floor no project override can
    # cross in either direction.
    if not is_module_enabled(db, organization_id, module_key):
        return False

    project_override = _project_module_override(db, project_id, module_key)
    if project_override is not None:
        # Floor already confirmed True above — a project's own choice is
        # symmetric from here: it may widen past the organisation's own
        # `default_project_enabled`, or narrow below it, either way.
        return project_override.enabled

    return resolve_default_project_enabled(db, organization_id, module_key)


def _find_subcomponent_definition(module_key: str, subcomponent_key: str) -> ModuleSubComponentDefinition | None:
    """Looks up one `ModuleSubComponentDefinition` by key off the registered
    module's own `ModuleDefinition.sub_components` — `None` if the module
    itself isn't registered, or is registered but never declared a
    sub-component with this key. Shared by `is_module_subcomponent_enabled`/
    `is_org_module_subcomponent_enabled` below."""
    definition = get_module(module_key)
    if definition is None:
        return None
    return next((s for s in definition.sub_components if s.key == subcomponent_key), None)


@scoped_memo
def resolve_org_subcomponent_state(
    db: Session, organization_id: uuid.UUID, module_key: str, subcomponent_key: str,
) -> tuple[bool, bool] | None:
    """Resolves the organisation-tier state of one sub-component — the
    same two-lever shape whole modules have (`enabled` hard floor +
    `default_project_enabled`), from an explicit
    `OrganizationModuleSubComponentDefault` row if one exists, else the
    registry's own `ModuleSubComponentDefinition.default_enabled` for both.

    Args:
        db: An active database session.
        organization_id: The organisation to resolve for.
        module_key: The declaring module's registry key.
        subcomponent_key: The sub-component's declared key.

    Returns:
        `(enabled, default_project_enabled)`, or `None` if the module or
        sub-component isn't registered.
    """
    subcomponent = _find_subcomponent_definition(module_key, subcomponent_key)
    if subcomponent is None:
        return None

    from app.models.module import OrganizationModuleSubComponentDefault

    row = db.scalar(
        select(OrganizationModuleSubComponentDefault).where(
            OrganizationModuleSubComponentDefault.organization_id == organization_id,
            OrganizationModuleSubComponentDefault.module_key == module_key,
            OrganizationModuleSubComponentDefault.subcomponent_key == subcomponent_key,
        )
    )
    if row is not None:
        return row.enabled, row.default_project_enabled
    return subcomponent.default_enabled, subcomponent.default_enabled


@scoped_memo
def is_module_subcomponent_enabled(
    db: Session, project_id: uuid.UUID, module_key: str, subcomponent_key: str,
) -> bool:
    """Resolves the *effective* enabled state of one project-scoped
    sub-component of `module_key`, in order (first that applies wins):

    1. Whole module disabled for this project (`is_module_enabled_for_project`)
       -> `False`; a disabled module cascades to every sub-component.
    2. The organisation's hard floor (`resolve_org_subcomponent_state`'s
       `enabled`) is `False` -> `False`; no project value can cross it.
    2b. The sub-component is `organization_only` -> the organisation's state; no project row or
        default is consulted.
    3. The project's own `ProjectModuleSubComponentEnablement` row. Projects
       get one at creation (`snapshot_project_module_state`) and before an org
       default changes (`freeze_projects_subcomponent_default`).
    4. No project row -> the organisation's `default_project_enabled`.
    5. Whatever the result of 2b to 4, `False` while any sub-component it `requires` is not in effect.

    Unregistered keys resolve to `False`, not an error.

    Args:
        db: An active database session.
        project_id: The project to resolve this sub-component's state for.
        module_key: The declaring module's registry key.
        subcomponent_key: The key declared in `ModuleDefinition.sub_components`.

    Returns:
        The effective enabled state.
    """
    if not is_module_enabled_for_project(db, project_id, module_key):
        return False
    return _project_subcomponent_in_effect(db, project_id, module_key, subcomponent_key)


def _project_subcomponent_in_effect(
    db: Session, project_id: uuid.UUID, module_key: str, subcomponent_key: str,
) -> bool:
    """Steps 2 to 5 of `is_module_subcomponent_enabled`: a sub-component's state in a project whose module is on, with
    the module-level switch left out so a requirement can be reported separately from it."""
    # Deferred import: `app.services.rbac` imports this module at load time;
    # reuses its project -> organisation resolution helper.
    from app.services.rbac import _project_organization_id

    organization_id = _project_organization_id(db, project_id)
    if organization_id is None:
        return False
    definition = _find_subcomponent_definition(module_key, subcomponent_key)
    org_state = resolve_org_subcomponent_state(db, organization_id, module_key, subcomponent_key)
    if definition is None or org_state is None:
        return False
    org_enabled, org_default_project_enabled = org_state
    if not org_enabled:
        return False

    if definition.organization_only:
        own = True
    else:
        project_override = _project_subcomponent_override(db, project_id, module_key, subcomponent_key)
        own = project_override.enabled if project_override is not None else org_default_project_enabled
    return own and not unmet_subcomponent_requirements(db, project_id, module_key, subcomponent_key)


def unmet_subcomponent_requirements(
    db: Session, project_id: uuid.UUID, module_key: str, subcomponent_key: str,
) -> list[ModuleSubComponentDefinition]:
    """The sub-components `subcomponent_key` `requires` that are not in effect in the project, in declaration order.
    The module-level switch is not counted, so a switched-off module reports none.

    Args:
        db: An active database session.
        project_id: The project to resolve for.
        module_key: The declaring module's registry key.
        subcomponent_key: The sub-component whose requirements are checked.

    Returns:
        The unmet requirements; empty when it requires nothing, all are in effect or the key is unregistered.
    """
    definition = _find_subcomponent_definition(module_key, subcomponent_key)
    if definition is None:
        return []
    unmet: list[ModuleSubComponentDefinition] = []
    for key in definition.requires:
        needed = _find_subcomponent_definition(module_key, key)
        if needed is not None and not _project_subcomponent_in_effect(db, project_id, module_key, key):
            unmet.append(needed)
    return unmet


def is_org_module_subcomponent_enabled(
    db: Session, organization_id: uuid.UUID, module_key: str, subcomponent_key: str,
) -> bool:
    """Org-scoped sibling of `is_module_subcomponent_enabled`, for a
    sub-component of an **org-scoped** artefact (e.g. Context & Strategy's
    org-level Strategy records), which has no project tier at all. The
    organisation's own hard `enabled` lever is the effective value; its
    `default_project_enabled` only matters for projects. A sub-component it `requires` that is not in effect
    makes it not in effect.

    Args:
        db: An active database session.
        organization_id: The organisation to resolve this sub-component's
            state for.
        module_key: The declaring module's registry key.
        subcomponent_key: The sub-component's declared key.

    Returns:
        `False` if the whole module is disabled/unregistered or the key is
        unregistered, else the org's `enabled` for this sub-component.
    """
    if not is_module_enabled(db, organization_id, module_key):
        return False
    return _org_subcomponent_in_effect(db, organization_id, module_key, subcomponent_key)


def _org_subcomponent_in_effect(
    db: Session, organization_id: uuid.UUID, module_key: str, subcomponent_key: str,
) -> bool:
    """The organisation tier of a sub-component with the module-level switch left out: its `enabled` lever and every
    requirement in effect."""
    org_state = resolve_org_subcomponent_state(db, organization_id, module_key, subcomponent_key)
    return (
        org_state is not None
        and org_state[0]
        and not unmet_org_subcomponent_requirements(db, organization_id, module_key, subcomponent_key)
    )


def unmet_org_subcomponent_requirements(
    db: Session, organization_id: uuid.UUID, module_key: str, subcomponent_key: str,
) -> list[ModuleSubComponentDefinition]:
    """The organisation-tier counterpart of `unmet_subcomponent_requirements`: the requirements of `subcomponent_key`
    that the organisation has switched off or that are themselves waiting on one."""
    definition = _find_subcomponent_definition(module_key, subcomponent_key)
    if definition is None:
        return []
    unmet: list[ModuleSubComponentDefinition] = []
    for key in definition.requires:
        needed = _find_subcomponent_definition(module_key, key)
        if needed is not None and not _org_subcomponent_in_effect(db, organization_id, module_key, key):
            unmet.append(needed)
    return unmet


def report_enabled_for_project(db: Session, project_id: uuid.UUID, module_key: str, report: ReportDefinition) -> bool:
    """Whether `report` is offered on a project: its module is enabled and, when it declares a sub-component, that one
    is (`subcomponent`) or at least one of those it spans is (`any_subcomponents`)."""
    if not is_module_enabled_for_project(db, project_id, module_key):
        return False
    if report.subcomponent:
        return is_module_subcomponent_enabled(db, project_id, module_key, report.subcomponent)
    if report.any_subcomponents:
        return any(is_module_subcomponent_enabled(db, project_id, module_key, key) for key in report.any_subcomponents)
    return True


def report_enabled_for_organization(db: Session, organization_id: uuid.UUID, module_key: str, report: ReportDefinition) -> bool:
    """Organisation-level twin of `report_enabled_for_project`."""
    if not is_module_enabled(db, organization_id, module_key):
        return False
    if report.subcomponent:
        return is_org_module_subcomponent_enabled(db, organization_id, module_key, report.subcomponent)
    if report.any_subcomponents:
        return any(is_org_module_subcomponent_enabled(db, organization_id, module_key, key) for key in report.any_subcomponents)
    return True


def _project_ids_without_row(db: Session, organization_id: uuid.UUID, row_model, **row_filters) -> list[uuid.UUID]:
    """Returns ids of `organization_id`'s projects that have no `row_model`
    row matching `row_filters` — the projects still reading an org default
    live. Shared by the two `freeze_*` helpers below."""
    from app.models.project import Project

    has_row = select(row_model.project_id).where(*(getattr(row_model, k) == v for k, v in row_filters.items()))
    return list(
        db.scalars(
            select(Project.id).where(Project.organization_id == organization_id, Project.id.not_in(has_row))
        )
    )


def snapshot_project_module_state(db: Session, project_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    """Copies the organisation's current project defaults into a newly created
    project: one `ProjectModuleEnablement` row per available module and one
    `ProjectModuleSubComponentEnablement` row per available sub-component. An
    org default affects only projects that get the module afterwards; an org
    hard Off still reaches every project through the floor checks.

    Only modules/sub-components the org has hard-on are copied: copying a
    default-off module while unavailable would leave the project without it
    once the org turns it on. Row-less projects read the live default until it
    changes (`freeze_projects_module_default`). Skips existing rows. Does not commit.

    Args:
        db: An active database session.
        project_id: The new project.
        organization_id: The project's owning organisation.
    """
    from app.models.module import ProjectModuleEnablement, ProjectModuleSubComponentEnablement

    existing_modules = set(
        db.scalars(select(ProjectModuleEnablement.module_key).where(ProjectModuleEnablement.project_id == project_id))
    )
    existing_subs = set(
        db.execute(
            select(ProjectModuleSubComponentEnablement.module_key, ProjectModuleSubComponentEnablement.subcomponent_key)
            .where(ProjectModuleSubComponentEnablement.project_id == project_id)
        ).tuples()
    )
    for definition in get_module_registry().values():
        if not is_module_enabled(db, organization_id, definition.key):
            continue
        if definition.key not in existing_modules:
            db.add(ProjectModuleEnablement(
                project_id=project_id, module_key=definition.key,
                enabled=resolve_default_project_enabled(db, organization_id, definition.key),
            ))
        for sub in definition.sub_components:
            if sub.organization_only:
                continue
            org_enabled, org_default_project_enabled = resolve_org_subcomponent_state(
                db, organization_id, definition.key, sub.key,
            )
            if org_enabled and (definition.key, sub.key) not in existing_subs:
                db.add(ProjectModuleSubComponentEnablement(
                    project_id=project_id, module_key=definition.key, subcomponent_key=sub.key,
                    enabled=org_default_project_enabled,
                ))


def freeze_projects_module_default(db: Session, organization_id: uuid.UUID, module_key: str) -> None:
    """Writes the organisation's *current* `default_project_enabled` for
    `module_key` into every one of its projects that has no row yet — call
    before changing that default, so existing projects keep their state
    (see `snapshot_project_module_state`). No-op while the module is
    hard-off for the org: no project is using the default then, so row-
    less projects should pick up whatever default applies once it's turned
    on. Does not commit.

    Args:
        db: An active database session.
        organization_id: The organisation whose default is about to change.
        module_key: The module's registry key.
    """
    from app.models.module import ProjectModuleEnablement

    if not is_module_enabled(db, organization_id, module_key):
        return
    current = resolve_default_project_enabled(db, organization_id, module_key)
    for project_id in _project_ids_without_row(db, organization_id, ProjectModuleEnablement, module_key=module_key):
        db.add(ProjectModuleEnablement(project_id=project_id, module_key=module_key, enabled=current))


def freeze_projects_subcomponent_default(
    db: Session, organization_id: uuid.UUID, module_key: str, subcomponent_key: str,
) -> None:
    """Sub-component sibling of `freeze_projects_module_default`; likewise
    a no-op while the module or sub-component is hard-off, or for an
    unregistered key. Does not commit.

    Args:
        db: An active database session.
        organization_id: The organisation whose default is about to change.
        module_key: The declaring module's registry key.
        subcomponent_key: The sub-component's declared key.
    """
    from app.models.module import ProjectModuleSubComponentEnablement

    org_state = resolve_org_subcomponent_state(db, organization_id, module_key, subcomponent_key)
    if org_state is None or not org_state[0] or not is_module_enabled(db, organization_id, module_key):
        return
    if (definition := _find_subcomponent_definition(module_key, subcomponent_key)) and definition.organization_only:
        return
    project_ids = _project_ids_without_row(
        db, organization_id, ProjectModuleSubComponentEnablement,
        module_key=module_key, subcomponent_key=subcomponent_key,
    )
    for project_id in project_ids:
        db.add(ProjectModuleSubComponentEnablement(
            project_id=project_id, module_key=module_key, subcomponent_key=subcomponent_key, enabled=org_state[1],
        ))


def import_all_module_models() -> None:
    """Imports every registered module's `models_import_path`, if declared, so
    `Base.metadata` includes its tables. `alembic/env.py` and `tests/conftest.py`
    call this instead of a per-module import line. Call it once, early, before
    `Base.metadata` is read.

    A module whose models fail to import is logged (`logger.exception`) and
    skipped, so one broken module does not abort the others.

    Trust boundary: this imports model classes for a module already in the live
    registry; it registers table shapes in-process and never touches a
    database. Schema changes reach a database through a reviewed Alembic
    revision (`configure_alembic_version_locations`) or, for an external
    module, the gated `apply_external_module_migrations`.
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
    """Points an Alembic `Config` at every registered module's `migrations_dir`
    in addition to the core `alembic/versions`, so a module's revisions live
    beside its code. Call once per freshly constructed `Config`, before any
    Alembic operation (`app.migrations.run_migrations` and `scripts/db.py` do),
    so a directory is declared only once, on the `ModuleDefinition`.

    Sets two options read when `ScriptDirectory.from_config` builds:
    - `version_locations`: the core directory, then each module's directory
      (skipping `None`), as absolute paths.
    - `path_separator`: `"os"`, required when more than one location is set.

    Only the directories modules declare are added, never a recursive scan of
    `app/modules/`: Alembic executes every `.py` file in a location, so a
    broad scan would execute `models.py`, `router.py` and the like.
    """
    core_versions_dir = _BACKEND_DIR / "alembic" / "versions"
    locations = [str(core_versions_dir)]
    for definition in get_module_registry().values():
        if not definition.migrations_dir:
            continue
        locations.append(str(_BACKEND_DIR / definition.migrations_dir))
    cfg.set_main_option("version_locations", os.pathsep.join(locations))
    cfg.set_main_option("path_separator", "os")


def apply_external_module_migrations(engine: Engine) -> None:
    """Applies every externally discovered module's schema changes through its
    `migrations_import_path`, so a module in `Settings.extra_modules_path` or
    installed as an entry-point package needs no edit to the core Alembic chain.
    Called once at startup (`app.migrations.run_migrations`) after
    `alembic upgrade head`.

    Gating is stricter than `import_all_module_models`:
    1. A no-op unless `Settings.allow_external_modules` is `True`.
    2. Only a module whose `key` is not in `INSTALLED_MODULES` is applied; a
       first-party module declaring the path is logged and skipped (it must
       ship a reviewed Alembic revision). Checked against the real list, not
       a self-declared field.

    Each module's `run_migrations(connection)` runs in its own transaction, so
    one failure rolls back only that module. A failure (an exception, an import
    error or a missing `run_migrations`) is logged and the module skipped;
    startup and other modules continue. `run_migrations` must be idempotent: it
    runs on every start and is not tracked against a revision history. Running
    an external module's SQL is only as safe as the operator's decision to
    enable `allow_external_modules`.

    Args:
        engine: The application's SQLAlchemy `Engine`; a connection is opened
            per qualifying module.
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
    """Mirrors every registered module's `ModuleRoleDefinition` entries into
    `module_role_definitions`, upserting on `(module_key, role_key)`. Called
    once at startup right after `run_bootstrap` in `app.main`'s `lifespan`.

    An existing row has its `name`/`description`/`scope` updated; a missing one
    is inserted. Rows are never deleted for a module or role no longer
    registered: a `UserModuleRole` grant must stay resolvable to a display name
    after a module is removed. `list_enabled_module_roles` decides which roles
    are offered, by registry membership and organisation enablement.

    Args:
        db: An active database session. Commits once at the end.
    """
    # Deferred import: avoids an unnecessary top-level coupling for a registry
    # whose other functions do not need `app.models.module_role`.
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
    """Returns `module_key`'s `ModuleFrontendManifest`, or `None` if it has none,
    the module is not registered, (Tier B) its `frame_url` origin is not in
    `Settings.module_frame_allowed_origins`, or (Tier C) it is declared by a
    first-party `INSTALLED_MODULES` entry, which may not use Tier C.

    The checks are mechanical, at the point of use, not trusted from the
    declaration. A rejected Tier B manifest is logged (`WARNING`) and treated
    as having no frontend integration; a first-party Tier C manifest is an
    authoring error, logged at `ERROR` and excluded the same way.

    Args:
        module_key: The module's registry key.

    Returns:
        The manifest if declared and (for `tier == "remote"`) allowlisted or (for
        `tier == "federated"`) discovered through the third-party pipeline;
        otherwise `None`.
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
        # No separate allowlist: a "federated" manifest only reaches this point
        # for a module from the `allow_external_modules`-gated discovery above.
        return manifest

    from urllib.parse import urlsplit

    frame = urlsplit(manifest.frame_url or "")
    origin = frame.scheme + "://" + frame.netloc
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
    """Tries every registered module's `resolve_file_owner_project_id` hook in
    registry order and returns the first non-`None` project id, so
    `app.routers.files.download_file` authorises module-owned files without
    importing a module. A module without the hook is skipped; two modules never
    legitimately claim one file, so first match wins.

    Args:
        db: An active database session.
        file_id: The `FileAsset` id being resolved.

    Returns:
        The owning project's id, or `None` if no hook recognises the file.
    """
    for definition in get_module_registry().values():
        if definition.resolve_file_owner_project_id is None:
            continue
        project_id = definition.resolve_file_owner_project_id(db, file_id)
        if project_id is not None:
            return project_id
    return None


def get_org_creation_choices() -> list[OrgCreationChoiceOption]:
    """Every registered module's `org_creation_choices`, in registry
    iteration order — the generic listing `app.routers.orgs`'s org-creation
    endpoints return so the org-creation form can render every module's
    optional seeding choices without importing any specific module."""
    options: list[OrgCreationChoiceOption] = []
    for definition in get_module_registry().values():
        options.extend(definition.org_creation_choices)
    return options


def default_org_creation_choice_keys() -> frozenset[str]:
    """The `key` of every `OrgCreationChoiceOption` marked
    `default_selected=True`, across every registered module — the implicit
    selection `run_on_org_created_hooks` applies when its caller doesn't
    pass `selected_choice_keys` at all, so a caller that predates this
    mechanism (`services.bootstrap.run_bootstrap`, any script/test calling
    `POST /orgs` without the new field) keeps getting the same seeding a
    human clicking through the org-creation form with nothing unchecked
    would get, rather than silently getting none of it."""
    return frozenset(option.key for option in get_org_creation_choices() if option.default_selected)


def run_on_org_created_hooks(
    db: Session, organization_id: uuid.UUID, selected_choice_keys: frozenset[str] | None = None
) -> None:
    """Calls every registered module's `on_org_created` hook, in registry
    order, right after a new `Organization` row is flushed, so core org creation
    (`routers.orgs.create_organization`, `services.bootstrap.run_bootstrap`)
    needs no specific module.

    Also calls every `on_org_created_with_choices` hook with the selected
    `OrgCreationChoiceOption` keys (`selected_choice_keys`, even if empty,
    else `default_org_creation_choice_keys()`), and seeds the default levels
    of every registered scoring scheme and the default external systems
    (generic core behaviour). A module with neither hook is skipped. Does not
    commit; the caller commits once for the whole transaction.

    Args:
        db: An active session, mid-transaction (the new `Organization` row
            must already be flushed so hooks can reference its id).
        organization_id: The newly created organisation's id.
        selected_choice_keys: The `OrgCreationChoiceOption.key`s explicitly
            chosen, or `None` to use every `default_selected` option (`None`,
            not an empty set, means "not specified").
    """
    from app.services.external_references import seed_org_defaults as seed_external_systems
    from app.services.scoring import seed_missing_scoring_levels

    resolved_keys = (
        default_org_creation_choice_keys() if selected_choice_keys is None else selected_choice_keys
    )
    seed_missing_scoring_levels(db, organization_id)
    seed_external_systems(db, organization_id)
    for definition in get_module_registry().values():
        if definition.on_org_created is not None:
            definition.on_org_created(db, organization_id)
        if definition.on_org_created_with_choices is not None:
            definition.on_org_created_with_choices(db, organization_id, resolved_keys)


def run_on_project_created_hooks(db: Session, project: Project, actor_id: uuid.UUID) -> None:
    """Calls every registered module's `on_project_created` hook in registry
    order right after a new `Project` row is flushed, so
    `app.routers.projects.create_project` needs no specific module. A module
    without the hook is skipped. Does not commit; the caller commits once.

    Args:
        db: An active session, mid-transaction (the `Project` row is flushed).
        project: The newly created project.
        actor_id: The creator, attributed on any row a hook creates.
    """
    for definition in get_module_registry().values():
        if definition.on_project_created is None:
            continue
        definition.on_project_created(db, project, actor_id)


def run_org_group_member_removal_hooks(db: Session, org_group_id: uuid.UUID, member_user_id: uuid.UUID) -> str | None:
    """Calls every registered module's `validate_org_group_member_removal` hook
    in registry order, stopping at the first block message, so
    `app.routers.orgs.remove_org_group_member` can protect module-owned
    invariants (e.g. Compliance's fallback group) without importing a module.
    A module without the hook is skipped. Read-only.

    Args:
        db: An active database session.
        org_group_id: The group a member is about to be removed from.
        member_user_id: The user being removed (always a user, never a nested group).

    Returns:
        The first non-`None` block message, or `None` if every module allows it.
    """
    for definition in get_module_registry().values():
        if definition.validate_org_group_member_removal is None:
            continue
        message = definition.validate_org_group_member_removal(db, org_group_id, member_user_id)
        if message is not None:
            return message
    return None


def run_org_group_deletion_hooks(db: Session, org_group_id: uuid.UUID) -> str | None:
    """Calls every registered module's `validate_org_group_deletion` hook,
    stopping at the first block message — so `delete_org_group` can respect
    module-owned invariants without importing any module.

    Args:
        db: An active database session (read-only use).
        org_group_id: The group about to be deleted.

    Returns:
        The first module's block message, or `None` if every module allows it.
    """
    for definition in get_module_registry().values():
        if definition.validate_org_group_deletion is None:
            continue
        message = definition.validate_org_group_deletion(db, org_group_id)
        if message is not None:
            return message
    return None


def get_module_principal_references() -> list[PrincipalReference]:
    """Every registered module's `principal_references`, in registry order.

    Core's own principal fields are added separately
    (`services.principals.all_principal_references`).
    """
    refs: list[PrincipalReference] = []
    for definition in get_module_registry().values():
        refs.extend(definition.principal_references)
    return refs


def get_module_artefact_ids_in_organization(db: Session, organization_id: uuid.UUID) -> set[uuid.UUID]:
    """Every module's `artefact_ids_in_organization` for one organisation,
    unioned — for org deletion's polymorphic cleanup.

    Args:
        db: An active database session (read-only use).
        organization_id: The organisation.

    Returns:
        Ids of every module-owned artefact belonging to it.
    """
    ids: set[uuid.UUID] = set()
    for definition in get_module_registry().values():
        if definition.artefact_ids_in_organization is not None:
            ids |= definition.artefact_ids_in_organization(db, organization_id)
    return ids


def get_all_registered_artefact_types() -> set[str]:
    """Every valid `ArtefactType` value — the built-in core values
    (`CORE_ARTEFACT_TYPES`) plus every registered
    module's own declared `artefact_types` (Platform
    Foundations). `services.relationships.create_link` validates
    `source_type`/`target_type` against this set, since `ArtefactLink`'s
    own columns are plain strings rather than a closed Python enum (a
    fixed `enum.Enum` can't gain members at runtime the way this registry
    can). A module with no `artefact_types` of its own (the default empty
    tuple) simply contributes nothing.

    Returns:
        The full set of currently-valid artefact-type string values.
    """
    from app.models.enums import CORE_ARTEFACT_TYPES

    types = set(CORE_ARTEFACT_TYPES)
    for definition in get_module_registry().values():
        types.update(definition.artefact_types)
    return types


def get_all_registered_scoring_schemes() -> dict[str, RegisteredScoringScheme]:
    """Merges every registered module's `scoring_schemes` into one
    `{scheme_key: RegisteredScoringScheme}` mapping.

    A scheme key claimed by two modules keeps the first registration (in
    registry order) and logs the rejection, the same "earlier wins" rule
    `build_registry` applies to module keys.

    Returns:
        Every currently registered scoring scheme, keyed by scheme key.
    """
    schemes: dict[str, RegisteredScoringScheme] = {}
    for definition in get_module_registry().values():
        for scheme in definition.scoring_schemes:
            if scheme.key in schemes:
                logger.error(
                    "Scoring scheme '%s' from module '%s' collides with module '%s'; ignoring it.",
                    scheme.key, definition.key, schemes[scheme.key].module_key,
                )
                continue
            schemes[scheme.key] = RegisteredScoringScheme(module_key=definition.key, scheme=scheme)
    return schemes


def _report_param_problem(param: ReportParamDefinition) -> str | None:
    """Why `param` is not a valid declaration, or `None` when it is."""
    if not _REPORT_PARAM_NAME_PATTERN.match(param.name) or param.name in RESERVED_REPORT_PARAM_NAMES:
        return f"parameter name '{param.name}' is invalid or reserved"
    if param.type not in REPORT_PARAM_TYPES:
        return f"parameter '{param.name}' has unknown type '{param.type}'"
    if param.choices is not None and param.type not in ("string", "integer"):
        return f"parameter '{param.name}' declares choices on a {param.type} parameter"
    if (param.minimum is not None or param.maximum is not None) and param.type != "integer":
        return f"parameter '{param.name}' declares bounds on a {param.type} parameter"
    if param.choices is not None and not param.choices:
        return f"parameter '{param.name}' declares an empty choice set"
    if param.minimum is not None and param.maximum is not None and param.minimum > param.maximum:
        return f"parameter '{param.name}' has minimum above maximum"
    if param.choices_for is not None and (param.choices is not None or param.choice_labels or param.type != "string"):
        return f"parameter '{param.name}' takes its choices from a provider, so it declares no fixed choices or labels and is a string"
    if param.choice_labels and not set(param.choice_labels) <= set(param.choices or ()):
        return f"parameter '{param.name}' labels a value that is not one of its choices"
    default = param.default
    if default is not None:
        if param.type == "integer" and (isinstance(default, bool) or not isinstance(default, int)):
            return f"parameter '{param.name}' default is not an integer"
        if param.type == "string" and not isinstance(default, str):
            return f"parameter '{param.name}' default is not a string"
        if param.type == "boolean" and not isinstance(default, bool):
            return f"parameter '{param.name}' default is not a boolean"
        if param.choices is not None and default not in param.choices:
            return f"parameter '{param.name}' default is not one of its choices"
        if param.minimum is not None and param.type == "integer" and default < param.minimum:
            return f"parameter '{param.name}' default is below its minimum"
        if param.maximum is not None and param.type == "integer" and default > param.maximum:
            return f"parameter '{param.name}' default is above its maximum"
    return None


def validate_report_definitions(
    definitions: Iterable[ReportDefinition],
    *,
    subcomponent_keys: Collection[str] | None = None,
    org_role_keys: Collection[str] | None = None,
) -> tuple[list[ReportDefinition], list[str]]:
    """Splits report declarations into the valid ones and a list of problems.

    A report is excluded (never partially served) when its key or slug repeats
    an earlier one, its slug, parameters or parts are malformed, `org_level` has no
    `org_role_key`, or `org_scope` is unknown. When the registry facts are
    supplied it is also excluded for naming a sub-component the module does not
    declare, or an `org_role_key` that is not one of the module's org-scoped
    roles; callers that run before the registry exists (router construction)
    omit them and rely on `get_module_reports` for those two checks.

    Args:
        definitions: The module's declarations, in order (earlier wins).
        subcomponent_keys: The module's `sub_components` keys, or `None` to skip
            that check.
        org_role_keys: The keys of the module's `"org"`-scoped roles, or `None`
            to skip that check.

    Returns:
        `(valid definitions in declaration order, human-readable problems)`.
    """
    valid: list[ReportDefinition] = []
    problems: list[str] = []
    seen_keys: set[str] = set()
    seen_slugs: set[str] = set()
    for report in definitions:
        problem: str | None = None
        if report.key in seen_keys or report.slug in seen_slugs:
            problem = "duplicate key or slug"
        elif not _REPORT_SLUG_PATTERN.match(report.slug) or not report.key.strip():
            problem = "invalid key or slug"
        elif report.org_scope not in REPORT_ORG_SCOPES:
            problem = f"unknown org_scope '{report.org_scope}'"
        elif report.org_level and not report.org_role_key:
            problem = "org_level without an org_role_key"
        elif report.org_role_key and not report.org_level:
            problem = "org_role_key on a report with no organisation-wide variant"
        elif subcomponent_keys is not None and report.subcomponent and report.subcomponent not in subcomponent_keys:
            problem = f"unknown sub-component '{report.subcomponent}'"
        elif report.any_subcomponents and report.subcomponent:
            problem = "subcomponent and any_subcomponents are exclusive"
        elif subcomponent_keys is not None and any(k not in subcomponent_keys for k in report.any_subcomponents):
            problem = "unknown sub-component in any_subcomponents"
        elif org_role_keys is not None and report.org_role_key and report.org_role_key not in org_role_keys:
            problem = f"'{report.org_role_key}' is not an org-scoped role of this module"
        else:
            names = [p.name for p in report.params]
            part_keys = [p.key for p in report.parts]
            if len(set(names)) != len(names):
                problem = "duplicate parameter name"
            elif len(set(part_keys)) != len(part_keys):
                problem = "duplicate part key"
            elif any(not _REPORT_PART_KEY_PATTERN.match(k) or k in BUILT_IN_REPORT_PARTS for k in part_keys):
                problem = f"invalid part key (lower-case words joined by _, not {' or '.join(BUILT_IN_REPORT_PARTS)})"
            elif any(not p.title.strip() for p in report.parts):
                problem = "a part has no title"
            else:
                problem = next((m for m in (_report_param_problem(p) for p in report.params) if m), None)
        if problem is not None:
            problems.append(f"report '{report.slug}': {problem}")
            continue
        seen_keys.add(report.key)
        seen_slugs.add(report.slug)
        valid.append(report)
    return valid, problems


_logged_report_problems: set[str] = set()


def get_module_reports(module_key: str) -> tuple[ReportDefinition, ...]:
    """The validated `reports` of one registered module.

    Invalid declarations are excluded and logged once per process. Returns an
    empty tuple for an unknown module.

    Args:
        module_key: The module's registry key.

    Returns:
        The module's valid `ReportDefinition`s in declaration order.
    """
    definition = get_module(module_key)
    if definition is None or not definition.reports:
        return ()
    valid, problems = validate_report_definitions(
        definition.reports,
        subcomponent_keys={s.key for s in definition.sub_components},
        org_role_keys={r.role_key for r in definition.roles if r.scope == "org"},
    )
    for problem in problems:
        message = f"Module {module_key!r}: {problem}; excluding it"
        if message not in _logged_report_problems:
            _logged_report_problems.add(message)
            logger.error(message)
    return tuple(valid)


def get_all_reports() -> list[tuple[str, ReportDefinition]]:
    """Every valid report across the registry as `(module_key, definition)`,
    in registry order then declaration order."""
    return [(key, report) for key in get_module_registry() for report in get_module_reports(key)]


def get_scoring_targets(db: Session, project_id: uuid.UUID, target_type: str) -> list[ScoringTarget]:
    """Lists the records of artefact type `target_type` that `project_id`
    can be scored against, via the owning module's
    `scoring_target_providers` entry.

    Returns `[]` — never raises — when no module provides `target_type` or
    the owning module is disabled for the project, so a scoring module
    degrades to "score against everything" rather than breaking when the
    provider is switched off.

    Args:
        db: An active database session.
        project_id: The project being scored in.
        target_type: A registered artefact type, e.g. `"persona"`.

    Returns:
        The provider's `ScoringTarget`s, or `[]`.
    """
    for definition in get_module_registry().values():
        provider = definition.scoring_target_providers.get(target_type)
        if provider is None:
            continue
        if not is_module_enabled_for_project(db, project_id, definition.key):
            return []
        return provider(db, project_id)
    return []


def has_demand_party_provider(artefact_type: str) -> bool:
    """Whether some registered module can expand records of `artefact_type` into demand parties (regardless of
    whether that module is enabled anywhere)."""
    return any(artefact_type in d.demand_party_providers for d in get_module_registry().values())


def resolve_demand_parties(
    db: Session, project_id: uuid.UUID, artefact_type: str, ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[DemandParty]]:
    """Expands records of `artefact_type` into the parties they stand for, via the owning module's
    `demand_party_providers` entry.

    Returns `{}` — never raises — when no module provides `artefact_type` or the owning module is disabled for
    the project, so a demand count degrades to "nothing known about these records" rather than breaking. An id
    the provider cannot see in the project (another project's record, one hidden from it) is absent from the
    result.

    Args:
        db: An active database session (read only).
        project_id: The project the counting happens in.
        artefact_type: A registered artefact type, e.g. `"engagement"`.
        ids: The records to expand.

    Returns:
        `{record id: parties}`.
    """
    if not ids:
        return {}
    for definition in get_module_registry().values():
        provider = definition.demand_party_providers.get(artefact_type)
        if provider is None:
            continue
        if not is_module_enabled_for_project(db, project_id, definition.key):
            return {}
        return provider(db, project_id, list(ids))
    return {}


def _summary_provider_for(artefact_type: str) -> tuple[ModuleDefinition, ArtefactSummaryProvider] | None:
    """The `(module, provider)` that declared a summary provider for `artefact_type`, if any."""
    for definition in get_module_registry().values():
        provider = definition.artefact_summary_providers.get(artefact_type)
        if provider is not None:
            return definition, provider
    return None


def has_artefact_summary_provider(artefact_type: str) -> bool:
    """Whether some registered module can label/list records of `artefact_type`
    as relationship targets (`False` for an artefact type whose module is not
    installed, e.g. a reserved target that does not exist yet)."""
    return _summary_provider_for(artefact_type) is not None


def get_artefact_summary(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> ArtefactSummary | None:
    """A module-neutral summary of one artefact via its owning module's
    `artefact_summary_providers` entry.

    Returns `None` — never raises — when no module provides `artefact_type`,
    the record does not exist, or the owning module is disabled for the
    record's project, so a caller treats "not available" and "not found" alike.

    Args:
        db: An active database session.
        artefact_type: A registered artefact type, e.g. `"pain_point"`.
        artefact_id: The record's id.

    Returns:
        The summary, or `None`.
    """
    found = _summary_provider_for(artefact_type)
    if found is None:
        return None
    definition, provider = found
    summary = provider.get(db, artefact_id)
    if summary is None or not is_module_enabled_for_project(db, summary.project_id, definition.key):
        return None
    return summary


def list_artefact_summaries(db: Session, project_id: uuid.UUID, artefact_type: str) -> list[ArtefactSummary]:
    """The records of `artefact_type` a picker can offer for `project_id`, via
    the owning module's provider; `[]` when none provides it or its module is
    disabled for the project."""
    found = _summary_provider_for(artefact_type)
    if found is None:
        return []
    definition, provider = found
    if not is_module_enabled_for_project(db, project_id, definition.key):
        return []
    return provider.list_for_project(db, project_id)


def list_organization_artefact_summaries(
    db: Session, organization_id: uuid.UUID, artefact_type: str
) -> list[ArtefactSummary]:
    """The records of `artefact_type` that `organization_id` itself owns (not any of
    its projects), via the owning module's `list_for_organization`; `[]` when the type
    has no organisation-scoped records or its module (or the type's sub-component of
    the same name) is disabled for the organisation. Used to resolve an
    organisation-qualified record code."""
    found = _summary_provider_for(artefact_type)
    if found is None:
        return []
    definition, provider = found
    list_for_organization = provider.list_for_organization
    if list_for_organization is None:
        return []
    if not is_module_enabled(db, organization_id, definition.key):
        return []
    serving = subcomponent_serving(definition, artefact_type)
    if serving is not None and not is_org_module_subcomponent_enabled(db, organization_id, definition.key, serving.key):
        return []
    return list_for_organization(db, organization_id)


def get_search_providers() -> dict[str, ArtefactSearchProvider]:
    """Every registered artefact type's `ArtefactSearchProvider`: the core types' (requirements,
    actions, change requests) plus each module's `search_providers`. A type claimed twice keeps
    the first registration."""
    from app.services.search_core import CORE_SEARCH_PROVIDERS

    merged: dict[str, ArtefactSearchProvider] = dict(CORE_SEARCH_PROVIDERS)
    for definition in get_module_registry().values():
        for artefact_type, provider in definition.search_providers.items():
            merged.setdefault(artefact_type, provider)
    return merged


def get_activity_action_kinds() -> dict[str, str]:
    """`{audit action: kind}` merged from every module's `activity_action_kinds`."""
    kinds: dict[str, str] = {}
    for definition in get_module_registry().values():
        kinds.update(definition.activity_action_kinds)
    return kinds


def get_activity_metadata_types() -> dict[str, str]:
    """`{audit entity type: metadata group}` merged from every module's `activity_metadata_types`."""
    groups: dict[str, str] = {}
    for definition in get_module_registry().values():
        groups.update(definition.activity_metadata_types)
    return groups


def get_activity_link_ends() -> dict[str, ActivityLinkEndsReader]:
    """`{audit entity type: reader}` merged from every module's `activity_link_ends`."""
    readers: dict[str, ActivityLinkEndsReader] = {}
    for definition in get_module_registry().values():
        readers.update(definition.activity_link_ends)
    return readers


def get_default_code_prefixes() -> dict[str, str]:
    """`{artefact type: default code prefix}` for every module-declared type with a code (core types are in
    `services.code_prefixes.CORE_DEFAULT_PREFIXES`)."""
    prefixes: dict[str, str] = {}
    for definition in get_module_registry().values():
        prefixes.update(definition.default_code_prefixes)
    return prefixes


def get_types_without_code_prefix() -> dict[str, str]:
    """`{artefact type: reason}` for every type a module declared as having no `PREFIX-nnn` code."""
    reasons: dict[str, str] = {}
    for definition in get_module_registry().values():
        reasons.update(definition.no_code_prefix)
    return reasons


def get_not_searchable_types() -> dict[str, str]:
    """`{artefact type: reason}` for every type a module declared not searchable."""
    reasons: dict[str, str] = {}
    for definition in get_module_registry().values():
        reasons.update(definition.not_searchable)
    return reasons


def get_markdown_fields() -> list[MarkdownField]:
    """Every Markdown field: the core tables' (`services.long_text_core`) plus each module's `markdown_fields`."""
    from app.services.long_text_core import CORE_MARKDOWN_FIELDS

    fields = list(CORE_MARKDOWN_FIELDS)
    for definition in get_module_registry().values():
        fields.extend(definition.markdown_fields)
    return fields


def get_plain_text_fields() -> dict[str, str]:
    """`{"table.column": reason}` for every long-text column declared to stay plain text, core and module."""
    from app.services.long_text_core import CORE_PLAIN_TEXT_FIELDS

    reasons = dict(CORE_PLAIN_TEXT_FIELDS)
    for definition in get_module_registry().values():
        reasons.update(definition.plain_text_fields)
    return reasons


def get_report_starter_sections(starter: str) -> list[tuple[str, ReportStarterSection]]:
    """The parts modules contribute to the starter layout `starter`, as `(module_key, section)` in `order`
    (registry order breaks a tie)."""
    found = [
        (key, section)
        for key, definition in get_module_registry().items()
        for section in definition.report_starter_sections
        if section.starter == starter
    ]
    return sorted(found, key=lambda pair: pair[1].order)


def get_report_snippets() -> list[tuple[str | None, ReportSnippet]]:
    """Every report snippet as `(module_key, snippet)`: the core set first (`module_key` is `None`;
    `services.report_snippets_core`), then each module's `report_snippets`. A key claimed twice keeps the first."""
    from app.services.report_snippets_core import CORE_REPORT_SNIPPETS

    found: list[tuple[str | None, ReportSnippet]] = [(None, snippet) for snippet in CORE_REPORT_SNIPPETS]
    seen = {snippet.key for _module, snippet in found}
    for key, definition in get_module_registry().items():
        for snippet in definition.report_snippets:
            if snippet.key not in seen:
                seen.add(snippet.key)
                found.append((key, snippet))
    return found


def get_report_field_providers() -> dict[str, ReportFieldProvider]:
    """Every registered artefact type's `ReportFieldProvider`: the core types'
    (`services.report_fields_core`) plus each module's `report_fields`. A type claimed twice keeps
    the first registration."""
    from app.services.report_fields_core import CORE_REPORT_FIELDS

    merged: dict[str, ReportFieldProvider] = dict(CORE_REPORT_FIELDS)
    for definition in get_module_registry().values():
        for artefact_type, provider in definition.report_fields.items():
            merged.setdefault(artefact_type, provider)
    return merged


def get_record_attachment_providers() -> dict[str, RecordAttachmentProvider]:
    """Every registered artefact type's `RecordAttachmentProvider`: the core types'
    (`services.record_attachments_core`) plus each module's `record_attachments`. A type claimed twice keeps the
    first registration."""
    from app.services.record_attachments_core import CORE_RECORD_ATTACHMENTS

    merged: dict[str, RecordAttachmentProvider] = dict(CORE_RECORD_ATTACHMENTS)
    for definition in get_module_registry().values():
        for artefact_type, provider in definition.record_attachments.items():
            merged.setdefault(artefact_type, provider)
    return merged


def get_no_record_attachment_reasons() -> dict[str, str]:
    """`{artefact type: reason}` for every reportable type whose attachments a report never prints."""
    from app.services.record_attachments_core import CORE_NO_RECORD_ATTACHMENTS

    reasons: dict[str, str] = dict(CORE_NO_RECORD_ATTACHMENTS)
    for definition in get_module_registry().values():
        reasons.update(definition.no_record_attachments)
    return reasons


def get_not_reportable_types() -> dict[str, str]:
    """`{artefact type: reason}` for every type a module declared not reportable."""
    reasons: dict[str, str] = {}
    for definition in get_module_registry().values():
        reasons.update(definition.not_reportable)
    return reasons


def get_record_table_providers() -> dict[str, RecordTableProvider]:
    """Every registered artefact type's `RecordTableProvider`: the core types' (`services.record_tables_core`)
    plus each module's `record_tables`. A type claimed twice keeps the first registration."""
    from app.services.record_tables_core import CORE_RECORD_TABLES

    merged: dict[str, RecordTableProvider] = dict(CORE_RECORD_TABLES)
    for definition in get_module_registry().values():
        for artefact_type, provider in definition.record_tables.items():
            merged.setdefault(artefact_type, provider)
    return merged


def get_not_importable_types() -> dict[str, str]:
    """`{artefact type: reason}` for every type left without import: a core type's
    (`services.record_tables_core.CORE_NOT_IMPORTABLE`) and each module's `not_importable`."""
    from app.services.record_tables_core import CORE_NOT_IMPORTABLE

    reasons: dict[str, str] = dict(CORE_NOT_IMPORTABLE)
    for definition in get_module_registry().values():
        reasons.update(definition.not_importable)
    return reasons


def get_not_placeable_types() -> dict[str, str]:
    """`{artefact type: reason}` for every type a module declared cannot be placed in a component (no core type is
    among them)."""
    reasons: dict[str, str] = {}
    for definition in get_module_registry().values():
        reasons.update(definition.not_placeable)
    return reasons


def get_record_comment_providers() -> dict[str, RecordCommentProvider]:
    """`{artefact type: RecordCommentProvider}` for every type a module opted into the generic record comments
    (no core type is among them: their comments are their own tables)."""
    providers: dict[str, RecordCommentProvider] = {}
    for definition in get_module_registry().values():
        providers.update(definition.record_comments)
    return providers


def get_baseline_snapshot_providers() -> dict[str, tuple[str, BaselineSnapshotProvider]]:
    """`{artefact type: (module key, BaselineSnapshotProvider)}` for every type a module opted into baselines (no
    core type is among them: requirements are captured by `services.baseline` itself). A type claimed twice keeps the
    first registration."""
    providers: dict[str, tuple[str, BaselineSnapshotProvider]] = {}
    for key, definition in get_module_registry().items():
        for artefact_type, provider in definition.baseline_snapshots.items():
            providers.setdefault(artefact_type, (key, provider))
    return providers


def get_not_creatable_from_links_types() -> dict[str, str]:
    """`{artefact type: reason}` for every type the Links panel cannot offer "Create new" for: each module's
    `not_creatable_from_links` (no core type is among them)."""
    reasons: dict[str, str] = {}
    for definition in get_module_registry().values():
        reasons.update(definition.not_creatable_from_links)
    return reasons


def get_perf_generators() -> dict[str, PerfDatasetGenerator]:
    """Every registered artefact type's `PerfDatasetGenerator`: the core types'
    (`services.perf_dataset.core`) plus each module's `perf_generators`. A type claimed twice keeps the first."""
    from app.services.perf_dataset.registry import CORE_PERF_GENERATORS

    merged: dict[str, PerfDatasetGenerator] = dict(CORE_PERF_GENERATORS)
    for definition in get_module_registry().values():
        for artefact_type, generator in definition.perf_generators.items():
            merged.setdefault(artefact_type, generator)
    return merged


def get_no_perf_generator_types() -> dict[str, str]:
    """`{artefact type: reason}` for every type a module declared not generated for the performance tooling."""
    reasons: dict[str, str] = {}
    for definition in get_module_registry().values():
        reasons.update(definition.no_perf_generator)
    return reasons


def get_scaling_probes() -> dict[str, ScalingProbe]:
    """Every registered artefact type's `ScalingProbe`: the core types' (`services.scaling_probes_core`) plus each
    module's `scaling_probes`. A type claimed twice keeps the first."""
    from app.services.scaling_probes_core import CORE_SCALING_PROBES

    merged: dict[str, ScalingProbe] = dict(CORE_SCALING_PROBES)
    for definition in get_module_registry().values():
        for artefact_type, probe in definition.scaling_probes.items():
            merged.setdefault(artefact_type, probe)
    return merged


def get_lifecycles() -> dict[str, tuple[str, LifecycleDefinition]]:
    """`{artefact type: (module key, LifecycleDefinition)}` for every type with a lifecycle: the core types' (module key
    `""`, `services.lifecycles_core`) and each module's `lifecycles`. A type claimed twice keeps the first."""
    from app.services.lifecycles_core import CORE_LIFECYCLES

    merged: dict[str, tuple[str, LifecycleDefinition]] = {t: ("", d) for t, d in CORE_LIFECYCLES.items()}
    for key, definition in get_module_registry().items():
        for artefact_type, lifecycle in definition.lifecycles.items():
            merged.setdefault(artefact_type, (key, lifecycle))
    return merged


def get_no_scaling_probe_types() -> dict[str, str]:
    """`{artefact type: reason}` for every type a module declared cannot be filled through its API."""
    reasons: dict[str, str] = {}
    for definition in get_module_registry().values():
        reasons.update(definition.no_scaling_probe)
    return reasons


def get_overview_metrics() -> dict[str, tuple[str, OverviewMetric]]:
    """Every module-contributed overview metric as `{<module_key>:<key>: (module_key, metric)}`."""
    return {
        f"{definition.key}:{metric_key}": (definition.key, metric)
        for definition in get_module_registry().values()
        for metric_key, metric in definition.overview_metrics.items()
    }


def get_overview_widget_types() -> dict[str, tuple[str, OverviewWidgetType]]:
    """Every module-contributed overview widget type as `{<module_key>:<key>: (module_key, type)}`."""
    return {
        f"{definition.key}:{widget_key}": (definition.key, widget)
        for definition in get_module_registry().values()
        for widget_key, widget in definition.overview_widgets.items()
    }


def get_org_overview_metrics() -> dict[str, tuple[str, OverviewMetric]]:
    """Every module-contributed organisation dashboard metric as `{<module_key>:<key>: (module_key, metric)}`."""
    return {
        f"{definition.key}:{metric_key}": (definition.key, metric)
        for definition in get_module_registry().values()
        for metric_key, metric in definition.org_overview_metrics.items()
    }


def get_org_overview_widget_types() -> dict[str, tuple[str, OverviewWidgetType]]:
    """Every module-contributed organisation dashboard widget type as `{<module_key>:<key>: (module_key, type)}`."""
    return {
        f"{definition.key}:{widget_key}": (definition.key, widget)
        for definition in get_module_registry().values()
        for widget_key, widget in definition.org_overview_widgets.items()
    }


def get_search_scopes() -> dict[str, tuple[ModuleDefinition, SearchScope]]:
    """Every module-contributed search scope, keyed `<module_key>:<scope_key>`."""
    return {
        f"{definition.key}:{scope_key}": (definition, scope)
        for definition in get_module_registry().values()
        for scope_key, scope in definition.search_scopes.items()
    }


def artefact_type_module(artefact_type: str) -> ModuleDefinition | None:
    """The module that declares `artefact_type` in its `artefact_types`; `None` for a core type."""
    for definition in get_module_registry().values():
        if artefact_type in definition.artefact_types:
            return definition
    return None


def artefact_type_enabled_for_project(db: Session, artefact_type: str, project_id: uuid.UUID) -> bool:
    """Whether `artefact_type`'s owning module (and the sub-component keyed by the type itself,
    where the module declares one) is enabled for the project. A core type is always enabled."""
    definition = artefact_type_module(artefact_type)
    return definition is None or _artefact_type_enabled_for_project(db, definition, artefact_type, project_id)


_CORE_ARTEFACT_TYPE_LABELS = {
    "requirement": "Requirement", "requirement_action": "Action", "change_request": "Change request",
}


def get_artefact_type_label(artefact_type: str) -> str:
    """The singular display name of `artefact_type`: a core type's built-in
    label, else the owning module's `artefact_type_labels` entry, else the
    type string title-cased (`"open_question"` -> `"Open question"`)."""
    label = _CORE_ARTEFACT_TYPE_LABELS.get(artefact_type)
    if label is not None:
        return label
    for definition in get_module_registry().values():
        label = definition.artefact_type_labels.get(artefact_type)
        if label is not None:
            return label
    return artefact_type.replace("_", " ").capitalize()


def get_all_notification_types() -> dict[str, str | None]:
    """Every valid notification type key mapped to its registered label.

    Core `NotificationType` values map to `None` (their labels live in the
    frontend's string table); each module's `notification_types` map to the label
    it declared. A module key that collides with a core value or an earlier
    module's is dropped and logged rather than raising, so one module's mistake
    cannot break notification delivery for everyone.

    Returns:
        `{type key: label or None}`, core types first.
    """
    from app.models.notification import NotificationType

    merged: dict[str, str | None] = {t.value: None for t in NotificationType}
    for definition in get_module_registry().values():
        for declared in definition.notification_types:
            if declared.key in merged:
                logger.warning(
                    "Module %r notification type %r collides with an existing type; declaration ignored.",
                    definition.key, declared.key,
                )
                continue
            merged[declared.key] = declared.label
    return merged


def get_all_notification_target_kinds() -> frozenset[str]:
    """Every notification target kind the frontend can open: core's plus each module's own."""
    from app.services.notification_targets import CORE_TARGET_KINDS

    kinds = set(CORE_TARGET_KINDS)
    for definition in get_module_registry().values():
        kinds.update(definition.notification_target_kinds)
    return frozenset(kinds)


def get_all_notification_targets() -> dict[str, tuple[str, ...]]:
    """Every notification type's ordered target kinds, core's table merged with the modules'.

    A module's `notification_targets` for a type core also declares are placed first (the module's
    more specific case, such as a standard grant, wins over the generic project one); a module's
    `notification_types` carry their own. A type with no entry is a defect a test reports
    (`test_every_notification_type_declares_a_target`), not something this function hides.

    Returns:
        `{type key: kinds}`, only for types that declare at least one.
    """
    from app.services.notification_targets import CORE_NOTIFICATION_TARGETS

    merged: dict[str, tuple[str, ...]] = dict(CORE_NOTIFICATION_TARGETS)
    for definition in get_module_registry().values():
        for key, kinds in definition.notification_targets.items():
            merged[key] = tuple(dict.fromkeys((*kinds, *merged.get(key, ()))))
        for declared in definition.notification_types:
            if declared.target_kinds and declared.key not in merged:
                merged[declared.key] = declared.target_kinds
    return merged


def get_all_link_type_seeds() -> dict[str, LinkTypeSeed]:
    """Every link type the platform and its modules want to exist, keyed by
    `forward_name`: the core defaults (`services.definitions.DEFAULT_LINK_TYPES`,
    unrestricted) plus each module's `link_type_seeds`.

    Seeds sharing a `forward_name` are merged: restriction lists are unioned
    (`None`, meaning any, absorbs the rest), `dedicated_endpoint` is true if any
    says so, and the first non-`none` flow (and the first non-default nesting scope) wins. A module seed whose phrases
    disagree with an earlier one is dropped and logged rather than raising, so
    one module's mistake cannot take down link creation for every module.

    Returns:
        `{forward_name: merged seed}`.
    """
    from app.services.definitions import DEFAULT_LINK_TYPES

    merged: dict[str, LinkTypeSeed] = {
        forward: LinkTypeSeed(forward_name=forward, reverse_name=reverse, flow=flow)
        for forward, reverse, flow in DEFAULT_LINK_TYPES
    }

    def union(a: tuple[str, ...] | None, b: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if a is None or b is None:
            return None
        return tuple(dict.fromkeys((*a, *b)))

    for definition in get_module_registry().values():
        for seed in definition.link_type_seeds:
            existing = merged.get(seed.forward_name)
            if existing is None:
                merged[seed.forward_name] = seed
                continue
            if existing.reverse_name != seed.reverse_name:
                logger.warning(
                    "Module %r link type seed %r has reverse phrase %r, conflicting with %r; seed ignored.",
                    definition.key, seed.forward_name, seed.reverse_name, existing.reverse_name,
                )
                continue
            merged[seed.forward_name] = LinkTypeSeed(
                forward_name=existing.forward_name, reverse_name=existing.reverse_name,
                flow=existing.flow if existing.flow is not LinkFlow.NONE else seed.flow,
                allowed_source_types=union(existing.allowed_source_types, seed.allowed_source_types),
                allowed_target_types=union(existing.allowed_target_types, seed.allowed_target_types),
                dedicated_endpoint=existing.dedicated_endpoint or seed.dedicated_endpoint,
                nesting_scope=(
                    existing.nesting_scope
                    if existing.nesting_scope is not LinkNestingScope.ANCESTOR_EITHER_WAY
                    else seed.nesting_scope
                ),
            )
    return merged


def get_link_type_seed_owners() -> dict[str, frozenset[str]]:
    """`{forward_name: keys of the modules that declare a seed with it}`, so a
    seed is only materialised for an organisation where one of its owning
    modules is enabled (a core default has no owner and is seeded at
    organisation creation instead)."""
    owners: dict[str, set[str]] = {}
    for definition in get_module_registry().values():
        for seed in definition.link_type_seeds:
            owners.setdefault(seed.forward_name, set()).add(definition.key)
    return {name: frozenset(keys) for name, keys in owners.items()}


def subcomponent_serving(definition: ModuleDefinition, artefact_type: str) -> ModuleSubComponentDefinition | None:
    """The sub-component of `definition` that serves `artefact_type`: the one keyed by the type's own name, else the one that
    lists it in `artefact_types`; `None` when the type is served by the whole module."""
    for sub in definition.sub_components:
        if sub.key == artefact_type or artefact_type in sub.artefact_types:
            return sub
    return None


def _artefact_type_enabled_for_project(
    db: Session, definition: ModuleDefinition, artefact_type: str, project_id: uuid.UUID
) -> bool:
    """Whether the module owning `artefact_type` is enabled for the project —
    and, where the module declares a sub-component keyed by the artefact type
    itself (Context & Strategy's `"pain_point"`, Stakeholders' `"persona"`),
    whether that sub-component is too."""
    sub = subcomponent_serving(definition, artefact_type)
    if sub is not None:
        return is_module_subcomponent_enabled(db, project_id, definition.key, sub.key)
    return is_module_enabled_for_project(db, project_id, definition.key)


def get_artefact_summaries_in_project(
    db: Session, project_id: uuid.UUID, artefact_type: str, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ArtefactSummary] | None:
    """The summaries of the `ids` of `artefact_type` that `project_id` may
    see, via the owning module's provider (batch when it offers
    `get_many_in_project`, else one `get` per id filtered to the project).

    Args:
        db: An active database session.
        project_id: The project doing the looking.
        artefact_type: A registered artefact type, e.g. `"decision"`.
        ids: Record ids to look up.

    Returns:
        `{id: summary}` for the visible records — a missing id is absent,
        so "not found", "other project's" and "hidden" look identical; `{}`
        when the owning module (or sub-component) is disabled for the
        project. `None` when no installed module provides `artefact_type`,
        so a caller can tell "cannot show this kind yet" from "none visible".
    """
    found = _summary_provider_for(artefact_type)
    if found is None:
        return None
    definition, provider = found
    if not ids or not _artefact_type_enabled_for_project(db, definition, artefact_type, project_id):
        return {}
    if provider.get_many_in_project is not None:
        summaries = provider.get_many_in_project(db, project_id, list(ids))
    else:
        summaries = [s for s in (provider.get(db, i) for i in ids) if s is not None and s.project_id == project_id]
    return {s.id: s for s in summaries}


def get_subtype_providers() -> dict[str, Callable[[Session, uuid.UUID], list[str]]]:
    """Merges every registered module's own `ModuleDefinition.subtype_
    providers` into one `{artefact_type: provider}` mapping — the sub-type-vocabulary analogue of `get_all_registered_
    artefact_types` above, one layer down.

    At most one provider is kept per artefact type: if two registered
    modules declared a provider for the same artefact type (not expected —
    a module only ever registers a provider for an artefact type it itself
    declared on `artefact_types`), the later module in registry iteration
    order wins, mirroring this registry's own documented last-write
    tolerance elsewhere rather than raising, since artefact-type ownership
    is already effectively exclusive per module by convention.

    Returns:
        A dict from artefact-type string to its registered provider
        callable. An artefact type with no registered provider (every
        artefact type before Decision Management's own `"decision"`
        registration) is simply absent — see `get_subtypes` for the
        no-provider default.
    """
    providers: dict[str, Callable[[Session, uuid.UUID], list[str]]] = {}
    for definition in get_module_registry().values():
        providers.update(definition.subtype_providers)
    return providers


def get_subtypes(db: Session, organization_id: uuid.UUID, artefact_type: str) -> list[str]:
    """Returns `organization_id`'s current sub-type values for
    `artefact_type`, via that artefact type's registered provider (see
    `get_subtype_providers`), or `[]` if no module has registered one for
    it. Used to validate a `CustomRolePermission`'s own `subtype` value at
    write time and to populate the Role Management UI's sub-type
    picker, mirroring how `create_link` validates `source_type`/
    `target_type` against `get_all_registered_artefact_types` — the
    difference here is that this vocabulary is per-organisation data,
    not a fixed, merged-once set, so it is re-resolved on every call rather
    than cached.

    Args:
        db: An active database session.
        organization_id: The organisation whose current rows to resolve.
        artefact_type: The artefact type to look up a provider for.

    Returns:
        That organisation's current sub-type string values, or `[]` if
        `artefact_type` has no registered provider.
    """
    provider = get_subtype_providers().get(artefact_type)
    if provider is None:
        return []
    return provider(db, organization_id)


def get_module_administrative_permissions() -> list[tuple[str, ModuleAdministrativePermission]]:
    """Every module's `administrative_permissions` as `(module_key, atom)` in registry order. An atom whose key is
    already claimed (by core's `ADMINISTRATIVE_PERMISSIONS` or an earlier module) is skipped, so a duplicate can never
    widen who holds a core atom."""
    from app.services.permissions import ADMINISTRATIVE_PERMISSIONS

    taken = set(ADMINISTRATIVE_PERMISSIONS)
    atoms: list[tuple[str, ModuleAdministrativePermission]] = []
    for key, definition in get_module_registry().items():
        for atom in definition.administrative_permissions:
            if atom.key in taken:
                logger.warning("Module %r administrative permission %r is already claimed; skipped", key, atom.key)
                continue
            taken.add(atom.key)
            atoms.append((key, atom))
    return atoms


def get_record_subtype_resolvers() -> dict[str, tuple[str | None, RecordSubtypeResolver]]:
    """`{artefact type: (module key or None, resolver)}` for every type whose records have a sub-type: core's own
    (`services.record_subtypes_core`, module key `None`) plus each module's `record_subtypes`. A type claimed twice keeps
    the first registration."""
    from app.services.record_subtypes_core import CORE_RECORD_SUBTYPES

    merged: dict[str, tuple[str | None, RecordSubtypeResolver]] = {
        artefact_type: (None, resolver) for artefact_type, resolver in CORE_RECORD_SUBTYPES.items()
    }
    for key, definition in get_module_registry().items():
        for artefact_type, resolver in definition.record_subtypes.items():
            merged.setdefault(artefact_type, (key, resolver))
    return merged


def resolve_record_subtypes(
    db: Session, project_id: uuid.UUID, artefact_type: str, record_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Each of `record_ids`' sub-type key (`RecordSubtypeResolver`), in bulk; a record with none is absent.

    A type with no resolver, or whose owning module is not enabled for the project, gives `{}`.
    """
    entry = get_record_subtype_resolvers().get(artefact_type)
    if entry is None or not record_ids:
        return {}
    module_key, resolver = entry
    if module_key is not None and not is_module_enabled_for_project(db, project_id, module_key):
        return {}
    return resolver(db, project_id, record_ids)


def get_review_adapters() -> dict[str, tuple[str, ReviewAdapter]]:
    """`{artefact type: (module key, ReviewAdapter)}` for every type a module registered a review schedule for. A type
    claimed twice keeps the first registration."""
    merged: dict[str, tuple[str, ReviewAdapter]] = {}
    for key, definition in get_module_registry().items():
        for artefact_type, adapter in definition.review_adapters.items():
            merged.setdefault(artefact_type, (key, adapter))
    return merged


def get_baseline_check_providers() -> list[tuple[str, BaselineCheckProvider]]:
    """Every module's `baseline_check_providers` as `(module_key, provider)` in registry order."""
    return [(key, provider) for key, definition in get_module_registry().items() for provider in definition.baseline_check_providers]


def get_profile_contributors() -> list[tuple[str, ProfileContributor]]:
    """Every module's `profile_contributors` as `(module_key, contributor)` in registry order."""
    return [(key, c) for key, definition in get_module_registry().items() for c in definition.profile_contributors]


def get_policy_resolvers(seam: GovernanceSeam) -> list[tuple[str, PolicyResolver]]:
    """Every module's `PolicyResolver` for `seam` as `(module_key, resolver)` in registry order."""
    return [
        (key, resolver)
        for key, definition in get_module_registry().items()
        for resolver in definition.policy_resolvers
        if resolver.seam == seam
    ]


def get_all_registered_entity_scopes() -> dict[str, EntityScopeDefinition]:
    """Merges every module's `ModuleDefinition.entity_scopes` into one
    `{scope_kind: EntityScopeDefinition}` mapping, the central counterpart to
    `ModuleRoleDefinition.scope`/`resolve_entity_organization_id`;
    `CustomRoleDefinition.scope` validation and the `entity_scope`-aware
    functions in `app.services.rbac` resolve against it.

    A duplicate scope string means two modules claim incompatible resolvers,
    so it is logged and the first registration is kept (as `build_registry`
    does for a duplicate module key).

    Returns:
        A dict from entity-scope string to its definition.
    """
    scopes: dict[str, EntityScopeDefinition] = {}
    for definition in get_module_registry().values():
        for scope_key, entity_scope in definition.entity_scopes.items():
            if scope_key in scopes:
                logger.warning(
                    "Duplicate entity scope %r registered by module %r; keeping the first one registered",
                    scope_key,
                    definition.key,
                )
                continue
            scopes[scope_key] = entity_scope
    return scopes


def get_all_module_scheduled_jobs() -> list[tuple[str, ModuleScheduledJob]]:
    """Every registered module's declared `scheduled_jobs`, each paired with its declaring module's own
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
    """Lists `(module_key, ModuleRoleDefinition)` pairs for every role of `scope`
    declared by a module that is effectively enabled (`is_module_enabled`) for
    `organization_id`. It backs the "available module roles" endpoints
    (`GET /orgs/{id}/module-roles`, `GET /projects/{id}/module-roles`) and the
    filtering of a user's existing grants: a role whose module is disabled is
    excluded from options and display, while its `UserModuleRole` row is kept.

    Args:
        db: An active database session.
        organization_id: The organisation to resolve module enablement against.
        scope: `"org"` or `"project"`; only roles with this scope are returned.

    Returns:
        `(module_key, ModuleRoleDefinition)` tuples in registry order.
    """
    result: list[tuple[str, ModuleRoleDefinition]] = []
    for definition in get_module_registry().values():
        if not is_module_enabled(db, organization_id, definition.key):
            continue
        for role in definition.roles:
            if role.scope == scope:
                result.append((definition.key, role))
    return result
