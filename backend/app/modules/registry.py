"""
Module: modules.registry

Builds and serves the merged module registry for the modular feature
system: the single source of truth for
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

Design note: first-party modules mount their own
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
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import LinkFlow, LinkNestingScope

if TYPE_CHECKING:
    from alembic.config import Config
    from app.models.file import FileAsset
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.user import User
    from app.services.bundle_common import BundleImportWarnings, UserResolver
    from app.services.report_framework import ReportContext, ReportResult

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

# Module availability is resolved in tiers (entitlement, organisation, project), each a small query. A
# read-only caller that resolves it for many projects (the global search asks about every module of every
# project it may search) opts in to `memoize_module_state()`, so each tier is read once per organisation or
# project instead of once per question. Outside that block nothing is cached, so a request that changes a
# setting and re-reads it sees the change.
_module_state_memo: contextvars.ContextVar[dict | None] = contextvars.ContextVar("module_state_memo", default=None)


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
    """Declares one module-contributed RBAC role — a module's own analogue of a fixed `OrgRole`/`ProjectRole`
    enum member, without extending either enum (modules register their own RBAC
    entitlements rather than having their roles hardcoded onto the core
    enums).

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
            a module-owned entity scope (e.g. `"standard"`, one role per `ComplianceStandard`
            row) — for a role tied to one specific row of a first-class
            entity the module itself owns, narrower than "the whole org."
            This generalisation exists specifically so a
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
        permissions: Fine-Grained Access Control — the set of
            permission-atom strings (`app.services.permissions.encode_
            permission`-encoded, e.g. `"decision:approve_baseline:"`, or a
            bare administrative key like `"grant_roles"`) a holder of this
            module-contributed role additionally gets, folded into `app.
            services.rbac.get_effective_permissions`'s union alongside
            direct/group `CustomRoleDefinition` grants. Additive and
            defaulted empty — a module that never sets this keeps working
            exactly as before; this is the one part of the custom-role system any actual
            module is expected to touch (see docs/modules.md).
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
    """Declares one module-owned entity scope as centrally discoverable
    so code outside
    `require_module_role` can resolve an arbitrary `(scope_kind, entity_id)`
    pair too.

    `ModuleRoleDefinition.scope`/`resolve_entity_organization_id` already let
    a module declare a role scoped to one specific row of its own first-class
    entity (e.g. compliance's `"standard"`) — that mechanism itself is
    already generic, but until this dataclass existed there was no registry
    of *which* scope strings exist or how to resolve/enumerate their
    entities, so nothing other than `require_module_role` (which already has
    the specific role object in hand) could reach an entity-scoped grant at
    all. `CustomRoleDefinition.scope` and `app.services.rbac.
    get_effective_permissions`/`require_permission`'s new `entity_scope`
    parameter both resolve against `get_all_registered_entity_scopes()`
    instead.

    Deliberately a second, parallel declaration alongside `ModuleRoleDefinition.
    resolve_entity_organization_id` rather than a refactor of that field to
    derive from this registry — `require_module_role`'s existing, heavily-
    exercised entity-scope branch keeps reading the role's own field
    unchanged; a module registers the *same* resolver function in both
    places. Collapsing the two into one is a reasonable future cleanup once
    this registry has its own track record, not required now.

    Attributes:
        resolve_organization_id: Same signature and contract as
            `ModuleRoleDefinition.resolve_entity_organization_id` — resolves
            one entity's id to its owning organisation's id, or `None` if no
            such entity exists.
        label: Human-readable name for this scope kind (e.g. "Standard"),
            shown in the Role Management UI's scope picker and entity picker.
        list_entities: Every entity of this scope kind that currently exists
            in a given organisation, as `(id, display_name)` pairs — powers
            the Role Management UI's entity picker generically, the same way
            `get_all_permissions()` avoids hardcoding artefact types
            client-side.
    """

    resolve_organization_id: Callable[[Session, uuid.UUID], uuid.UUID | None]
    label: str
    list_entities: Callable[[Session, uuid.UUID], list[tuple[uuid.UUID, str]]]


@dataclass(frozen=True)
class ModuleSubComponentDefinition:
    """Declares one independently toggleable sub-component of a module
    (Platform Foundations, added 2026-09-28 at the
    user's explicit request: "can a project admin turn off just Strategy
    while keeping Pain Points on" rather than only the whole module at
    once). Same shape/spirit as the sibling `ModuleRoleDefinition`/
    `EntityScopeDefinition` dataclasses above — a module declares a tuple
    of these on `ModuleDefinition.sub_components` rather than a core file
    hand-maintaining a per-module list, the same Modular Feature System
    Boundary reasoning `artefact_types`/`org_creation_choices` already
    follow one concern earlier.

    Every `ModuleDefinition.sub_components` entry is one of these.
    `is_module_subcomponent_enabled`/`is_org_module_subcomponent_enabled`
    (below) resolve a given `(module_key, subcomponent_key)` pair's
    effective enabled state — project override, then org default, then
    this dataclass's own `default_enabled` — see those functions'
    docstrings for the full two-tier resolution formula and
 section
    for the full design record.

    Attributes:
        key: Stable identifier for this sub-component, unique within its
            declaring module (e.g. `"strategy"`, `"future_state"`,
            `"pain_point"`) — used as the `subcomponent_key` column value
            in `OrganizationModuleSubComponentDefault`/
            `ProjectModuleSubComponentEnablement`, so it must never change
            once a deployment has rows keyed on it.
        name: Human-readable display name shown in admin UIs (e.g.
            "Strategy").
        default_enabled: Whether a project/organisation with no explicit
            override row for this sub-component gets it enabled by
            default — this dataclass's own analogue of `ModuleDefinition.
            default_enabled` one tier down.
    """

    key: str
    name: str
    default_enabled: bool = True


@dataclass(frozen=True)
class ModuleNavEntry:
    """One additional nav-rail entry a Tier A ("installed") module
    contributes, beyond the single `nav_label`/`nav_path` pair every
    `ModuleFrontendManifest` already carries (Platform
    Foundations / Context & Strategy).

    **Why this exists:** every module registered before Context & Strategy
    (Compliance, Decision Management) only ever needed one project-scoped
    nav-rail entry, so `ModuleFrontendManifest.nav_label`/`nav_path` was
    sufficient on its own. Context & Strategy requires **five**
    separate top-level nav-rail entries — one per artefact type (Strategy,
    Future State, Pain Point, Guiding Principle, Open Question) — not one
    grouped entry with tabs, by explicit user decision. Per this repo's own "Modular Feature
    System Boundary" rule, a core mechanism a module needs *multiple*
    values from must become a generic, registry-driven extension point
    rather than a module-specific hack hardcoded into `Layout.tsx` — this
    dataclass, plus `ModuleFrontendManifest.additional_nav_entries` below,
    is that extension point.

    **Design choice, Decided by: Agent:** rather than replacing `nav_label`/
    `nav_path` with a single `nav_entries: tuple[ModuleNavEntry, ...]` list
    (which would be more uniform), this instead *adds* an `additional_nav_
    entries` field alongside the existing singular pair — so Compliance's
    and Decision Management's own `module.py` files, which declare
    `nav_label=`/`nav_path=` directly, need **zero** changes to keep working
    (an explicit backward-compatibility requirement). A
    module needing more than one entry (Context & Strategy) treats its
    *first* entry as the manifest's own primary `nav_label`/`nav_path`, and
    declares the remaining four via `additional_nav_entries`. `all_nav_
    entries` (below) gives any consumer the full, order-preserving list
    without needing to know about this split.

    Deliberately **Tier A ("installed") only** — `__post_init__` below
    rejects a non-empty `additional_nav_entries` on any other tier. Tier B
    ("remote") mounts exactly one `<ModuleFrame>` iframe at one `frame_url`,
    and Tier C ("federated") loads exactly one Module Federation remote at
    one `remote_entry_url`/`exposed_module` pair — supporting multiple nav
    entries for either would mean re-architecting the iframe/federation
    loading mechanism itself, which is out of scope and has no
    real module asking for it yet. A Tier A module's own routing already
    supports multiple routes natively (`TierAModuleDefinition.routes` on the
    frontend, an array from day one), so only the nav-rail-rendering side
    needed this extension.

    Attributes:
        nav_label: Display label for this nav-rail entry.
        nav_path: The frontend route path this entry links to — same
            `"{project_id}"`-placeholder convention as `ModuleFrontendManifest.
            nav_path` (interpolated the same way, at the same call sites).
        nav_icon: Icon name for this nav-rail entry, resolved client-side by
            `frontend/src/modules/navIcons.ts`'s lucide-react lookup (same
            "module supplies its own data, core file resolves it generically"
            shape as `entityAccentColor` — see that module's own docstring).
            Defaults to `"puzzle"` (a generic module icon) so every entry
            declared before this field existed keeps rendering something
            sensible rather than failing validation.
        sub_component: Key of the `ModuleDefinition.sub_components` entry this
            entry leads to, or `None` when the entry belongs to the module as
            a whole. The nav rail hides an entry whose sub-component is
            disabled for the project (the same state that makes its API
            routes 404), so a link never leads to a page that cannot load.
        sub_components_any: For one page that serves several sub-components (a combined list): the entry is
            hidden only while *every* key listed here is disabled, and shown while at least one is enabled.
            Combined with `sub_component` it needs both conditions; normally only one of the two is set.
    """

    nav_label: str
    nav_path: str
    nav_icon: str = "puzzle"
    sub_component: str | None = None
    sub_components_any: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleFrontendManifest:
    """Declares a module's frontend integration (the two-tier
    frontend module system, extended with a third tier — "Tier C" —
    Module Federation for a genuinely third-party, not-compiled-in, no-rebuild-required module.
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
            mirroring the path-prefix enforcement for MCP tools.
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
        additional_nav_entries: Zero or more further `ModuleNavEntry` rows,
            beyond this manifest's own primary `nav_label`/`nav_path` pair
            (Context & Strategy) — see
            `ModuleNavEntry`'s own docstring for the full rationale and the
            "why add a field instead of replacing the pair" design note.
            Empty by default, so a module that declares only the primary
            pair (Compliance, Decision Management) is unaffected. **Tier `
            "installed"` only** — non-empty on any other tier raises in
            `__post_init__` below. Use `all_nav_entries()` to read the full,
            order-preserving list (primary entry first) without needing to
            know about this split.
        nav_icon: Icon name for this manifest's own primary nav-rail entry —
            same field/meaning as `ModuleNavEntry.nav_icon` (see that
            dataclass's docstring); this manifest doesn't reuse `ModuleNavEntry`
            for its primary pair, so it needs its own copy of the field.
            Defaults to `"puzzle"` for the same backward-compatibility reason.
        nav_sub_component: `ModuleNavEntry.sub_component` for this manifest's
            own primary entry.
        nav_sub_components_any: `ModuleNavEntry.sub_components_any` for this manifest's own primary entry.
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
    """Declares one module-contributed `mcp-server/` tool — see docs/modules.md's "Module-contributed MCP
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
            (see docs/modules.md).
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
    """Declares one optional, module-contributed seeding choice offered on
    the organisation-creation form/endpoint (Decision Management,
for its ADR template packs) — the org-creation flow's own
    analogue of `ModuleRoleDefinition`: a generic declaration so
    `routers.orgs.create_organization` and its accompanying `GET` listing
    endpoint never need to hardcode a specific module's choice list, the
    same "core code shouldn't need to know a specific module exists" goal
    `on_org_created`/`resolve_file_owner_project_id` already serve for
    other org-creation-time concerns.

    Every `ModuleDefinition.org_creation_choices` entry is one of these.
    `get_org_creation_choices` (below) merges every registered module's own
    tuple, in registry order, for the generic listing endpoint to return;
    `default_org_creation_choice_keys` picks out the `default_selected`
    subset used when a caller creates an organisation without specifying
    any selection at all (see that function's own docstring for why this
    matters for backward compatibility).

    Attributes:
        key: Stable identifier, unique across every module's own choices
            (convention: `f"{module_key}:{short_name}"`, e.g.
            `"decisions:adr_madr"`) — passed back in `POST /orgs`'s
            `module_choice_keys` and to `ModuleDefinition.
            on_org_created_with_choices`. Must never change once a
            deployment may have organisations whose provenance depended on
            it (informational only today — no row stores which keys were
            selected — but still treated as stable for forward
            compatibility).
        group_label: Heading the org-creation form groups this option
            under (e.g. `"Decision Templates"`) — multiple options may
            share one group_label; the form renders one heading per
            distinct group_label, in first-seen order.
        label: This option's own display label (e.g. `"MADR (Markdown
            Architectural Decision Records)"`).
        description: One-line explanation shown under the label.
        default_selected: Whether this option is pre-checked on the
            org-creation form, and whether it's included when a caller
            creates an organisation without passing `module_choice_keys`
            at all (server bootstrap, existing scripts, any API caller
            that predates this mechanism) — see `run_on_org_created_hooks`.
    """

    key: str
    group_label: str
    label: str
    description: str
    default_selected: bool = True


@dataclass(frozen=True)
class ModuleScheduledJob:
    """Declares one date-driven background sweep a module needs run
    periodically — e.g. Compliance's
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
    import (added so `org_export.py` doesn't have to import
    `app.modules.compliance` directly, mirroring
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
    project-scoped, unlike the standard
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
        import_late: Optional callable with `import_`'s signature, run for
            every module once *all* modules' `import_` have finished. For
            content that refers to another module's records, which do not
            exist yet while this module's own `import_` runs (Context &
            Strategy's per-persona Pain Point scores refer to Personas, which
            a later-registered module creates). `None` when `import_` alone
            suffices.
    """

    export: Callable[[Session, Project], tuple[dict[str, Any], dict[uuid.UUID, FileAsset]]]
    import_: Callable[
        [Session, Project, dict[str, Any], dict[str, bytes], User, UserResolver, BundleImportWarnings], None
    ]
    import_late: (
        Callable[[Session, Project, dict[str, Any], dict[str, bytes], User, UserResolver, BundleImportWarnings], None] | None
    ) = None


#: `openapi_extra` key a route's own author sets to mark it as an
#: approval/decision-type action (e.g. `@router.post(..., openapi_extra=
#: APPROVAL_ACTION_ROUTE_EXTRA)`) — `build_mcp_tool_manifest` reads this
#: directly off the resolved route object and excludes any tool resolving
#: to such a route from the manifest entirely, regardless of what the
#: declaring module's own `McpToolDefinition` claims. See docs/modules.md:
#: "mark any endpoint that approves/decides something with
#: your route's own approval-action metadata — don't rely on the manifest
#: builder's exclusion as your only defence."
APPROVAL_ACTION_EXTRA_KEY = "x-approval-action"
APPROVAL_ACTION_ROUTE_EXTRA: dict = {APPROVAL_ACTION_EXTRA_KEY: True}

_VALID_MCP_TOOL_PARAM_LOCATIONS = {"path", "query", "body"}


def build_mcp_tool_manifest() -> list[ResolvedMcpTool]:
    """Builds the full, mechanically-verified manifest of every module-
    contributed MCP tool across the live registry — the exact list `GET /api/v1/system/modules/mcp-tools`
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
      when the module declares one too —
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


@dataclass(frozen=True)
class ScoringLevelDefault:
    """One seeded level of a scoring axis (e.g. Severity "Blocker", weight 5).

    Attributes:
        name: Display name, unique within the axis.
        weight: Positive numeric weight, unique within the axis; levels are
            always ordered by weight, so the highest weight is the axis's
            top level.
        description: Optional guidance shown beside the level when scoring.
    """

    name: str
    weight: float
    description: str = ""


@dataclass(frozen=True)
class ScoringAxisDefinition:
    """One scoring input (e.g. Severity) a module registers.

    Attributes:
        key: Stable machine key, unique within its scheme.
        label: Display label.
        description: Optional guidance for scorers.
        default_levels: Levels seeded into every organisation (at least 2).
    """

    key: str
    label: str
    default_levels: tuple[ScoringLevelDefault, ...]
    description: str = ""


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
    the chosen levels' weights.

    Attributes:
        key: Stable machine key, unique within its scheme.
        label: Display label.
        axis_keys: The axes combined (≥1); the first two are the matrix
            chart's rows (Y) and columns (X).
        default_bands: Optional default rating bands (empty = no banding
            until an org/project defines some).
    """

    key: str
    label: str
    axis_keys: tuple[str, ...]
    default_bands: tuple[ScoringBandDefault, ...] = ()


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
        model_keys = [m.key for m in self.models]
        if not model_keys or len(set(model_keys)) != len(model_keys):
            raise ValueError(f"Scheme '{self.key}' needs at least one model and unique model keys.")
        for model in self.models:
            if not _SCORING_KEY_PATTERN.match(model.key):
                raise ValueError(f"Invalid scoring model key '{model.key}'.")
            if not model.axis_keys or not set(model.axis_keys) <= set(axis_keys) or len(set(model.axis_keys)) != len(model.axis_keys):
                raise ValueError(f"Model '{model.key}' must combine distinct axes of scheme '{self.key}'.")
            if model.default_bands:
                validate_scoring_bands([(b.label, b.min_score, b.tone) for b in model.default_bands])
        if self.default_model_key not in model_keys:
            raise ValueError(f"Default model '{self.default_model_key}' is not one of scheme '{self.key}'s models.")
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
    """

    key: str
    label: str
    column: Any


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
        domain: For a field whose values come from a closed list a project defines (a component's name, a type
            definition's name), `(db, project ids) -> the values on offer`, so a run-time variable can offer them as
            options. An `enum` needs none (its `labels` are the domain); a field with neither takes free input.
            `project ids` are the projects the report is for (one, or the readable projects of an organisation run).
    """

    key: str
    label: str
    column: Any
    kind: str = "text"
    labels: Mapping[str, str] = field(default_factory=dict)
    id_column: Any | None = None
    math: bool = False
    domain: Callable[[Session, Sequence[uuid.UUID]], list[str]] | None = None


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
            enums by the label users see, a person as an email (user) or `Name (Org group)` (group).
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
    """

    label: str
    columns: Callable[[Session, Any], Sequence[RecordColumn]]
    list_records: Callable[[Session, Any, uuid.UUID, RecordFilters], list[Any]]
    find: Callable[[Session, Any, str], Any | None]
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
    """

    key: str
    label: str


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
    "format", "include_children", "report_template_id", "project_id", "organization_id", "current_user", "db",
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
        cell_tones: Badge colours for the PDF and Word output, by column heading: `{"Status": {"Approved": "accent"}}`
            tones every cell under a column headed "Status" whose text is a listed label, in every section of the
            report, as the screen's badge does. Build the inner maps with `report_framework.tones_by_label` from the
            module's label and tone maps. A cell whose text is not listed is left plain. Ratings are toned by the
            collector (`ReportSection.tones`), which wins over this.
        parts: The report's tables a custom report layout can embed one at a time (widgets), by the
            `ReportSection.key` the collector gives them. Declare every table whose key is fixed; a table whose
            key depends on the data is not embeddable. Every report also offers `figures` (its headline figures)
            and `notes` (its caveats) without declaring them.
    """

    key: str
    slug: str
    title: str
    description: str
    collector: Callable[[Session, ReportContext], ReportResult]
    subcomponent: str | None = None
    org_level: bool = False
    org_role_key: str | None = None
    org_scope: Literal["readable_projects", "all_org_projects"] = "readable_projects"
    params: tuple[ReportParamDefinition, ...] = field(default=())
    record_types: tuple[str, ...] = field(default=())
    cell_tones: Mapping[str, Mapping[str, str]] = field(default_factory=dict, compare=False)
    parts: tuple[ReportPartDefinition, ...] = field(default=())


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

    model: type
    field: str
    label: str
    audit_entity_type: str
    mandatory: bool = False
    live_filter: Callable[[], Any] | None = None
    record_id_field: str = "id"
    multi_valued: bool = False


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
            gets it enabled by default. Compliance is
            `default_enabled=True` per its own requirements' "enabled by
            default"; a more optional/experimental module would ship
            `default_enabled=False`.
        implemented: Whether this module actually does anything yet.
            `False` for a definition registered as a placeholder/in-
            progress (nothing requires that today, but the
            field exists so a module can be registered ahead of
            its full implementation landing without misrepresenting it as
            live) — admin UIs display this rather than hiding an
            unimplemented entry, matching the "don't hide, grey out"
            principle already applied to non-entitled modules.
        get_router: Zero-argument callable returning the module's
            `APIRouter`, or `None` if it contributes no HTTP endpoints at
            all. Called (not stored eagerly) so a module can defer its own
            import-time work, and so a module with genuinely no router
            (e.g. one that only contributes MCP tools) can return
            `None` without needing a dummy empty router.
        get_project_router: Like `get_router`, but for a second, optional
            router mounted at a genuinely different path root. A module's `get_router` is
            always org-scoped (`/api/v1/orgs/{organization_id}/
            modules/<key>/...`); a module surface that
            also needs project-scoped endpoints living at their own,
            unprefixed-by-org path root (`/api/v1/projects/{project_id}/
            modules/<key>/...`) — required so that an MCP tool proxying to
            one of them can declare `project_id` as its only path
            parameter (mirroring hand-written tools like `get_project
            (project_id)`), which is impossible if the underlying route
            also carries an `{organization_id}` placeholder. `None` for a
            module with no project-scoped router of its own. `build_mcp_tool_manifest` validates a tool's
            `path_template` against **either** of a module's two router
            prefixes, not just `get_router`'s — see that function's own
            docstring. `app.main`'s mount loop mounts both, the same way,
            with no second gate applied at the mount-loop level (see this
            module's own docstring).
        get_global_router: Like `get_router`, but for a third, optional
            router mounted at a path root carrying **neither** an
            `organization_id` nor a `project_id` placeholder at all.
`get_router`/`get_
            project_router` both assume the module's endpoint is reachable
            through *some* resource id already present in the URL
            needed two endpoints with no such id to key off in the first
            place — `GET /api/v1/compliance/nav-visibility` (aggregates
            across every org the caller belongs to, so no single
            `organization_id` applies) and `GET /api/v1/compliance/
            standards/{standard_id}` (deliberately un-prefixed by org,
            mirroring how a project's own id already resolves to its org
            without an `organization_id` segment — see `app.routers.
            projects.get_project`). `None` for a module with no such
            router of its own. Mounted by
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
        roles: Module-contributed RBAC role declarations — each a `ModuleRoleDefinition`. Synced into the
            `module_role_definitions` table at startup by
            `sync_module_role_definitions` and surfaced to callers of
            `list_enabled_module_roles`. Empty tuple for a module that
            contributes no roles of its own.
        frontend_manifest: Module-contributed frontend integration manifest
 — a `ModuleFrontendManifest`, or `None`
            for a module with no frontend surface of its own (e.g. one that
            only contributes a backend router or MCP tools). Read through
            `get_frontend_manifest`, not this field directly, at any call
            site that renders it to a browser — that function additionally
            enforces the Tier B origin-allowlist check documented on
            `ModuleFrontendManifest.frame_url`.
        mcp_tools: Module-contributed MCP tool declarations — each an `McpToolDefinition`. `build_mcp_tool_
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
            module (replacing a "one model-import line per
            first-party module" touch point that used to be hand-maintained). Only ever *imports* a module's already-
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
            to Alembic's own multi-directory `version_locations`, so a module's migration sits
            alongside the rest of that module's own code
            (models/service/router/tests) rather than all in
            `backend/alembic/versions/`. **This does not reopen or
            weaken the trust boundary** — it is a pure
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
        resolve_file_owner_project_id: Optional hook letting a module authorize downloads of files
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
            its own.
        scheduled_jobs: Module-contributed APScheduler jobs — each a `ModuleScheduledJob`.
            Registered generically by `app.services.scheduler.
            start_scheduler`, job-id-prefixed with this module's own `key`.
            Empty tuple for a module with no scheduled processing of its
            own.
        org_bundle_hooks: Optional `ModuleOrgBundleHooks` — this module's
            contribution to `app.services.org_export`'s organisation bundle
            export/import, read via `get_all_module_org_bundle_hooks`.
            `None` for a module with no org-level bundle content of its own;
            such a module then states why in `no_org_bundle`.
        no_org_bundle: Reason this module has no `org_bundle_hooks` (it owns nothing at
            organisation level). A backend test fails for a module with neither.
        project_bundle_hooks: Optional `ModuleProjectBundleHooks` — this
            module's contribution to `app.services.project_export`'s
            project bundle export/import, read via `get_all_module_
            project_bundle_hooks`. `None` for a module with no project-level
            bundle content of its own; such a module then states why in
            `no_project_bundle`.
        no_project_bundle: Reason this module has no `project_bundle_hooks` (it stores nothing
            per project). A backend test fails for a module with neither.
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
        org_creation_choices: Module-contributed `OrgCreationChoiceOption`s
            (Decision Management) offered on the
            org-creation form, distinct from `on_org_created` above: that
            hook always seeds unconditionally, while these are choices a
            human (or caller) opts into — e.g. Decision Management's three
            ADR template packs, none of which should be forced on every
            organisation the way default project statuses are. Empty tuple
            for a module with nothing optional to offer at org-creation
            time (every module before Decision Management). See
            `get_org_creation_choices`/`default_org_creation_choice_keys`.
        on_org_created_with_choices: Optional hook, called once alongside
            `on_org_created` (same event, same transaction, same
            not-committed convention) but only for modules that declared at
            least one `org_creation_choices` entry — separate from
            `on_org_created` itself so a module with only unconditional
            seeding never has to accept an unused `selected_keys` argument.
            Takes `(db, organization_id, selected_keys)` where
            `selected_keys` is the resolved set of every `OrgCreationChoiceOption.
            key` the caller chose (across every module, not just this
            module's own — filter to this module's own prefix before
            acting). `None` for a module with no `org_creation_choices` of
            its own (every module before Decision Management).
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
        on_project_created: Optional hook called once, synchronously, right after a brand-new
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
            module with nothing to react to at project-creation time.
        validate_org_group_member_removal: Generic hook — `app.routers.orgs.remove_org_group_
            member` calls every registered module's copy of this (via
            `run_org_group_member_removal_hooks`, below) before actually
            removing a *user* member (never a nested-group member) from an
            `OrgGroup`, so a module that treats a specific group as some
            kind of fallback/floor-satisfying membership (compliance's own
            "default compliance-managers group," §3) can block a
            removal that would leave one of its own floors unsatisfiable —
            the exact same "can't leave zero" reasoning `routers/projects.
            py`'s project-manager-floor guards already apply, generalised
            so *this* core endpoint never needs to import a specific
            module's own models to enforce a module-owned invariant (the
            Modular Feature System Boundary `CLAUDE.md` describes). Takes `(db, org_group_id,
            member_user_id)`; returns a human-readable block message (the
            endpoint 400s with it) or `None` to allow the removal. `None`
            for a module with no group-based floor concept of its own
.
        validate_org_group_deletion: The whole-group counterpart of
            `validate_org_group_member_removal` (2026-10-05, when org
            groups became deletable). `routers.orgs.groups.delete_org_group`
            calls every module's copy via `run_org_group_deletion_hooks`
            before deleting, so a module that relies on a group (e.g.
            Compliance's fallback compliance-managers group) can block it.
            Takes `(db, org_group_id)`; returns a block message (the
            endpoint 400s with it) or `None` to allow the delete.
        artefact_ids_in_organization: Returns the ids of every artefact of
            this module's own `artefact_types` that belongs to an
            organisation (org-scoped or in one of its projects). Org
            deletion (`services.org_deletion`) uses it to remove the
            polymorphic rows core can't reach by foreign key: `ArtefactLink`
            rows, comments and subscriptions on those artefacts. Takes
            `(db, organization_id)`; `None` for a module with no artefact
            types. Added 2026-10-05: deleting an org whose module artefacts
            were linked failed with a 500.
        artefact_types: Module-contributed values for the shared
            `ArtefactType` vocabulary that `app.models.relationship.ArtefactLink.source_
            type`/`target_type` (a plain validated string column, not a
            closed Python `enum.Enum`, precisely so it can hold values no
            core file has to know about ahead of time) may hold. A module
            introducing its own linkable artefact type declares its string
            values here rather than a core enum being hand-edited per
            module — `get_all_registered_artefact_types` (below) merges
            every registered module's own tuple with the two built-in core
            values (`ArtefactType.REQUIREMENT`/`REQUIREMENT_ACTION`) into
            the one set `services.relationships.create_link` validates
            against. Empty tuple for a module that introduces no linkable
            artefact type of its own (every module before Compliance's own
            evidence-linkage migration).
        subtype_providers: Fine-Grained Access Control — maps
            one of this module's own `artefact_types` values to a callable
            `(db, organization_id) -> list[str]` returning that
            organisation's currently valid sub-type values for it (e.g.
            Decision Management registers `{"decision": <a callable
            returning that org's current Decision Type names>}`), for the
            same reason `artefact_types` itself exists: a permission atom's
            `subtype` dimension needs to validate against a *dynamic,
            per-organisation* vocabulary a module owns, not a value a core
            file could hand-maintain or derive from a fixed enum. Unlike
            `artefact_types` (a fixed, code-level set merged once),
            sub-types here are org-scoped *data* (e.g. `DecisionTypeDefinition`
            rows), so the registry only holds the lookup function, never the
            values themselves — see `get_subtype_providers`/`get_subtypes`
            (below). A module with no dynamic sub-type vocabulary of its own
            simply leaves this empty (every module so far, other than
            Decision Management) — `subtype=None` (the wildcard, matching
            every sub-type) remains the only option for its artefact types.
        entity_scopes: Maps a `ModuleRoleDefinition.scope` value this module already
            uses for a module-owned entity scope (e.g. compliance's
            `"standard"`) to an `EntityScopeDefinition` centrally
            registering how to resolve/enumerate it, so `CustomRoleDefinition.
            scope` and `app.services.rbac`'s `entity_scope`-aware functions
            can reach it too, not just `require_module_role`. Additive and
            defaulted empty — a module with no entity-scoped role of its own
            (every module before Compliance) simply leaves this empty.
        sub_components: Independently toggleable sub-components of this module (e.g.
            Context & Strategy's `"strategy"`/`"future_state"`/
            `"pain_point"`/`"guiding_principle"`/`"open_question"`), each a
            `ModuleSubComponentDefinition`. Resolved by `is_module_
            subcomponent_enabled`/`is_org_module_subcomponent_enabled`
            (below), gated behind `app.services.rbac.require_project_
            subcomponent_enabled`/`require_org_subcomponent_enabled`.
            Empty tuple (the default) for a module with no sub-component-
            level toggling of its own — every module before Context &
            Strategy's own `"strategy"` entry needs no change.
        scoring_schemes: Scoring
            schemes (axes with ordered, weighted levels; named models;
            default rating bands) this module registers into core's generic
            scoring-matrix mechanism (`app.services.scoring`). Merged by
            `get_all_registered_scoring_schemes` (below). Empty for a module
            that scores nothing.
        scoring_target_providers: Stakeholders & Personas
            Maps one of this module's own `artefact_types` to a
            callable `(db, project_id) -> list[ScoringTarget]` listing the
            records of that type a project can be scored against, with
            weights. Lets one module (Context & Strategy) score against
            another's records (Personas) without importing it; read via
            `get_scoring_targets` (below), which returns `[]` when the
            owning module is disabled for the project. Empty for a module
            offering no scoring targets.
        artefact_summary_providers: Maps one of this
            module's own `artefact_types` to an `ArtefactSummaryProvider`
            (`get` + `list_for_project`), so another module can validate,
            label and offer a picker for this module's records as relationship
            targets without importing it. Read via `get_artefact_summary` /
            `list_artefact_summaries` (below), which return `None`/`[]` when
            the owning module is disabled for the project. Empty for a module
            whose records nothing else links to.
        artefact_type_labels: Maps one of this module's own `artefact_types` to
            its singular display name (e.g. `"pain_point"` -> `"Pain point"`),
            read via `get_artefact_type_label`. Lets core UI and API responses
            name a record's kind without a closed per-module map in a core
            file; a type left out gets a title-cased fallback.
        search_providers: Maps one of this module's own `artefact_types` to an
            `ArtefactSearchProvider`, making its records findable by the global search
            (code, title, tags and the fields the provider declares). Read via
            `get_search_providers`. Registration is required of every artefact type: one
            that is not searchable says why in `not_searchable`.
        not_searchable: `{artefact type: reason}` for a type deliberately left out of the
            global search. A backend test fails for a type that has neither.
        search_scopes: `{scope key: SearchScope}` the module adds to the search page's
            Scope filter (Compliance: one standard). Addressed in a request as
            `<module_key>:<scope_key>:<ref_id>`; a scope of a module that is off for the
            caller's project is neither offered nor accepted.
        report_fields: Maps one of this module's own `artefact_types` to a `ReportFieldProvider`, making
            its records usable by custom report layouts (selectable as a source, traversable by link,
            printable by field). Read via `get_report_field_providers`. Registration is required of
            every artefact type: one that cannot be reported says why in `not_reportable`.
        not_reportable: `{artefact type: reason}` for a type deliberately left out of custom reports. A
            backend test fails for a type that has neither.
        report_starter_sections: The parts of the platform's starter report layouts this module supplies for its
            own records (`ReportStarterSection`), so a starter names no module in a core file. Read via
            `get_report_starter_sections`; each is validated as part of its starter by a backend test.
        record_tables: Maps one of this module's own `artefact_types` to a `RecordTableProvider`, making its
            list exportable (CSV, PDF, Word) and, where the provider has `create`/`update`, importable from the
            list itself. Read via `get_record_table_providers`. Registration is required of every artefact
            type, and export has no exemption; a type authored by a workflow rather than by people says why
            it cannot be imported in `not_importable` (and still registers a provider for export).
        not_importable: `{artefact type: reason}` for a type deliberately left without import. A backend
            test fails for a type that has neither a provider able to import nor a reason.
        reports: The reports this module contributes, each
            a `ReportDefinition`. The module mounts the routers built by
            `app.services.report_framework.build_report_routers` and may
            expose the MCP tools from `report_mcp_tools`; the core catalogue
            endpoints list them via `get_module_reports`. Definitions that fail
            `validate_report_definitions` are excluded and logged. Empty for a
            module with no reports.
        link_type_seeds: Link types (`LinkTypeSeed`)
            this module wants to exist, each with phrases, flow and an optional
            source/target artefact-type restriction. Created lazily and only when
            absent, so an organisation's edits are never overwritten; seeds sharing
            a `forward_name` across modules are merged (`get_all_link_type_seeds`).
            Any two artefact types can be linked by default, so a module needs
            seeds only to ship meaningful vocabulary, never to make its types
            linkable. Empty for a module with no vocabulary of its own.
        notification_types: Notification kinds this module sends, each a
            `NotificationTypeDefinition`. Lets a module add kinds without editing
            core's closed `NotificationType` enum; merged by
            `get_all_notification_types`, which `services.notifications.notify` and
            the preferences API validate against. Empty for a module that sends none.
        on_artefact_changed: Optional hook `(db, ArtefactChange) -> None`, called
            synchronously inside the changing request's transaction (never commit)
            for every registered module whenever an artefact changes in a way that
            may invalidate something depending on it (`services.artefact_changes.
            notify_artefact_changed`). It lets a module react to a change in
            another module's artefact (e.g. Risk flagging a mitigation for
            reassessment) with no import of that artefact's module. It must be
            cheap when the change is irrelevant to it.
        principal_references: Columns on this module's models that hold a principal
            (`PrincipalReference`). Lets core block deleting a group that still owns
            records and reassign them (`services.principals`) with no import of the
            module. Declare every owner/assignee/reviewer-style field built as a
            principal; actor fields (`created_by`, `decided_by`) are not principals.
        mcp_guidance: Hand-written Markdown telling an AI agent how to use this
            module's MCP tools (typical workflows, lifecycle order, which tools
            are gated, gotchas). Embedded per module in the agent skill's
            generated `module-tools.md` (`backend/scripts/generate_mcp_module_
            tools_reference.py`); a module that contributes MCP tools must
            provide it (enforced by `backend/tests/test_mcp_skill_reference.py`).
            Do not repeat per-tool parameter lists, which the generator adds.
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
    artefact_summary_providers: dict[str, ArtefactSummaryProvider] = field(default_factory=dict)
    artefact_type_labels: dict[str, str] = field(default_factory=dict)
    reports: tuple[ReportDefinition, ...] = field(default=())
    link_type_seeds: tuple[LinkTypeSeed, ...] = field(default=())
    notification_types: tuple[NotificationTypeDefinition, ...] = field(default=())
    on_artefact_changed: Callable[[Session, ArtefactChange], None] | None = None
    principal_references: tuple[PrincipalReference, ...] = field(default=())
    search_providers: dict[str, ArtefactSearchProvider] = field(default_factory=dict)
    not_searchable: dict[str, str] = field(default_factory=dict)
    search_scopes: dict[str, SearchScope] = field(default_factory=dict)
    report_fields: dict[str, ReportFieldProvider] = field(default_factory=dict)
    not_reportable: dict[str, str] = field(default_factory=dict)
    report_starter_sections: tuple[ReportStarterSection, ...] = field(default=())
    record_tables: dict[str, RecordTableProvider] = field(default_factory=dict)
    not_importable: dict[str, str] = field(default_factory=dict)


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
    part of the required operational record (see this module's
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


@scoped_memo
def is_module_entitled(db: Session, organization_id: uuid.UUID, module_key: str) -> bool:
    """Resolves whether `organization_id` is entitled to use `module_key`
    (the server-tier licensing/plan lever).

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


@scoped_memo
def is_module_enabled(db: Session, organization_id: uuid.UUID, module_key: str) -> bool:
    """Resolves the *effective* enabled state of `module_key` for
    `organization_id` — entitlement AND enablement
    (exact formula: "Effective enabled
    = entitled(org,key) AND (org_row.enabled if present else
    server_default.org_enabled if present else registry.default_enabled)").

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
    """Resolves the organisation-tier "default for a project absent its
    own override" value for `module_key` (Platform Foundations,
`OrganizationModuleEnablement.
    default_project_enabled`) — an explicit row's own value if one exists,
    else the server-wide `ServerModuleDefault.project_default_enabled`, else the
    registry's own `default_enabled` — the same fallback chain
    `is_module_enabled` uses for the sibling `enabled` column.

    This is deliberately **not** gated on `enabled` itself here — that hard
    floor is checked separately by `is_module_enabled`/
    `is_module_enabled_for_project`, which both call this only after
    already confirming `enabled` is `True`. Calling this alone, with
    `enabled` `False`, would return a meaningless value (the "would-be
    default if this module were ever turned on" figure, not a real
    effective state) — callers that need the real effective state should
    use `is_module_enabled_for_project` instead, which combines both tiers
    correctly.

    Args:
        db: An active database session.
        organization_id: The organisation to resolve the default for.
        module_key: The module's registry key.

    Returns:
        `True` if a project of this organisation, with no override of its
        own, gets this module on by default.
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
    """Resolves the *effective* enabled state of `module_key` for one
    specific project (Platform Foundations; corrected
    2026-09-29 to add the `default_project_enabled` tier below — see
    `docs/decisions.md`'s dated entry and correction note for the full reasoning).

    Four tiers, the formula collapsing to:

        effective = entitled AND org_hard_enabled AND (project_override.enabled if a row exists else default_project_enabled)

    In words:

    1. **Entitlement** and **org hard enablement** (`is_module_enabled`,
       which already folds both together) are an absolute floor — if
       either is `False`, the result is `False` full stop, regardless of
       any `ProjectModuleEnablement` row's value, existing or new. This is
       the genuine "the org needs to shut this off entirely, no
       exceptions" case; no project override can cross it in either
       direction.
    2. Once that floor is clear (both `True`), a project's own override
       row, if one exists, decides the result directly — **symmetric**,
       either direction: a project may turn on a module its organisation
       merely *defaults* off for new projects (the "available, but opt-in
       per project" case — a specialist module most projects don't need,
       but any project manager may still choose for their own), or turn
       off one the organisation defaults on.
    3. Absent a project override, `resolve_default_project_enabled` (the
       organisation's own `default_project_enabled` value, or the registry
       default if the organisation has no row at all) is the effective
       state. In practice only a module registered after the project was
       created reaches this tier: projects get a row copied in at creation
       (`snapshot_project_module_state`) and before an org default changes
       (`freeze_projects_module_default`).

    Write-time validation (`routers.projects.module_roles.
    update_project_module_enablement`) rejects an attempt to *set*
    `enabled=True` only when tier 1 (entitlement/hard-enablement) is
    `False` — not merely because `default_project_enabled` is `False`,
    which is exactly the case a project is allowed to opt into. A
    pre-existing override row from before entitlement/hard-enablement was
    revoked is left in place rather than force-deleted, per this
    codebase's existing precedent for harmless stale rows
    (`OrganizationModuleEntitlement`'s own docstring) — it simply never
    takes effect while tier 1 stays `False`.

    Also returns `False` if `module_key` isn't registered or `project_id`
    doesn't resolve to a real project — mirrors `is_module_enabled`'s own
    "unregistered/absent behaves as disabled, not an error" posture.

    `require_project_module_enabled`/`require_project_module_enabled_dynamic`
    (`app.services.rbac`) call this instead of resolving `organization_id`
    and calling `is_module_enabled` directly — every existing module-gated
    project endpoint keeps working unchanged from this switch alone, since
    it's a pure resolution-depth change with an identical result until a
    project override row actually exists.

    `is_module_subcomponent_enabled`'s own first (whole-module) check also
    calls this, not the org-only `is_module_enabled`, so a project-level
    whole-module override correctly cascades to disable/enable that
    module's sub-components too — see that function's own docstring.

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
    sub-component of `module_key` — the generic mechanism behind "keep Pain Points on, turn off
    Strategy" for a project admin, without a per-module hand-edit.

    Mirrors `is_module_enabled_for_project` one level down. Resolution
    order (first that applies wins):

    1. Whole module disabled for this project (`is_module_enabled_for_
       project`) -> `False`; a disabled module cascades to every
       sub-component.
    2. The organisation's own sub-component hard floor (`resolve_org_
       subcomponent_state`'s `enabled`) is `False` -> `False`; no project
       value can cross it, so an org-level Off reaches every project at
       once.
    3. This project's own `ProjectModuleSubComponentEnablement` row ->
       its `enabled`. Projects get one copied in at creation (`snapshot_
       project_module_state`) and before an org default changes
       (`freeze_projects_subcomponent_default`), so an org default change
       never silently flips an existing project.
    4. No project row -> the org's `default_project_enabled`.

    Unregistered module/sub-component keys resolve to `False`, not an
    error, matching `is_module_enabled`.

    Args:
        db: An active database session.
        project_id: The project to resolve this sub-component's state for.
        module_key: The declaring module's registry key.
        subcomponent_key: The sub-component's key, as declared in that
            module's own `ModuleDefinition.sub_components`.

    Returns:
        The effective enabled state, per the resolution order above.
    """
    # Deferred import: `app.services.rbac` imports this module at load time
    # (for `is_module_enabled`/`get_module`), so importing it back here at
    # module top-level would be circular — reusing its existing project ->
    # organisation resolution helper instead of duplicating that lookup.
    from app.services.rbac import _project_organization_id

    organization_id = _project_organization_id(db, project_id)
    if organization_id is None:
        return False
    if not is_module_enabled_for_project(db, project_id, module_key):
        return False

    org_state = resolve_org_subcomponent_state(db, organization_id, module_key, subcomponent_key)
    if org_state is None:
        return False
    org_enabled, org_default_project_enabled = org_state
    if not org_enabled:
        return False

    project_override = _project_subcomponent_override(db, project_id, module_key, subcomponent_key)
    if project_override is not None:
        return project_override.enabled
    return org_default_project_enabled


def is_org_module_subcomponent_enabled(
    db: Session, organization_id: uuid.UUID, module_key: str, subcomponent_key: str,
) -> bool:
    """Org-scoped sibling of `is_module_subcomponent_enabled`, for a
    sub-component of an **org-scoped** artefact (e.g. Context & Strategy's
    org-level Strategy records), which has no project tier at all. The
    organisation's own hard `enabled` lever is the effective value; its
    `default_project_enabled` only matters for projects.

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
    org_state = resolve_org_subcomponent_state(db, organization_id, module_key, subcomponent_key)
    return org_state is not None and org_state[0]


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
    """Copies the organisation's current project defaults into a newly
    created project — one `ProjectModuleEnablement` row per available
    module and one `ProjectModuleSubComponentEnablement` row per available
    sub-component (**Decided by: User**, 2026-10-04: an org default only
    affects projects that get the module afterwards; an org hard Off still
    reaches every project via the floor checks above).

    Only modules/sub-components the org has hard-on are copied (**Decided
    by: Agent**): copying a default-off module (e.g. Decisions) while it's
    unavailable would leave the project without it once the org turns it
    on. Row-less projects read the live default until it next changes
    (`freeze_projects_module_default`).

    Skips any row that already exists. Does not commit.

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
    project_ids = _project_ids_without_row(
        db, organization_id, ProjectModuleSubComponentEnablement,
        module_key=module_key, subcomponent_key=subcomponent_key,
    )
    for project_id in project_ids:
        db.add(ProjectModuleSubComponentEnablement(
            project_id=project_id, module_key=module_key, subcomponent_key=subcomponent_key, enabled=org_state[1],
        ))


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
    where its *file* lives, which changes nothing
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
    (on `ModuleDefinition`, above) describes, added in a follow-up so a first-party module's own migration file
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
    is still what "was deliberately installed" (the trust boundary) hinges on. `run_migrations(connection)` must be idempotent —
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
    entries into the `module_role_definitions` table, upserting on `(module_key, role_key)`.

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
    "don't silently drop historical display data" philosophy
    applied elsewhere (e.g. evidence-revalidation history, which
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
    at all (see `ModuleFrontendManifest`'s own docstring).

    These checks are deliberately mechanical, at the point of use, rather
    than trusted from the module's own declaration — the same "verify,
    don't trust a self-declared field" principle already applied to
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
    """Tries every registered module's `resolve_file_owner_project_id` hook,
in registry iteration order,
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
    """Calls every registered module's `on_org_created` hook (module
    boundary cleanup, 2026-09-08), in registry iteration order, right after
    a brand-new `Organization` row is flushed — the mechanism
    `app.routers.orgs.create_organization` and `app.services.bootstrap.
    run_bootstrap` both call instead of importing a specific module (e.g.
    Compliance's `seed_compliance_action_types`) to seed its own org-scoped
    defaults, mirroring `resolve_module_file_project_id`'s identical
    "core code shouldn't need to know a specific module exists" reasoning.

    Also calls every registered module's `on_org_created_with_choices` hook
    (Decision Management), passing the resolved set of
    selected `OrgCreationChoiceOption` keys — `selected_choice_keys` if the
    caller passed one explicitly (even an empty set, an explicit "seed none
    of these"), otherwise `default_org_creation_choice_keys()`.

    Also seeds the organisation's default levels for every registered
    scoring scheme (`services.scoring.seed_missing_scoring_levels`) — generic core behaviour, not a per-module hook.

    A module with neither hook (the default `None` for both) is simply
    skipped. Does not commit — each hook only adds rows, the same
    convention `seed_project_statuses`/`seed_link_types` already follow;
    the caller commits once for the whole org-creation transaction.

    Args:
        db: An active database session, mid-transaction (the new
            `Organization` row must already be flushed so hooks can
            reference its id via foreign keys).
        organization_id: The newly created organisation's id.
        selected_choice_keys: The `OrgCreationChoiceOption.key`s the caller
            explicitly chose, or `None` to fall back to every
            `default_selected` option (see `default_org_creation_choice_
            keys`'s own docstring for why `None`, not an empty set, is the
            "caller didn't specify" sentinel).
    """
    from app.services.scoring import seed_missing_scoring_levels

    resolved_keys = (
        default_org_creation_choice_keys() if selected_choice_keys is None else selected_choice_keys
    )
    seed_missing_scoring_levels(db, organization_id)
    for definition in get_module_registry().values():
        if definition.on_org_created is not None:
            definition.on_org_created(db, organization_id)
        if definition.on_org_created_with_choices is not None:
            definition.on_org_created_with_choices(db, organization_id, resolved_keys)


def run_on_project_created_hooks(db: Session, project: Project, actor_id: uuid.UUID) -> None:
    """Calls every registered module's `on_project_created` hook,
in registry iteration order,
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
    hook, in registry iteration
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
    if found is None or found[1].list_for_organization is None:
        return []
    definition, provider = found
    if not is_module_enabled(db, organization_id, definition.key):
        return []
    if any(sub.key == artefact_type for sub in definition.sub_components) and not is_org_module_subcomponent_enabled(
        db, organization_id, definition.key, artefact_type
    ):
        return []
    return provider.list_for_organization(db, organization_id)


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


def get_not_searchable_types() -> dict[str, str]:
    """`{artefact type: reason}` for every type a module declared not searchable."""
    reasons: dict[str, str] = {}
    for definition in get_module_registry().values():
        reasons.update(definition.not_searchable)
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


def _artefact_type_enabled_for_project(
    db: Session, definition: ModuleDefinition, artefact_type: str, project_id: uuid.UUID
) -> bool:
    """Whether the module owning `artefact_type` is enabled for the project —
    and, where the module declares a sub-component keyed by the artefact type
    itself (Context & Strategy's `"pain_point"`, Stakeholders' `"persona"`),
    whether that sub-component is too."""
    if any(sub.key == artefact_type for sub in definition.sub_components):
        return is_module_subcomponent_enabled(db, project_id, definition.key, artefact_type)
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


def get_all_registered_entity_scopes() -> dict[str, EntityScopeDefinition]:
    """Merges every registered module's own `ModuleDefinition.entity_scopes`
    into one `{scope_kind: EntityScopeDefinition}` mapping — the centrally-discoverable
    counterpart to `ModuleRoleDefinition.scope`/`resolve_entity_organization_id`,
    which `require_module_role` already resolves without needing this
    registry (it has the specific role object in hand). `CustomRoleDefinition.
    scope` validation and `app.services.rbac`'s `entity_scope`-aware
    functions resolve against this instead.

    Unlike `get_subtype_providers` (whose "last write wins" tolerance is
    safe because sub-type-provider collision would only mean two modules
    redundantly declared the same, compatible lookup for one artefact type),
    a scope-string collision here would mean two modules' *own, likely
    incompatible* `resolve_organization_id`/`list_entities` callables both
    claim the same key — a real registration conflict, not a harmless
    redundancy. This is logged and the first-registered definition is kept,
    mirroring `build_registry`'s own "detect collision, warn, keep the
    first" handling for a duplicate module key.

    Returns:
        A dict from entity-scope string to its registered definition. A
        scope string with no registered definition (every module before
        Compliance's own `"standard"` registration) is simply absent.
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
    """Lists `(module_key, ModuleRoleDefinition)` pairs for every role of
    the given `scope`, declared by a module that is currently *effectively
    enabled* (`is_module_enabled`) for `organization_id`.

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
