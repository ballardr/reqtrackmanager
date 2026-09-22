"""
Module: modules.compliance.module

Registers the Compliance Module into the modular feature system's registry
(docs/compliance-module-plan.md Phase 5) via `MODULE_DEFINITION` — the same
module-level attribute name `app.modules.registry._discover_path_modules`
looks for on a third-party module directory, kept consistent here even
though this is a first-party module appended directly to `INSTALLED_MODULES`
(`app.modules.registry`), not path-discovered.

`compliance_manager` (org-scoped) and `compliance_officer` (project-scoped)
are declared here as module-contributed roles (module system Phase 2) —
per §3/§26's explicit requirement that Compliance's own roles be separate
from `OrgRole`/`ProjectRole`, not new enum members on either.

**2026-09-22 reversal — MCP surface is now write-enabled** (explicit user
instruction, see docs/decisions.md's "Compliance MCP write tools +
generalized AI approval gate" entry): every phase paragraph below that
says a mutating endpoint was "deliberately" left off the MCP tool surface
described a policy this module no longer follows. This module's `mcp_tools`
now declares a write tool for essentially every mutating endpoint across
`router.py`/`project_router.py` (org settings, standards/versions/
requirements/required-actions/action-types/mapping-relationship-types
CRUD+move, requirement mappings, project-compliance assignment+migration,
requirement applicability/assessment, required-action-assessment
complete/uncomplete, evidence CRUD+links+revalidation, reviews CRUD
+complete+evidence-links, traceability links), gated as normal by the
global `MCP_WRITES_ENABLED` switch and the calling account's own RBAC role
— nothing new needed for those. Three categories stay off the tool surface
even now, for reasons that are *not* superseded by this reversal:

1. `approve_requirement`/`reject_requirement` (`project_router.py`) — no
   longer excluded outright; they are declared, but reached through MCP
   only when the project's and its organisation's `allow_ai_approvals` are
   both explicitly enabled (`app.services.rbac.require_ai_approvals_
   enabled`, called inline the same way core's `requirements.approve_
   requirement`/`change_requests.decide_change_request` already do). See
   those two functions' own docstrings.
2. `assign_standard_member_role`/`revoke_standard_member_role`/`assign_
   standard_group_role`/`revoke_standard_group_role` (`router.py`) stay
   undeclared — these grant/revoke a standard-scoped RBAC role
   (`standards_manager`/`standards_contributor`), not compliance business
   data; the user's own instruction was to enable MCP writes "except
   modules that are RBAC or Governance in nature," and a role grant is
   RBAC in nature regardless of which module it lives in. No core RBAC
   role-grant endpoint is MCP-reachable anywhere in this codebase either.
3. `import_standard` (`router.py`) and `upload_evidence_attachment`
   (`project_router.py`) stay undeclared for a mechanical reason, not a
   policy one: both take a `multipart/form-data` file upload, and the
   module-tool proxy mechanism (`mcp-server/server.py`'s
   `_DeclarativeModuleTool.run`) only ever sends a JSON body built from
   `path`/`query`/`body`-located params — there is no way to declare a file
   upload through this mechanism at all, the same constraint that already
   keeps every other file-upload endpoint in this codebase off the MCP
   tool surface.

Phase 6 (Standards Management API, docs/compliance-module-plan.md) adds this
module's first HTTP endpoints — `get_router()` now returns a real
`APIRouter` (`app.modules.compliance.router`) mounted at
`/api/v1/orgs/{organization_id}/modules/compliance` — and its first three
MCP tools, all read-only: `compliance_list_standards`, `compliance_
get_standard_version`, `compliance_list_requirements`. Publish/retire had
no mutating tool at the time (Phase 6's spec deliberately kept the MCP
surface read-only so far, mirroring `docs/mcp-server.md`'s then-cautious
default) — superseded by the 2026-09-22 reversal above; both are now
declared (`compliance_publish_standard_version`/`compliance_retire_
standard_version`).

Phase 7 (Project Compliance Assignment & Assessment) adds this module's
first *project*-scoped router — `get_project_router()`, a new
`ModuleDefinition` field (`app.modules.registry`) mounted at `/api/v1/
projects/{project_id}/modules/compliance` — alongside two more read-only
MCP tools whose path_templates fall under that router's own prefix instead
of `get_router()`'s: `compliance_get_project_status(project_id)` and
`compliance_list_non_compliant_requirements(project_id)`. Neither tool
takes `organization_id` — deliberately, mirroring hand-written tools like
`get_project(project_id)` — which is exactly why these two live on a
second router rather than being nested under the org-scoped one; see
`app.modules.registry`'s own docstring on `get_project_router` and
`project_router.py`'s module docstring for the full reasoning.

Phase 8 (Evidence, §13-§15) adds this module's evidence endpoints to the
same project router, one more read-only MCP tool
(`compliance_list_expiring_evidence(project_id)`), and this module's
`resolve_file_owner_project_id` hook (`app.modules.registry`) — resolving
a `ComplianceEvidenceFile`-attached file to its owning project, so the
core, module-agnostic `GET /api/v1/files/{id}` download endpoint
(`app.routers.files.download_file`) can authorize a Compliance evidence
attachment without importing anything from this module directly.

Phase 9 (Approval/Sign-off, §12, §16, §27) adds one more read-only MCP tool,
`compliance_list_pending_approvals(project_id)`, mirroring `compliance_
list_non_compliant_requirements`'s exact shape. The three real workflow
actions this phase adds — `submit-for-approval`, `approve`, `reject` —
were originally never declared at all. As of the 2026-09-22 reversal
above, `compliance_submit_requirement_for_approval` is a normal write tool
(it only queues a decision, it does not decide anything), and `compliance_
approve_requirement`/`compliance_reject_requirement` are declared but
resolve to routes gated by `require_ai_approvals_enabled` when called
through MCP — see `project_router.py`'s `approve_requirement`/`reject_
requirement` docstrings and point 1 of the reversal note above.

Phase 10 (Scheduled Reviews + Notifications, §17, §18, §28) adds one more
read-only MCP tool, `compliance_list_reviews_due(project_id)`, and this
module's first `scheduled_jobs` — four APScheduler jobs (`app.modules.
registry.ModuleScheduledJob`), one per date-driven sweep `scheduler.py`
defines. The review CRUD/complete endpoints this phase adds (`router.py`/
`project_router.py`) originally had no mutating tool (Phase 10's own plan
spec asked only for the read-only "reviews due" listing) — superseded by
the 2026-09-22 reversal above; all are now declared (`compliance_create_
standard_review`, `compliance_create_project_review`, etc.).

Phase 11 (Cross-Standard Mapping + Version Impact, §19, §27) adds two more
read-only MCP tools: `compliance_list_requirement_mappings` (one
requirement's cross-standard/cross-version mapping links) and `compliance_
get_standard_version_diff` (the added/removed/modified/replaced/re-mapped
diff between two versions of a standard) — both on the org router, both
pure reads with no side effects. §27's own new mutating action, the
project-scoped version-migration endpoint (`project_router.py::migrate_
project_compliance_version`), originally had no declared tool at all, on
this module's then-principle of adding mutating MCP tools only narrowly
and deliberately. Superseded by the 2026-09-22 reversal above: it is now
declared as `compliance_migrate_project_compliance_version`, including its
`confirmed_replacement_requirement_ids` opt-in (carrying an assessment
forward across a `replaced` mapping, gated by both an org-level
`ComplianceMappingRelationshipTypeDefinition.implies_equivalence` flag and
this per-call confirmation — see `models.py`'s own Phase 11 notes) as a
plain array-of-uuid body param, same as any other write tool — no special
confirmation step beyond what the endpoint itself already requires.

Phase 11 follow-up (same day): this module's six Alembic revisions
(0026-0031) moved from the flat `backend/alembic/versions/` directory into
`migrations/` alongside the rest of this module's own code, via the new
`ModuleDefinition.migrations_dir` mechanism (`app.modules.registry.
configure_alembic_version_locations`) — see that field's own docstring for
why this doesn't reopen or weaken Phase 1's original trust-boundary design
(still one linear, reviewed Alembic chain; only the file location changed).

Phase 13 (Frontend: Project Compliance View) adds this module's
`frontend_manifest` — a Tier A (`"installed"`) `ModuleFrontendManifest`
(module system Phase 3) whose `nav_path` uses the `"{project_id}"`
placeholder `ModuleFrontendManifest`'s own docstring names as an example
but which, until this phase, no real module had ever actually populated:
`app.routers.projects.list_project_enabled_modules` needed a small, generic
fix (interpolating the real path parameter into that placeholder before
returning it) to make the placeholder do anything — see that function's own
docstring for the fix. `frontend/src/modules/registry.ts` registers the
matching React Router path (`/projects/:projectId/modules/compliance`),
proving Phase 3's real installed-module routing/nav-discovery mechanism for
the first time (Phase 12's `ComplianceAdminPanel` — org-scoped — had no
routing mechanism to plug into and was mounted directly by `OrgAdminPage.tsx`
instead; see that phase's own notes).

Phase 18 ("Compliance Standards" as a first-class, cross-org, project-like
nav entity) adds this module's third router, `get_global_router()` — a new
`ModuleDefinition` field (`app.modules.registry`) mounted at the bare
`/api/v1/compliance` prefix, no `organization_id`/`project_id` segment at
all, since both of this router's endpoints (`nav-visibility`, `standards/
{standard_id}`) genuinely have no single such id to key off — see
`global_router.py`'s own module docstring and `app.modules.registry.
ModuleDefinition.get_global_router`'s docstring for the full reasoning. No
new MCP tools or roles were added for this phase — both endpoints are
read-only, UI-navigation-shaped surfaces, not new data or actions.

Module boundary cleanup (2026-09-08, see `docs/decisions.md`'s "Module
system follow-up: on_org_created / project_nav_visible hooks" entry — found
and fixed as pre-existing debt flagged during Phase 18's own review, not
part of Phase 18 itself) adds two more hooks, both replacing a direct
`from app.modules.compliance...` import a core file used to carry: `on_org_
created` (`_seed_org_defaults`, below) — `app.routers.orgs.
create_organization`/`app.services.bootstrap.run_bootstrap` used to import
`seed_compliance_action_types` directly; both now call the generic `app.
modules.registry.run_on_org_created_hooks` instead — and `project_nav_
visible` (`_project_nav_visible`, below) — `app.routers.projects.
list_project_enabled_modules` used to import this module's own models/enums
inline to decide whether its nav entry has anything assignable yet; that
query moved into `app.modules.compliance.service.has_assignable_standard`,
called through the new hook instead.

Phase 20 (Standard Applicability Defaults, Exceptions, and Project-Manager
Assignment; §3, §7, §11, §26) adds this module's fourth registry hook,
`on_project_created` (`_reconcile_new_project`, below) — the natural
`Project`-lifecycle sibling to `on_org_created`, reconciling a brand-new
project against every `applies_to_all_projects` standard in its
organisation (`service.py::reconcile_new_project_for_all_standards`), the
same treatment a pre-existing project already got when a standard was
switched into that mode. The two new mutating surfaces this phase adds — the project-scoped
self-service assignment endpoint and the org-scoped applicability-default/
exclusion-list endpoints — originally had no MCP tool, per Phase 4/9's
then-established precedent; superseded by the 2026-09-22 reversal above,
both are now declared (`compliance_assign_standard_to_project`,
`compliance_update_standard_applicability_default`, `compliance_create_
standard_exclusion`, `compliance_remove_standard_exclusion`). No
new module roles (this phase widens *who may call an existing kind of
endpoint* — `ProjectRole.PROJECT_MANAGER`, already this module's existing
`_require_officer` composition — rather than introducing a new named role).

Phase 22 (Standard-Level RBAC, §3) adds two more module-contributed roles,
`standards_manager`/`standards_contributor`, both declared with a new,
module-owned `scope="standard"` — the first user of `app.modules.registry.
ModuleRoleDefinition`'s generalised entity-scope mechanism (`overridden_by`,
`resolve_entity_organization_id`), added by this same phase specifically so
a *future* module's own first-class entity gets the identical per-row-role
capability without teaching core `app.services.rbac` a second hardcoded
scope literal — see that dataclass's own docstring and `docs/modules.md`'s
"Module-contributed RBAC" section for the full mechanism. No new MCP tools
for `assign_standard_member_role`/`revoke_standard_member_role`/`assign_
standard_group_role`/`revoke_standard_group_role` then or now — unlike
every other mutating endpoint this phase's docstring paragraph mentioned,
this one is *not* superseded by the 2026-09-22 reversal above: it is an
RBAC role grant/revoke, which point 2 of that note keeps off the MCP
surface on principle, the same way Modules 8/11/12 stay read-only-only or
untouched for being RBAC/Governance in nature.

External dependencies: `app.modules.registry`'s own dataclasses;
`app.modules.compliance.router`/`.project_router`/`.global_router`/
`.service`/`.scheduler` (each imported lazily, inside `get_router()`/
`get_project_router()`/`get_global_router()`/`resolve_file_owner_project_id`/
`_seed_org_defaults`/`_project_nav_visible`/`_reconcile_new_project`/the
`scheduled_jobs` callables, to avoid any import-cycle risk with this
module's own registration -- mirroring how Phase 5's own notes already
document resolving the `MODULE_DEFINITION`/registry import cycle via
`app/modules/__init__.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.modules.registry import (
    McpToolDefinition,
    ModuleDefinition,
    ModuleFrontendManifest,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleScheduledJob,
)

if TYPE_CHECKING:
    from app.models.file import FileAsset
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.user import User
    from app.services.bundle_common import BundleImportWarnings, UserResolver

COMPLIANCE_MODULE_KEY = "compliance"

_ROUTER_PREFIX = f"/api/v1/orgs/{{organization_id}}/modules/{COMPLIANCE_MODULE_KEY}"
_PROJECT_ROUTER_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{COMPLIANCE_MODULE_KEY}"

# Mirrors `export.ORG_MERGE_RESOLUTION_CHOICES` exactly — defined locally
# (not imported from `export.py`) purely to keep `ModuleOrgBundleHooks`
# construction below a static literal with zero import-cycle risk, the same
# reasoning every callable hook on `MODULE_DEFINITION` already applies via
# lazy, inside-the-function imports.
_ORG_MERGE_RESOLUTION_CHOICES = {"compliance_standard": frozenset({"skip", "import_as_copy"})}

# Mirrors `models.ARTEFACT_TYPE_EVIDENCE`/`ARTEFACT_TYPE_PROJECT_COMPLIANCE_
# REQUIREMENT`/`ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT` exactly — defined
# locally (not imported from models.py) for the same zero-import-cycle
# reason `_ORG_MERGE_RESOLUTION_CHOICES` above documents. This module's own
# contribution to the shared `ArtefactType` vocabulary (Module 0 — Platform
# Foundations, Phase 3): `app.models.relationship.ArtefactLink` rows with
# `source_type="compliance_evidence"` point at either target type below,
# replacing the old dedicated evidence-link join tables.
_ARTEFACT_TYPES = (
    "compliance_evidence",
    "project_compliance_requirement",
    "compliance_required_action_assessment",
)


def get_router() -> APIRouter | None:
    """Returns this module's org-scoped `APIRouter` (Phase 6 — Standards
    Management API; Phase 7 adds standard-to-project assignment endpoints
    to this same router). Imported inside the function body, not at module
    top-level, to avoid any import-cycle risk with this module's own
    registration (see this module's own docstring)."""
    from app.modules.compliance.router import router as compliance_router

    return compliance_router


def get_project_router() -> APIRouter | None:
    """Returns this module's project-scoped `APIRouter` (Phase 7 — Project
    Compliance Assignment & Assessment). Imported inside the function
    body for the same import-cycle reason as `get_router()`."""
    from app.modules.compliance.project_router import router as compliance_project_router

    return compliance_project_router


def get_global_router() -> APIRouter | None:
    """Returns this module's third router (Phase 18 — "Compliance
    Standards" as a first-class, cross-org, project-like nav entity),
    mounted with no `organization_id`/`project_id` in its own path root at
    all (`nav-visibility`, `standards/{standard_id}`) — see `app.modules.
    registry.ModuleDefinition.get_global_router`'s own docstring for why
    neither `get_router()` nor `get_project_router()` fits these two
    endpoints. Imported inside the function body for the same import-cycle
    reason as `get_router()`/`get_project_router()`."""
    from app.modules.compliance.global_router import router as compliance_global_router

    return compliance_global_router


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """This module's `ModuleDefinition.resolve_file_owner_project_id` hook
    (Phase 8) — imported lazily for the same import-cycle reason as
    `get_router()`/`get_project_router()`."""
    from app.modules.compliance.service import resolve_evidence_file_project_id

    return resolve_evidence_file_project_id(db, file_id)


def _seed_org_defaults(db: Session, organization_id: UUID) -> None:
    """This module's `ModuleDefinition.on_org_created` hook (module boundary
    cleanup, 2026-09-08) — seeds this organisation's default compliance
    action types, replacing what `app.routers.orgs.create_organization`/
    `app.services.bootstrap.run_bootstrap` used to import and call directly.
    Imported lazily for the same import-cycle reason as `get_router()`."""
    from app.modules.compliance.service import seed_compliance_action_types

    seed_compliance_action_types(db, organization_id)


def _project_nav_visible(db: Session, project: Project) -> bool:
    """This module's `ModuleDefinition.project_nav_visible` hook (module
    boundary cleanup, 2026-09-08) — hides this module's project nav entry
    until its owning organisation has a standard actually assignable,
    replacing what `app.routers.projects.list_project_enabled_modules` used
    to compute inline via a direct import of this module's own models.
    Imported lazily for the same import-cycle reason as `get_router()`."""
    from app.modules.compliance.service import has_assignable_standard

    return has_assignable_standard(db, project.organization_id)


def _resolve_standard_organization_id(db: Session, standard_id: UUID) -> UUID | None:
    """This module's `ModuleRoleDefinition.resolve_entity_organization_id`
    hook for the `"standard"` scope (Phase 22) — imported lazily for the
    same import-cycle reason as `get_router()`."""
    from app.modules.compliance.service import resolve_standard_organization_id

    return resolve_standard_organization_id(db, standard_id)


def _reconcile_new_project(db: Session, project: Project, actor_id: UUID) -> None:
    """This module's `ModuleDefinition.on_project_created` hook (Phase 20)
    — reconciles a brand-new project against every `applies_to_all_
    projects` standard in its organisation, the same treatment a pre-
    existing project already got when the standard was switched into that
    mode. Imported lazily for the same import-cycle reason as
    `get_router()`."""
    from app.modules.compliance.service import reconcile_new_project_for_all_standards

    reconcile_new_project_for_all_standards(db, project=project, actor_id=actor_id)


def _validate_org_group_member_removal(db: Session, org_group_id: UUID, member_user_id: UUID) -> str | None:
    """This module's `ModuleDefinition.validate_org_group_member_removal`
    hook (Phase 22) — blocks removing a user from this organisation's
    designated fallback compliance-managers group when they're its last
    remaining member and at least one standard in that organisation
    currently relies on the fallback for its own `standards_manager` floor
    (no explicit per-standard grant of its own). Imported lazily for the
    same import-cycle reason as `get_router()`."""
    from app.modules.compliance.service import validate_fallback_group_member_removal

    return validate_fallback_group_member_removal(db, org_group_id, member_user_id)


# `ModuleOrgBundleHooks`/`ModuleProjectBundleHooks` (module system follow-up,
# self-containment pass — see `app.modules.compliance.export`'s own module
# docstring) — each a thin wrapper delegating to `export.py`, imported
# lazily for the same import-cycle reason as every other hook above.
def _export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    from app.modules.compliance.export import export_org_data

    return export_org_data(db, org)


def _import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    from app.modules.compliance.export import import_org_data

    import_org_data(db, org, data, users, warnings, resolutions)


def _compute_org_merge_conflicts(db: Session, target_org: Organization, data: dict[str, Any]) -> list[dict[str, Any]]:
    from app.modules.compliance.export import compute_org_merge_conflicts

    return compute_org_merge_conflicts(db, target_org, data)


def _summarize_org_merge(
    data: dict[str, Any], conflicts: list[dict[str, Any]], resolutions: dict[str, str]
) -> dict[str, int]:
    from app.modules.compliance.export import summarize_org_merge

    return summarize_org_merge(data, conflicts, resolutions)


def _export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    from app.modules.compliance.export import export_project_data

    return export_project_data(db, project)


def _import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes],
    current_user: User, users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    from app.modules.compliance.export import import_project_data

    import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)


def _run_evidence_expiry_notifications(db: Session) -> None:
    from app.modules.compliance.scheduler import send_evidence_expiry_notifications

    send_evidence_expiry_notifications(db)


def _run_review_due_notifications(db: Session) -> None:
    from app.modules.compliance.scheduler import send_review_due_notifications

    send_review_due_notifications(db)


def _run_required_action_due_notifications(db: Session) -> None:
    from app.modules.compliance.scheduler import send_required_action_due_notifications

    send_required_action_due_notifications(db)


def _run_target_date_notifications(db: Session) -> None:
    from app.modules.compliance.scheduler import send_target_date_notifications

    send_target_date_notifications(db)


MODULE_DEFINITION = ModuleDefinition(
    key=COMPLIANCE_MODULE_KEY,
    name="Compliance",
    description=(
        "Manage compliance standards, requirements, and required actions, and assess project "
        "compliance against them."
    ),
    version="0.1.0",
    default_enabled=True,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    get_global_router=get_global_router,
    models_import_path="app.modules.compliance.models",
    migrations_dir="app/modules/compliance/migrations",
    resolve_file_owner_project_id=resolve_file_owner_project_id,
    on_org_created=_seed_org_defaults,
    project_nav_visible=_project_nav_visible,
    on_project_created=_reconcile_new_project,
    validate_org_group_member_removal=_validate_org_group_member_removal,
    artefact_types=_ARTEFACT_TYPES,
    org_bundle_hooks=ModuleOrgBundleHooks(
        export=_export_org_data,
        import_=_import_org_data,
        compute_merge_conflicts=_compute_org_merge_conflicts,
        merge_resolution_choices=_ORG_MERGE_RESOLUTION_CHOICES,
        summarize_merge=_summarize_org_merge,
    ),
    project_bundle_hooks=ModuleProjectBundleHooks(
        export=_export_project_data,
        import_=_import_project_data,
    ),
    frontend_manifest=ModuleFrontendManifest(
        tier="installed",
        nav_label="Compliance",
        nav_path=f"/projects/{{project_id}}/modules/{COMPLIANCE_MODULE_KEY}",
    ),
    scheduled_jobs=(
        ModuleScheduledJob(
            job_id="evidence_expiry_reminders", hour=2, minute=0, run=_run_evidence_expiry_notifications
        ),
        ModuleScheduledJob(job_id="review_due_reminders", hour=2, minute=15, run=_run_review_due_notifications),
        ModuleScheduledJob(
            job_id="required_action_due_reminders", hour=2, minute=30, run=_run_required_action_due_notifications
        ),
        ModuleScheduledJob(job_id="target_date_reminders", hour=2, minute=45, run=_run_target_date_notifications),
    ),
    roles=(
        ModuleRoleDefinition(
            role_key="compliance_manager",
            name="Compliance Manager",
            description=(
                "Creates and manages compliance standards, versions, requirements, and required "
                "actions; assigns standards to projects; views compliance across projects (§3)."
            ),
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="compliance_officer",
            name="Compliance Officer",
            description=(
                "Modifies compliance assessments, applicability, and evidence, and performs "
                "authorised approval/sign-off for the projects they are assigned to (§11/§26)."
            ),
            scope="project",
        ),
        # Phase 22 (docs/compliance-module-plan.md): standard-scoped
        # working-group roles, distinct from org-wide `compliance_manager`
        # (every standard) and project-scoped `compliance_officer`
        # (assessment, not the standard's own content). Both declare
        # `overridden_by=(("org", "compliance_manager"),)` so an org-wide
        # Compliance Manager never needs a redundant per-standard grant —
        # `require_module_role`'s own `OrgRole.ORG_ADMIN`/`is_server_admin`
        # overrides apply automatically to every scope, including this one
        # (see `services.rbac.user_satisfies_module_role`'s own docstring).
        ModuleRoleDefinition(
            role_key="standards_manager",
            name="Standards Manager",
            description=(
                "Full management of one specific compliance standard — requirements, versions, "
                "publish/retire, and this standard's own member list — scoped to just this "
                "standard rather than every standard in the organisation."
            ),
            scope="standard",
            overridden_by=(("org", "compliance_manager"),),
            resolve_entity_organization_id=_resolve_standard_organization_id,
        ),
        ModuleRoleDefinition(
            role_key="standards_contributor",
            name="Standards Contributor",
            description=(
                "May edit a draft version's requirements and required actions on one specific "
                "compliance standard, but may not publish/retire a version or manage the "
                "standard's own member list."
            ),
            scope="standard",
            overridden_by=(("org", "compliance_manager"),),
            resolve_entity_organization_id=_resolve_standard_organization_id,
        ),
    ),
    mcp_tools=(
        McpToolDefinition(
            name="list_standards",
            description="Lists an organisation's compliance standards.",
            method="GET",
            path_template=f"{_ROUTER_PREFIX}/standards",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation whose compliance standards to list."},
            ],
        ),
        McpToolDefinition(
            name="get_standard_version",
            description="Fetches a single version of a compliance standard.",
            method="GET",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The compliance standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The specific version of the standard."},
            ],
        ),
        McpToolDefinition(
            name="list_requirements",
            description="Lists the requirements defined in one version of a compliance standard.",
            method="GET",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The compliance standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The specific version of the standard whose requirements to list."},
            ],
        ),
        McpToolDefinition(
            name="get_project_status",
            description=(
                "Gets a project's overall compliance status (§20) against each of its currently "
                "assigned, active compliance standards — total/applicable/non-applicable requirement "
                "counts, a per-status breakdown, the calculated compliance percentage, and the "
                "overall compliance/approval state."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/status",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose compliance status to get."},
            ],
        ),
        McpToolDefinition(
            name="list_non_compliant_requirements",
            description=(
                "Lists every applicable, Non-Compliant requirement across a project's active "
                "compliance standard assignments."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/non-compliant-requirements",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose non-compliant requirements to list."},
            ],
        ),
        McpToolDefinition(
            name="list_expiring_evidence",
            description=(
                "Lists a project's non-archived supporting evidence that is approaching or has "
                "already passed its expiry date."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/expiring-evidence",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose expiring/expired evidence to list."},
            ],
        ),
        McpToolDefinition(
            name="list_pending_approvals",
            description=(
                "Lists every requirement currently awaiting formal approval/sign-off across a "
                "project's active compliance standard assignments."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/pending-approvals",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose pending compliance approvals to list."},
            ],
        ),
        McpToolDefinition(
            name="list_reviews_due",
            description=(
                "Lists every scheduled compliance review, standard-level or project-level, that is "
                "currently due or overdue for a project — its own project-level reviews plus any "
                "review of a standard it is assigned to."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/reviews-due",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose due/overdue compliance reviews to list."},
            ],
        ),
        McpToolDefinition(
            name="list_requirement_mappings",
            description=(
                "Lists the cross-standard/cross-version mapping links for one compliance requirement, "
                "visible from either side of each mapping."
            ),
            method="GET",
            path_template=(
                f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements/"
                "{requirement_id}/mappings"
            ),
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The compliance standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The specific version of the standard the requirement belongs to."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The requirement whose mapping links to list."},
            ],
        ),
        McpToolDefinition(
            name="get_standard_version_diff",
            description=(
                "Computes the added/removed/modified/replaced/re-mapped requirement diff between two "
                "versions of a compliance standard."
            ),
            method="GET",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/diff/{{other_version_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The compliance standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path",
                 "description": "One of the two versions to diff (order does not matter)."},
                {"name": "other_version_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The other of the two versions to diff (order does not matter)."},
            ],
        ),
        # --- 2026-09-22 reversal: write tools for router.py's (org-scoped) mutating
        # endpoints — see this module's own docstring's "2026-09-22 reversal" section.
        # `import_standard` and the four standard member/group role assign/revoke
        # endpoints are deliberately not declared here (file upload, and RBAC-in-
        # nature respectively) — see that same docstring section for why.
        McpToolDefinition(
            name="update_org_settings",
            description=(
                "Updates this organisation's compliance settings (currently: the fallback group used as this "
                "organisation's default Standards Manager when a standard has no member/group role of its own)."
            ),
            method="PUT",
            path_template=f"{_ROUTER_PREFIX}/settings",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation whose compliance settings to update."},
                {"name": "default_standards_manager_group_id", "type": "uuid", "required": False, "in": "body",
                 "description": "Org group to fall back to as Standards Manager, or null to unset."},
            ],
        ),
        McpToolDefinition(
            name="create_standard",
            description="Creates a new compliance standard, along with its mandatory first (draft) version.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation to create the standard in."},
                {"name": "reference", "type": "string", "required": True, "in": "body",
                 "description": "Short unique reference/code for the standard."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The standard's name."},
                {"name": "description", "type": "string", "required": False, "in": "body",
                 "description": "Free-text description."},
                {"name": "issuing_organisation", "type": "string", "required": False, "in": "body",
                 "description": "The body that issues/owns this standard (e.g. ISO, NIST)."},
                {"name": "owner_id", "type": "uuid", "required": False, "in": "body",
                 "description": "User who owns this standard; defaults to the caller."},
                {"name": "initial_version_label", "type": "string", "required": True, "in": "body",
                 "description": "Label for the standard's mandatory first (draft) version."},
                {"name": "initial_version_effective_date", "type": "string", "required": False, "in": "body",
                 "description": "ISO date the first version takes effect, if known."},
                {"name": "initial_version_change_note", "type": "string", "required": False, "in": "body",
                 "description": "Change note for the first version."},
            ],
        ),
        McpToolDefinition(
            name="update_standard",
            description="Updates a compliance standard's name/description/issuing organisation/owner (its reference is immutable).",
            method="PATCH",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard to update."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The standard's name."},
                {"name": "description", "type": "string", "required": False, "in": "body", "description": "Free-text description."},
                {"name": "issuing_organisation", "type": "string", "required": False, "in": "body",
                 "description": "The body that issues/owns this standard."},
                {"name": "owner_id", "type": "uuid", "required": True, "in": "body", "description": "User who owns this standard."},
            ],
        ),
        McpToolDefinition(
            name="archive_standard",
            description="Archives a compliance standard.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/archive",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard to archive."},
            ],
        ),
        McpToolDefinition(
            name="unarchive_standard",
            description="Unarchives a previously archived compliance standard.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/unarchive",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard to unarchive."},
            ],
        ),
        McpToolDefinition(
            name="update_standard_applicability_default",
            description=(
                "Sets whether a standard applies to every project in the organisation by default "
                "(\"applies_to_all_projects\") or only when a project opts in (\"opt_in\")."
            ),
            method="PATCH",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/applicability-default",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard to update."},
                {"name": "applicability_default", "type": "string", "required": True, "in": "body",
                 "description": "One of 'opt_in' or 'applies_to_all_projects'."},
            ],
        ),
        McpToolDefinition(
            name="create_standard_exclusion",
            description="Excepts a specific project out of a standard's 'applies_to_all_projects' default.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/exclusions",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard to exclude a project from."},
                {"name": "project_id", "type": "uuid", "required": True, "in": "body", "description": "The project to exclude."},
                {"name": "reason", "type": "string", "required": False, "in": "body", "description": "Why this project is excluded."},
            ],
        ),
        McpToolDefinition(
            name="remove_standard_exclusion",
            description="Removes a project's exclusion from a standard's 'applies_to_all_projects' default.",
            method="DELETE",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/exclusions/{{project_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project whose exclusion to remove."},
            ],
        ),
        McpToolDefinition(
            name="create_standard_version",
            description="Creates a new draft version of a standard, optionally cloning another version's full requirement tree.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard to create a new version of."},
                {"name": "version_label", "type": "string", "required": True, "in": "body", "description": "Label for the new version."},
                {"name": "effective_date", "type": "string", "required": False, "in": "body", "description": "ISO date the version takes effect."},
                {"name": "change_note", "type": "string", "required": False, "in": "body", "description": "Change note for this version."},
                {"name": "clone_from_version_id", "type": "uuid", "required": False, "in": "body",
                 "description": "Version to deep-copy the requirement tree from, if any."},
            ],
        ),
        McpToolDefinition(
            name="update_standard_version",
            description="Updates a standard version's editable summary (the only field still editable once a version leaves draft).",
            method="PATCH",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The version to update."},
                {"name": "summary", "type": "string", "required": False, "in": "body", "description": "The version's editable summary."},
            ],
        ),
        McpToolDefinition(
            name="publish_standard_version",
            description="Publishes a draft standard version, making it the standard's current published version.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/publish",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The draft version to publish."},
            ],
        ),
        McpToolDefinition(
            name="retire_standard_version",
            description="Retires a published standard version.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/retire",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The published version to retire."},
            ],
        ),
        McpToolDefinition(
            name="create_requirement",
            description="Creates a new requirement in a draft standard version.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The draft version to add the requirement to."},
                {"name": "parent_requirement_id", "type": "uuid", "required": False, "in": "body",
                 "description": "Parent requirement, for a nested requirement."},
                {"name": "reference", "type": "string", "required": False, "in": "body", "description": "Short reference/code for the requirement."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The requirement's name."},
                {"name": "description", "type": "string", "required": False, "in": "body", "description": "Free-text description."},
                {"name": "reasoning", "type": "string", "required": False, "in": "body", "description": "Why this requirement exists."},
            ],
        ),
        McpToolDefinition(
            name="update_requirement",
            description="Updates a requirement's reference/name/description/reasoning in a draft standard version.",
            method="PATCH",
            path_template=(
                f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements/{{requirement_id}}"
            ),
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The draft version."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path", "description": "The requirement to update."},
                {"name": "reference", "type": "string", "required": False, "in": "body", "description": "Short reference/code for the requirement."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The requirement's name."},
                {"name": "description", "type": "string", "required": False, "in": "body", "description": "Free-text description."},
                {"name": "reasoning", "type": "string", "required": False, "in": "body", "description": "Why this requirement exists."},
            ],
        ),
        McpToolDefinition(
            name="clarify_requirement",
            description=(
                "Makes a non-substantive clarification edit to a requirement that already belongs to a "
                "published version; requires a clarification note."
            ),
            method="PATCH",
            path_template=(
                f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements/"
                "{requirement_id}/clarify"
            ),
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The published version."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path", "description": "The requirement to clarify."},
                {"name": "reference", "type": "string", "required": False, "in": "body", "description": "Short reference/code for the requirement."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The requirement's name."},
                {"name": "description", "type": "string", "required": False, "in": "body", "description": "Free-text description."},
                {"name": "reasoning", "type": "string", "required": False, "in": "body", "description": "Why this requirement exists."},
                {"name": "clarification_note", "type": "string", "required": True, "in": "body",
                 "description": "Mandatory note explaining this non-substantive clarification."},
            ],
        ),
        McpToolDefinition(
            name="delete_requirement",
            description="Deletes a requirement from a draft standard version.",
            method="DELETE",
            path_template=(
                f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements/{{requirement_id}}"
            ),
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The draft version."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path", "description": "The requirement to delete."},
            ],
        ),
        McpToolDefinition(
            name="move_requirement",
            description="Reorders a requirement up or down among its siblings in a draft standard version.",
            method="POST",
            path_template=(
                f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements/"
                "{requirement_id}/move"
            ),
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The draft version."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path", "description": "The requirement to move."},
                {"name": "direction", "type": "string", "required": True, "in": "body", "description": "'up' or 'down'."},
            ],
        ),
        McpToolDefinition(
            name="create_required_action",
            description="Creates a required action under a requirement in a draft standard version.",
            method="POST",
            path_template=(
                f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements/"
                "{requirement_id}/required-actions"
            ),
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The draft version."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The requirement to add a required action to."},
                {"name": "action_type_id", "type": "uuid", "required": True, "in": "body",
                 "description": "This organisation's action type for the action."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The required action's name."},
                {"name": "description", "type": "string", "required": False, "in": "body", "description": "Free-text description."},
                {"name": "is_mandatory", "type": "boolean", "required": False, "in": "body",
                 "description": "Whether this action is mandatory (default true)."},
            ],
        ),
        McpToolDefinition(
            name="update_required_action",
            description="Updates a required action in a draft standard version.",
            method="PATCH",
            path_template=(
                f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements/"
                "{requirement_id}/required-actions/{action_id}"
            ),
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The draft version."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path", "description": "The requirement."},
                {"name": "action_id", "type": "uuid", "required": True, "in": "path", "description": "The required action to update."},
                {"name": "action_type_id", "type": "uuid", "required": True, "in": "body",
                 "description": "This organisation's action type for the action."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The required action's name."},
                {"name": "description", "type": "string", "required": False, "in": "body", "description": "Free-text description."},
                {"name": "is_mandatory", "type": "boolean", "required": False, "in": "body", "description": "Whether this action is mandatory."},
            ],
        ),
        McpToolDefinition(
            name="delete_required_action",
            description="Deletes a required action from a draft standard version.",
            method="DELETE",
            path_template=(
                f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements/"
                "{requirement_id}/required-actions/{action_id}"
            ),
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The draft version."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path", "description": "The requirement."},
                {"name": "action_id", "type": "uuid", "required": True, "in": "path", "description": "The required action to delete."},
            ],
        ),
        McpToolDefinition(
            name="move_required_action",
            description="Reorders a required action up or down among its siblings in a draft standard version.",
            method="POST",
            path_template=(
                f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements/"
                "{requirement_id}/required-actions/{action_id}/move"
            ),
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path", "description": "The draft version."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path", "description": "The requirement."},
                {"name": "action_id", "type": "uuid", "required": True, "in": "path", "description": "The required action to move."},
                {"name": "direction", "type": "string", "required": True, "in": "body", "description": "'up' or 'down'."},
            ],
        ),
        McpToolDefinition(
            name="create_action_type",
            description="Creates a new compliance action type (organisation-scoped vocabulary used by required actions).",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/action-types",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation to create the action type in."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The action type's name."},
            ],
        ),
        McpToolDefinition(
            name="move_action_type",
            description="Reorders a compliance action type up or down in its organisation's list.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/action-types/{{action_type_id}}/move",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "action_type_id", "type": "uuid", "required": True, "in": "path", "description": "The action type to move."},
                {"name": "direction", "type": "string", "required": True, "in": "body", "description": "'up' or 'down'."},
            ],
        ),
        McpToolDefinition(
            name="rename_action_type",
            description="Renames a compliance action type.",
            method="PATCH",
            path_template=f"{_ROUTER_PREFIX}/action-types/{{action_type_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "action_type_id", "type": "uuid", "required": True, "in": "path", "description": "The action type to rename."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The action type's new name."},
            ],
        ),
        McpToolDefinition(
            name="delete_action_type",
            description="Deletes a compliance action type, optionally reassigning its existing required actions to another action type first.",
            method="DELETE",
            path_template=f"{_ROUTER_PREFIX}/action-types/{{action_type_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "action_type_id", "type": "uuid", "required": True, "in": "path", "description": "The action type to delete."},
                {"name": "reassign_to_id", "type": "uuid", "required": False, "in": "query",
                 "description": "Action type to reassign existing required actions to, if any use this one."},
            ],
        ),
        McpToolDefinition(
            name="create_mapping_relationship_type",
            description="Creates a new cross-standard mapping relationship type (e.g. Equivalent, Replaced).",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/mapping-relationship-types",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The relationship type's name."},
                {"name": "implies_equivalence", "type": "boolean", "required": False, "in": "body",
                 "description": "Whether a mapping of this type may carry an assessment forward on migration."},
            ],
        ),
        McpToolDefinition(
            name="move_mapping_relationship_type",
            description="Reorders a mapping relationship type up or down in its organisation's list.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/mapping-relationship-types/{{relationship_type_id}}/move",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "relationship_type_id", "type": "uuid", "required": True, "in": "path", "description": "The relationship type to move."},
                {"name": "direction", "type": "string", "required": True, "in": "body", "description": "'up' or 'down'."},
            ],
        ),
        McpToolDefinition(
            name="update_mapping_relationship_type",
            description="Updates a mapping relationship type's name and/or implies_equivalence flag.",
            method="PATCH",
            path_template=f"{_ROUTER_PREFIX}/mapping-relationship-types/{{relationship_type_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "relationship_type_id", "type": "uuid", "required": True, "in": "path", "description": "The relationship type to update."},
                {"name": "name", "type": "string", "required": True, "in": "body", "description": "The relationship type's name."},
                {"name": "implies_equivalence", "type": "boolean", "required": False, "in": "body",
                 "description": "Whether a mapping of this type may carry an assessment forward on migration."},
            ],
        ),
        McpToolDefinition(
            name="delete_mapping_relationship_type",
            description="Deletes a mapping relationship type, optionally reassigning its existing mappings to another relationship type first.",
            method="DELETE",
            path_template=f"{_ROUTER_PREFIX}/mapping-relationship-types/{{relationship_type_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "relationship_type_id", "type": "uuid", "required": True, "in": "path", "description": "The relationship type to delete."},
                {"name": "reassign_to_id", "type": "uuid", "required": False, "in": "query",
                 "description": "Relationship type to reassign existing mappings to, if any use this one."},
            ],
        ),
        McpToolDefinition(
            name="create_requirement_mapping",
            description="Creates a cross-standard/cross-version mapping link between two requirements in this organisation.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/requirement-mappings",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "from_requirement_id", "type": "uuid", "required": True, "in": "body", "description": "The mapping's source requirement."},
                {"name": "to_requirement_id", "type": "uuid", "required": True, "in": "body", "description": "The mapping's target requirement."},
                {"name": "relationship_type_id", "type": "uuid", "required": True, "in": "body",
                 "description": "The relationship type describing this mapping."},
                {"name": "notes", "type": "string", "required": False, "in": "body", "description": "Free-text notes about this mapping."},
            ],
        ),
        McpToolDefinition(
            name="archive_requirement_mapping",
            description="Archives a requirement mapping.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/requirement-mappings/{{mapping_id}}/archive",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "mapping_id", "type": "uuid", "required": True, "in": "path", "description": "The mapping to archive."},
            ],
        ),
        McpToolDefinition(
            name="unarchive_requirement_mapping",
            description="Unarchives a previously archived requirement mapping.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/requirement-mappings/{{mapping_id}}/unarchive",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "mapping_id", "type": "uuid", "required": True, "in": "path", "description": "The mapping to unarchive."},
            ],
        ),
        McpToolDefinition(
            name="admin_assign_standard_to_project",
            description=(
                "Assigns a compliance standard version to a project (the org-scoped, Compliance-Manager "
                "administrative path — see 'assign_standard_to_project' for the project-scoped self-service path)."
            ),
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/projects/{{project_id}}/project-compliance",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project to assign the standard to."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "body", "description": "The standard being assigned."},
                {"name": "standard_version_id", "type": "uuid", "required": True, "in": "body",
                 "description": "The specific version of the standard being assigned."},
                {"name": "target_compliance_date", "type": "string", "required": False, "in": "body",
                 "description": "ISO date the project targets full compliance by."},
            ],
        ),
        McpToolDefinition(
            name="archive_project_compliance",
            description="Archives a project's compliance standard assignment.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/projects/{{project_id}}/project-compliance/{{project_compliance_id}}/archive",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The assignment to archive."},
            ],
        ),
        McpToolDefinition(
            name="unarchive_project_compliance",
            description="Unarchives a previously archived project compliance standard assignment.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/projects/{{project_id}}/project-compliance/{{project_compliance_id}}/unarchive",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The assignment to unarchive."},
            ],
        ),
        McpToolDefinition(
            name="create_standard_review",
            description="Schedules a new review of a compliance standard itself (not a specific project's assignment).",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/reviews",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard to schedule a review for."},
                {"name": "frequency_label", "type": "string", "required": True, "in": "body",
                 "description": "Human-readable review frequency label."},
                {"name": "recurrence_days", "type": "integer", "required": False, "in": "body",
                 "description": "Days between recurrences, if recurring."},
                {"name": "next_due_date", "type": "string", "required": True, "in": "body", "description": "ISO date this review is next due."},
                {"name": "owner_id", "type": "uuid", "required": False, "in": "body", "description": "User who owns this review."},
                {"name": "notes", "type": "string", "required": False, "in": "body", "description": "Free-text notes."},
            ],
        ),
        McpToolDefinition(
            name="update_standard_review",
            description="Updates a scheduled (not yet completed) standard-level review.",
            method="PATCH",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/reviews/{{review_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "review_id", "type": "uuid", "required": True, "in": "path", "description": "The review to update."},
                {"name": "frequency_label", "type": "string", "required": True, "in": "body",
                 "description": "Human-readable review frequency label."},
                {"name": "recurrence_days", "type": "integer", "required": False, "in": "body",
                 "description": "Days between recurrences, if recurring."},
                {"name": "next_due_date", "type": "string", "required": True, "in": "body", "description": "ISO date this review is next due."},
                {"name": "owner_id", "type": "uuid", "required": False, "in": "body", "description": "User who owns this review."},
                {"name": "notes", "type": "string", "required": False, "in": "body", "description": "Free-text notes."},
            ],
        ),
        McpToolDefinition(
            name="delete_standard_review",
            description="Deletes a scheduled (not yet completed) standard-level review.",
            method="DELETE",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/reviews/{{review_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "review_id", "type": "uuid", "required": True, "in": "path", "description": "The review to delete."},
            ],
        ),
        McpToolDefinition(
            name="complete_standard_review",
            description="Records the outcome of a standard-level review, completing it.",
            method="POST",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/reviews/{{review_id}}/complete",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path", "description": "The standard."},
                {"name": "review_id", "type": "uuid", "required": True, "in": "path", "description": "The review to complete."},
                {"name": "outcome", "type": "string", "required": True, "in": "body", "description": "The review's outcome."},
                {"name": "notes", "type": "string", "required": False, "in": "body",
                 "description": "Free-text notes, replacing the review's current notes."},
            ],
        ),
        # --- 2026-09-22 reversal: write tools for project_router.py's (project-scoped)
        # mutating endpoints. `upload_evidence_attachment` is deliberately not declared
        # here (file upload — see this module's own docstring's "2026-09-22 reversal"
        # section, point 3). `approve_requirement`/`reject_requirement` resolve to
        # routes gated by `require_ai_approvals_enabled` when reached through MCP (point
        # 1 of that same section) — declaring them here does not bypass that gate.
        McpToolDefinition(
            name="assign_standard_to_project",
            description=(
                "Assigns a compliance standard version to this project — the default, self-service path a "
                "compliance_officer/PROJECT_MANAGER uses (see 'admin_assign_standard_to_project' for the "
                "org-scoped Compliance-Manager administrative path)."
            ),
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/project-compliance",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project to assign the standard to."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "body", "description": "The standard being assigned."},
                {"name": "standard_version_id", "type": "uuid", "required": True, "in": "body",
                 "description": "The specific version of the standard being assigned."},
                {"name": "target_compliance_date", "type": "string", "required": False, "in": "body",
                 "description": "ISO date the project targets full compliance by."},
            ],
        ),
        McpToolDefinition(
            name="migrate_project_compliance_version",
            description=(
                "Migrates a project's compliance assignment to a newer, published version of the standard it "
                "already tracks, creating a new assignment row and archiving the old one."
            ),
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/migrate-version",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The assignment to migrate."},
                {"name": "new_standard_version_id", "type": "uuid", "required": True, "in": "body",
                 "description": "The published version to migrate to."},
                {"name": "confirmed_replacement_requirement_ids", "type": "array", "required": False, "in": "body",
                 "description": "New-version requirement ids to carry an assessment forward for, across a 'replaced' mapping that permits it."},
            ],
        ),
        McpToolDefinition(
            name="update_requirement_applicability",
            description="Sets a project requirement's explicit applicability decision (applicable / not_applicable / unset).",
            method="PATCH",
            path_template=(
                f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/requirements/"
                "{pcr_id}/applicability"
            ),
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The standard assignment."},
                {"name": "pcr_id", "type": "uuid", "required": True, "in": "path", "description": "The project compliance requirement to update."},
                {"name": "applicability", "type": "string", "required": True, "in": "body", "description": "The applicability decision."},
                {"name": "justification", "type": "string", "required": False, "in": "body",
                 "description": "Required (400 otherwise) when applicability is 'not_applicable'."},
            ],
        ),
        McpToolDefinition(
            name="update_requirement_assessment",
            description="Sets a project requirement's compliance status (compliant / non_compliant / not_assessed).",
            method="PATCH",
            path_template=(
                f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/requirements/"
                "{pcr_id}/assessment"
            ),
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The standard assignment."},
                {"name": "pcr_id", "type": "uuid", "required": True, "in": "path", "description": "The project compliance requirement to assess."},
                {"name": "compliance_status", "type": "string", "required": True, "in": "body", "description": "The compliance status."},
                {"name": "justification", "type": "string", "required": False, "in": "body",
                 "description": "Required (400 otherwise) when compliance_status is 'non_compliant'."},
                {"name": "notes", "type": "string", "required": False, "in": "body", "description": "Free-text assessment notes."},
            ],
        ),
        McpToolDefinition(
            name="submit_requirement_for_approval",
            description="Requests formal approval/sign-off for a requirement's current assessment (moves it from Assessed to Pending Approval).",
            method="POST",
            path_template=(
                f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/requirements/"
                "{pcr_id}/submit-for-approval"
            ),
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The standard assignment."},
                {"name": "pcr_id", "type": "uuid", "required": True, "in": "path", "description": "The project compliance requirement to submit."},
            ],
        ),
        McpToolDefinition(
            name="approve_requirement",
            description=(
                "Formally approves/signs off a requirement's assessment. Reached through MCP only when this "
                "project's and its organisation's AI-approval opt-in are both enabled."
            ),
            method="POST",
            path_template=(
                f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/requirements/"
                "{pcr_id}/approve"
            ),
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The standard assignment."},
                {"name": "pcr_id", "type": "uuid", "required": True, "in": "path", "description": "The project compliance requirement to approve."},
                {"name": "decision_note", "type": "string", "required": False, "in": "body", "description": "Optional note explaining the approval."},
            ],
        ),
        McpToolDefinition(
            name="reject_requirement",
            description=(
                "Formally rejects a requirement's assessment (a decision_note is required). Reached through MCP "
                "only when this project's and its organisation's AI-approval opt-in are both enabled."
            ),
            method="POST",
            path_template=(
                f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/requirements/"
                "{pcr_id}/reject"
            ),
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The standard assignment."},
                {"name": "pcr_id", "type": "uuid", "required": True, "in": "path", "description": "The project compliance requirement to reject."},
                {"name": "decision_note", "type": "string", "required": False, "in": "body",
                 "description": "Note explaining the rejection; the endpoint 400s if left blank."},
            ],
        ),
        McpToolDefinition(
            name="update_required_action_assessment",
            description="Updates a required action assessment's assignee/due date/notes (not its completion — use complete/uncomplete).",
            method="PATCH",
            path_template=(
                f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/requirements/"
                "{pcr_id}/required-action-assessments/{assessment_id}"
            ),
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The standard assignment."},
                {"name": "pcr_id", "type": "uuid", "required": True, "in": "path", "description": "The project compliance requirement."},
                {"name": "assessment_id", "type": "uuid", "required": True, "in": "path", "description": "The required action assessment to update."},
                {"name": "assignee_id", "type": "uuid", "required": False, "in": "body", "description": "User assigned to this required action."},
                {"name": "due_date", "type": "string", "required": False, "in": "body", "description": "ISO due date."},
                {"name": "notes", "type": "string", "required": False, "in": "body", "description": "Free-text notes."},
            ],
        ),
        McpToolDefinition(
            name="complete_required_action_assessment",
            description="Marks a required action assessment completed.",
            method="POST",
            path_template=(
                f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/requirements/"
                "{pcr_id}/required-action-assessments/{assessment_id}/complete"
            ),
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The standard assignment."},
                {"name": "pcr_id", "type": "uuid", "required": True, "in": "path", "description": "The project compliance requirement."},
                {"name": "assessment_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The required action assessment to complete."},
            ],
        ),
        McpToolDefinition(
            name="uncomplete_required_action_assessment",
            description="Reverts a required action assessment's completion, to correct a mistake.",
            method="POST",
            path_template=(
                f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/requirements/"
                "{pcr_id}/required-action-assessments/{assessment_id}/uncomplete"
            ),
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path", "description": "The standard assignment."},
                {"name": "pcr_id", "type": "uuid", "required": True, "in": "path", "description": "The project compliance requirement."},
                {"name": "assessment_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The required action assessment to uncomplete."},
            ],
        ),
        McpToolDefinition(
            name="create_evidence",
            description=(
                "Creates a piece of supporting evidence in this project, optionally linking it to "
                "requirements/required-action assessments right away."
            ),
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "title", "type": "string", "required": True, "in": "body", "description": "The evidence's title."},
                {"name": "description", "type": "string", "required": False, "in": "body", "description": "Free-text description."},
                {"name": "issuing_organisation", "type": "string", "required": False, "in": "body",
                 "description": "The body that issued this evidence."},
                {"name": "issued_date", "type": "string", "required": False, "in": "body", "description": "ISO date this evidence was issued."},
                {"name": "expiry_date", "type": "string", "required": False, "in": "body", "description": "ISO date this evidence expires, if any."},
                {"name": "notes", "type": "string", "required": False, "in": "body", "description": "Free-text notes."},
                {"name": "project_compliance_requirement_ids", "type": "array", "required": False, "in": "body",
                 "description": "Project compliance requirement ids to link this evidence to right away."},
                {"name": "required_action_assessment_ids", "type": "array", "required": False, "in": "body",
                 "description": "Required action assessment ids to link this evidence to right away."},
            ],
        ),
        McpToolDefinition(
            name="update_evidence",
            description=(
                "Updates a piece of evidence's title/description/issuing organisation/issued date/notes (its "
                "expiry date can only change via revalidate_evidence)."
            ),
            method="PATCH",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence to update."},
                {"name": "title", "type": "string", "required": True, "in": "body", "description": "The evidence's title."},
                {"name": "description", "type": "string", "required": False, "in": "body", "description": "Free-text description."},
                {"name": "issuing_organisation", "type": "string", "required": False, "in": "body",
                 "description": "The body that issued this evidence."},
                {"name": "issued_date", "type": "string", "required": False, "in": "body", "description": "ISO date this evidence was issued."},
                {"name": "notes", "type": "string", "required": False, "in": "body", "description": "Free-text notes."},
            ],
        ),
        McpToolDefinition(
            name="archive_evidence",
            description="Archives a piece of evidence.",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}/archive",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence to archive."},
            ],
        ),
        McpToolDefinition(
            name="unarchive_evidence",
            description="Unarchives a previously archived piece of evidence.",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}/unarchive",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence to unarchive."},
            ],
        ),
        McpToolDefinition(
            name="revalidate_evidence",
            description="Records a new expiry date (or a periodic re-confirmation) for a piece of evidence, retaining the previous value as history.",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}/revalidate",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence to revalidate."},
                {"name": "new_expiry_date", "type": "string", "required": False, "in": "body",
                 "description": "The evidence's new expiry date, if any."},
                {"name": "justification", "type": "string", "required": False, "in": "body", "description": "Notes explaining this revalidation."},
            ],
        ),
        McpToolDefinition(
            name="link_evidence_to_requirement",
            description="Links existing evidence to an additional project compliance requirement's assessment.",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}/requirement-links",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence to link."},
                {"name": "project_compliance_requirement_id", "type": "uuid", "required": True, "in": "body",
                 "description": "The project compliance requirement to link this evidence to."},
            ],
        ),
        McpToolDefinition(
            name="unlink_evidence_from_requirement",
            description="Removes a link between a piece of evidence and a project compliance requirement.",
            method="DELETE",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}/requirement-links/{{pcr_id}}",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence."},
                {"name": "pcr_id", "type": "uuid", "required": True, "in": "path", "description": "The project compliance requirement to unlink."},
            ],
        ),
        McpToolDefinition(
            name="link_evidence_to_action_assessment",
            description="Links existing evidence to an additional required action assessment.",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}/action-links",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence to link."},
                {"name": "required_action_assessment_id", "type": "uuid", "required": True, "in": "body",
                 "description": "The required action assessment to link this evidence to."},
            ],
        ),
        McpToolDefinition(
            name="unlink_evidence_from_action_assessment",
            description="Removes a link between a piece of evidence and a required action assessment.",
            method="DELETE",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}/action-links/{{assessment_id}}",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence."},
                {"name": "assessment_id", "type": "uuid", "required": True, "in": "path", "description": "The required action assessment to unlink."},
            ],
        ),
        McpToolDefinition(
            name="link_evidence_file",
            description="Links an existing, already-uploaded file resource to a piece of evidence (does not itself upload a file).",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}/files/link",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence to attach the file to."},
                {"name": "file_id", "type": "uuid", "required": True, "in": "body", "description": "The existing file resource to link."},
            ],
        ),
        McpToolDefinition(
            name="unlink_evidence_file",
            description="Unlinks a file from a piece of evidence.",
            method="DELETE",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/evidence/{{evidence_id}}/files/{{file_id}}",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence."},
                {"name": "file_id", "type": "uuid", "required": True, "in": "path", "description": "The file to unlink."},
            ],
        ),
        McpToolDefinition(
            name="create_project_review",
            description="Schedules a new review of a project's compliance standard assignment.",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/project-compliance/{{project_compliance_id}}/reviews",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "project_compliance_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The standard assignment to schedule a review for."},
                {"name": "frequency_label", "type": "string", "required": True, "in": "body",
                 "description": "Human-readable review frequency label."},
                {"name": "recurrence_days", "type": "integer", "required": False, "in": "body",
                 "description": "Days between recurrences, if recurring."},
                {"name": "next_due_date", "type": "string", "required": True, "in": "body", "description": "ISO date this review is next due."},
                {"name": "owner_id", "type": "uuid", "required": False, "in": "body", "description": "User who owns this review."},
                {"name": "notes", "type": "string", "required": False, "in": "body", "description": "Free-text notes."},
            ],
        ),
        McpToolDefinition(
            name="update_project_review",
            description="Updates a scheduled (not yet completed) project-level review.",
            method="PATCH",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/reviews/{{review_id}}",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "review_id", "type": "uuid", "required": True, "in": "path", "description": "The review to update."},
                {"name": "frequency_label", "type": "string", "required": True, "in": "body",
                 "description": "Human-readable review frequency label."},
                {"name": "recurrence_days", "type": "integer", "required": False, "in": "body",
                 "description": "Days between recurrences, if recurring."},
                {"name": "next_due_date", "type": "string", "required": True, "in": "body", "description": "ISO date this review is next due."},
                {"name": "owner_id", "type": "uuid", "required": False, "in": "body", "description": "User who owns this review."},
                {"name": "notes", "type": "string", "required": False, "in": "body", "description": "Free-text notes."},
            ],
        ),
        McpToolDefinition(
            name="delete_project_review",
            description="Deletes a scheduled (not yet completed) project-level review.",
            method="DELETE",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/reviews/{{review_id}}",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "review_id", "type": "uuid", "required": True, "in": "path", "description": "The review to delete."},
            ],
        ),
        McpToolDefinition(
            name="complete_project_review",
            description="Records the outcome of a project-level review, completing it.",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/reviews/{{review_id}}/complete",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "review_id", "type": "uuid", "required": True, "in": "path", "description": "The review to complete."},
                {"name": "outcome", "type": "string", "required": True, "in": "body", "description": "The review's outcome."},
                {"name": "notes", "type": "string", "required": False, "in": "body",
                 "description": "Free-text notes, replacing the review's current notes."},
            ],
        ),
        McpToolDefinition(
            name="link_review_evidence",
            description="Links a piece of this project's evidence to a review.",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/reviews/{{review_id}}/evidence-links",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "review_id", "type": "uuid", "required": True, "in": "path", "description": "The review to link evidence to."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "body", "description": "The evidence to link."},
            ],
        ),
        McpToolDefinition(
            name="unlink_review_evidence",
            description="Removes a link between a review and a piece of evidence.",
            method="DELETE",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/reviews/{{review_id}}/evidence-links/{{evidence_id}}",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "review_id", "type": "uuid", "required": True, "in": "path", "description": "The review."},
                {"name": "evidence_id", "type": "uuid", "required": True, "in": "path", "description": "The evidence to unlink."},
            ],
        ),
        McpToolDefinition(
            name="create_requirement_traceability_link",
            description="Creates a traceability link from a core project requirement to a compliance standard requirement.",
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/requirements/{{requirement_id}}/traceability-links",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path", "description": "The core requirement to link from."},
                {"name": "compliance_requirement_id", "type": "uuid", "required": True, "in": "body",
                 "description": "The compliance standard requirement to link to."},
                {"name": "link_type_id", "type": "uuid", "required": True, "in": "body",
                 "description": "The link type describing this traceability link."},
            ],
        ),
        McpToolDefinition(
            name="delete_requirement_traceability_link",
            description="Deletes a traceability link between a core project requirement and a compliance standard requirement.",
            method="DELETE",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/requirements/{{requirement_id}}/traceability-links/{{link_id}}",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project."},
                {"name": "requirement_id", "type": "uuid", "required": True, "in": "path", "description": "The core requirement."},
                {"name": "link_id", "type": "uuid", "required": True, "in": "path", "description": "The traceability link to delete."},
            ],
        ),
    ),
)
