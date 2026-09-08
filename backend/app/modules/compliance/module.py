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

Phase 6 (Standards Management API, docs/compliance-module-plan.md) adds this
module's first HTTP endpoints — `get_router()` now returns a real
`APIRouter` (`app.modules.compliance.router`) mounted at
`/api/v1/orgs/{organization_id}/modules/compliance` — and its first three
MCP tools, all read-only: `compliance_list_standards`, `compliance_
get_standard_version`, `compliance_list_requirements`. No mutating tool is
declared for publish/retire — Phase 6's spec deliberately keeps the MCP
surface read-only for this module so far, mirroring `docs/mcp-server.md`'s
existing cautious default of adding write tools narrowly and deliberately
rather than by default.

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
actions this phase adds — `submit-for-approval`, `approve`, `reject` — are
**deliberately never declared here**: `project_router.py` marks `approve`/
`reject` with `app.modules.registry.APPROVAL_ACTION_ROUTE_EXTRA`, which
would exclude them from the manifest even if a future session mistakenly
added tool declarations for them, but the first line of defence is simply
that no `McpToolDefinition` for any of the three exists in this file at
all — mirroring `docs/mcp-server.md`'s existing, explicit rule that
ReqTrackManager's core approval workflow is excluded from the tool surface
on principle (accountable-human-decision, not an RBAC question).

Phase 10 (Scheduled Reviews + Notifications, §17, §18, §28) adds one more
read-only MCP tool, `compliance_list_reviews_due(project_id)`, and this
module's first `scheduled_jobs` — four APScheduler jobs (`app.modules.
registry.ModuleScheduledJob`), one per date-driven sweep `scheduler.py`
defines. No mutating tool is declared for the review CRUD/complete
endpoints this phase adds (`router.py`/`project_router.py`) — Phase 10's
own plan spec asks only for the read-only "reviews due" listing, mirroring
this module's existing cautious default of adding MCP tools narrowly.

Phase 11 (Cross-Standard Mapping + Version Impact, §19, §27) adds two more
read-only MCP tools: `compliance_list_requirement_mappings` (one
requirement's cross-standard/cross-version mapping links) and `compliance_
get_standard_version_diff` (the added/removed/modified/replaced/re-mapped
diff between two versions of a standard) — both on the org router, both
pure reads with no side effects. §27's own new mutating action, the
project-scoped version-migration endpoint (`project_router.py::migrate_
project_compliance_version`), is **deliberately never declared here** —
this module's own established, repeatedly-stated principle (see Phase 9's
notes above on approve/reject/submit-for-approval) is to add mutating MCP
tools narrowly and only when the plan's own spec explicitly calls for one;
nothing in Phase 11's spec asks for a migration tool, and migrating a
project's entire compliance assignment to a new standard version — which
touches every one of that assignment's requirement rows, can downgrade
in-flight/decided approvals, and is explicitly required by §27 to be an
"explicit action," never an implicit or automated one — is exactly the
kind of significant, wide-blast-radius mutation this module has
consistently kept off the tool surface even where doing so would have been
technically straightforward (the read-only version-diff tool above is this
action's intended "preview before you commit" companion instead). This
holds regardless of the migration endpoint's own later addition of a
`confirmed_replacement_requirement_ids` opt-in (carrying an assessment
forward across a `replaced` mapping, gated by both an org-level
`ComplianceMappingRelationshipTypeDefinition.implies_equivalence` flag and
this per-call confirmation — see `models.py`'s own Phase 11 notes) — that
addition makes the action *more* consequential, not less, so the same
exclusion applies with no reconsideration needed.

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
switched into that mode. No new MCP tools (the two new mutating surfaces
this phase adds — the project-scoped self-service assignment endpoint and
the org-scoped applicability-default/exclusion-list endpoints — are exactly
the kind of broad, wide-blast-radius mutations this module has consistently
kept off the tool surface, per Phase 4/9's established precedent) and no
new module roles (this phase widens *who may call an existing kind of
endpoint* — `ProjectRole.PROJECT_MANAGER`, already this module's existing
`_require_officer` composition — rather than introducing a new named role).

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


def _reconcile_new_project(db: Session, project: Project, actor_id: UUID) -> None:
    """This module's `ModuleDefinition.on_project_created` hook (Phase 20)
    — reconciles a brand-new project against every `applies_to_all_
    projects` standard in its organisation, the same treatment a pre-
    existing project already got when the standard was switched into that
    mode. Imported lazily for the same import-cycle reason as
    `get_router()`."""
    from app.modules.compliance.service import reconcile_new_project_for_all_standards

    reconcile_new_project_for_all_standards(db, project=project, actor_id=actor_id)


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
    ),
)
