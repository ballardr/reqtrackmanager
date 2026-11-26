"""
Module: modules.traceability.module

Registers the Traceability & Governance module through `MODULE_DEFINITION`: ten independently switchable
sub-components in two halves, the permission atoms and roles that administer them, governance profiles with their
organisation and project APIs and bundles, and the engine registration points the later parts plug into.

Registered contributions:
- Frontend: a project nav entry for Governance Health, shown while the `governance_health` part is in effect; the policy
  and profile screens are administration sections registered by the module's `module.ts`.
- Governance health (`health`, `health_router`): the project's figures per record category, reviews due and baseline check
  results, live or from a snapshot; the hourly `health_snapshots` job refreshes interval snapshots. MCP tools and guidance
  (`mcp_tools`, `mcp_guidance.md`) configure governance and read the health.
- Sub-components: Governance (`lifecycle_policies`, `approval_policies`, `review_policies`, `baseline_policies`,
  `governance_health`) and Traceability (`requirement_types`, `traceability_rules`, `traceability_exceptions`,
  `traceability_matrices`, `cross_project_traceability`). An exception and cross-project traceability `require`
  `traceability_rules`: they have no effect while it is off, and their settings are kept.
- `administrative_permissions`: `manage_org_governance`, `manage_project_governance`, `manage_org_traceability`,
  `manage_project_traceability` and `approve_traceability_exceptions`.
- `policy_resolvers` and `profile_contributors`: the lifecycle policy (`lifecycle_policy`) and, with its part, the stage
  workflow policy (`stage_workflow_policy`: the organisation workflow a profile requires of stages), the approval policy
  (`approval_policy`: the roles that may also approve a record type), the review policy (`review_policy`: the interval,
  reminder lead and default owner of a record type) and the baseline policy (`baseline_policy`: the checks that run before
  a baseline and the fields a record must have filled) of governance profiles and projects, each in force while its
  sub-component is effective.
- `baseline_check_providers`: the required-fields and required-approvals checks (`baseline_checks`); a check runs only where
  a baseline policy enables it.
- Roles: Governance Manager and Traceability Manager, each as a project role and an organisation role (the organisation
  role also holds the project atom, so it manages every project's policy).

Design decisions:
- Governance profiles (organisation-owned policy sets, `profiles`, `profile_resolution`) are module-level: they serve
  every policy sub-component, so they need only the module to be on. Each later policy table joins a profile through a
  registered `ProfileContributor`, so the profile screens and bundles need no per-table code. Profiles, targets and
  exemptions travel in the organisation bundle; a project's choices in the project bundle (project configuration,
  copied to a project made from a template).
- `default_enabled=False`: an organisation opts in; a fresh install is switched on through the server default table.
- The engine seams live in core `services/` with each type's current behaviour as the default; this module only
  registers resolvers, checks and adapters on top (`modules.seams`), so core never imports it.

Dependencies: `modules.registry`, `modules.seams`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from app.models.enums import OrgRole, ProjectRole
from app.modules.registry import (
    ModuleDefinition,
    ModuleFrontendManifest,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleScheduledJob,
    ModuleSubComponentDefinition,
    PrincipalReference,
)
from app.modules.seams import (
    BaselineCheckProvider,
    GovernanceSeam,
    ModuleAdministrativePermission,
    PolicyResolver,
    ProfileContributor,
)
from app.modules.traceability import (
    approval_policy,
    baseline_checks,
    baseline_policy,
    bundle,
    health,
    lifecycle_policy,
    review_policy,
    stage_workflow_policy,
)
from app.modules.traceability._shared import (
    APPROVAL_POLICIES,
    APPROVE_TRACEABILITY_EXCEPTIONS,
    BASELINE_POLICIES,
    CROSS_PROJECT_TRACEABILITY,
    GOVERNANCE_HEALTH,
    GOVERNANCE_MANAGER_ROLE,
    GOVERNANCE_ORG_MANAGER_ROLE,
    LIFECYCLE_POLICIES,
    MANAGE_ORG_GOVERNANCE,
    MANAGE_ORG_TRACEABILITY,
    MANAGE_PROJECT_GOVERNANCE,
    MANAGE_PROJECT_TRACEABILITY,
    REQUIREMENT_TYPES,
    REVIEW_POLICIES,
    TRACEABILITY_EXCEPTIONS,
    TRACEABILITY_MANAGER_ROLE,
    TRACEABILITY_MATRICES,
    TRACEABILITY_MODULE_KEY,
    TRACEABILITY_ORG_MANAGER_ROLE,
    TRACEABILITY_RULES,
)
from app.modules.traceability.mcp_tools import build_mcp_tools
from app.modules.traceability.models import GovernanceReviewPolicy

# Hand-written agent usage guidance, embedded in the MCP skill (see ModuleDefinition.mcp_guidance).
_MCP_GUIDANCE = (Path(__file__).parent / "mcp_guidance.md").read_text(encoding="utf-8")


def get_router() -> APIRouter | None:
    """The module's organisation-scoped router (governance profiles). Imported inside the function so the module's
    own registration cannot form an import cycle."""
    from app.modules.traceability.router import router

    return router


def get_project_router() -> APIRouter | None:
    """The module's project-scoped router (a project's view of the profiles that reach it and its choices), imported
    lazily for the same reason as `get_router`."""
    from app.modules.traceability.project_router import router

    return router


MODULE_DEFINITION = ModuleDefinition(
    key=TRACEABILITY_MODULE_KEY,
    name="Traceability & Governance",
    description=(
        "Governance: lifecycle, approval, review and baseline policy per record type, set by the organisation as "
        "profiles that can be enforced, defaulted or opted into, with a health view. Traceability: requirement types "
        "and rules for which links a record must carry, with status, exceptions, cross-project reach and matrices."
    ),
    version="0.1.0",
    default_enabled=False,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    models_import_path="app.modules.traceability.models",
    migrations_dir="app/modules/traceability/migrations",
    org_bundle_hooks=ModuleOrgBundleHooks(
        export=bundle.export_org_data, import_=bundle.import_org_data,
        export_with_projects=bundle.export_org_project_data, import_with_projects=bundle.import_org_project_data,
    ),
    project_bundle_hooks=ModuleProjectBundleHooks(
        export=bundle.export_project_data, import_=bundle.import_project_data,
        template_configuration_keys=frozenset({
            bundle.CHOICES_KEY, bundle.APPROVAL_POLICIES_KEY, bundle.REVIEW_POLICIES_KEY, bundle.BASELINE_POLICY_KEY,
            bundle.HEALTH_SETTINGS_KEY,
        }),
        template_excluded={
            bundle.HEALTH_RUNNER_KEY: (
                "A named person who runs the baseline checks is not copied: they must hold a role in the project that is "
                "made from the template, which names its own."
            ),
        },
    ),
    frontend_manifest=ModuleFrontendManifest(
        tier="installed",
        nav_label="Governance Health",
        nav_path=f"/projects/{{project_id}}/modules/{TRACEABILITY_MODULE_KEY}/health",
        nav_icon="gauge",
        nav_sub_component=GOVERNANCE_HEALTH,
    ),
    sub_components=(
        ModuleSubComponentDefinition(key=LIFECYCLE_POLICIES, name="Lifecycle policies"),
        ModuleSubComponentDefinition(key=APPROVAL_POLICIES, name="Approval policies"),
        ModuleSubComponentDefinition(key=REVIEW_POLICIES, name="Review policies"),
        ModuleSubComponentDefinition(key=BASELINE_POLICIES, name="Baseline policies"),
        ModuleSubComponentDefinition(key=GOVERNANCE_HEALTH, name="Governance health"),
        ModuleSubComponentDefinition(key=REQUIREMENT_TYPES, name="Requirement types"),
        ModuleSubComponentDefinition(key=TRACEABILITY_RULES, name="Traceability rules"),
        ModuleSubComponentDefinition(
            key=TRACEABILITY_EXCEPTIONS, name="Traceability exceptions", requires=(TRACEABILITY_RULES,),
        ),
        ModuleSubComponentDefinition(key=TRACEABILITY_MATRICES, name="Traceability matrices"),
        ModuleSubComponentDefinition(
            key=CROSS_PROJECT_TRACEABILITY, name="Cross-project traceability", requires=(TRACEABILITY_RULES,),
        ),
    ),
    policy_resolvers=(
        PolicyResolver(
            seam=GovernanceSeam.LIFECYCLE, resolve_project=lifecycle_policy.resolve_project_policy,
            sub_component=LIFECYCLE_POLICIES,
        ),
        PolicyResolver(
            seam=GovernanceSeam.APPROVAL, resolve=approval_policy.resolve_policy, sub_component=APPROVAL_POLICIES,
        ),
        PolicyResolver(seam=GovernanceSeam.REVIEW, resolve=review_policy.resolve_policy, sub_component=REVIEW_POLICIES),
        PolicyResolver(
            seam=GovernanceSeam.STAGE_WORKFLOW, resolve_project=stage_workflow_policy.resolve_project_policy,
            sub_component=LIFECYCLE_POLICIES,
        ),
        PolicyResolver(
            seam=GovernanceSeam.BASELINE, resolve_project=baseline_policy.resolve_project_policy, sub_component=BASELINE_POLICIES,
        ),
    ),
    baseline_check_providers=(
        BaselineCheckProvider(
            key=baseline_checks.REQUIRED_FIELDS_KEY, name="Required fields", artefact_types=(),
            check=baseline_checks.check_required_fields, sub_component=BASELINE_POLICIES,
        ),
        BaselineCheckProvider(
            key=baseline_checks.REQUIRED_APPROVALS_KEY, name="Required approvals",
            artefact_types=baseline_checks.APPROVAL_CHECKED_TYPES, check=baseline_checks.check_required_approvals,
            sub_component=BASELINE_POLICIES,
        ),
    ),
    profile_contributors=(
        ProfileContributor(
            key="lifecycle", name="Lifecycle policy", count_rows=lifecycle_policy.count_rows,
            export_rows=lifecycle_policy.export_rows, import_rows=lifecycle_policy.import_rows,
            sub_component=LIFECYCLE_POLICIES,
        ),
        ProfileContributor(
            key="stage_workflow", name="Stage workflow policy", count_rows=stage_workflow_policy.count_rows,
            export_rows=stage_workflow_policy.export_rows, import_rows=stage_workflow_policy.import_rows,
            sub_component=LIFECYCLE_POLICIES,
        ),
        ProfileContributor(
            key="approval", name="Approval policy", count_rows=approval_policy.count_rows,
            export_rows=approval_policy.export_rows, import_rows=approval_policy.import_rows,
            sub_component=APPROVAL_POLICIES,
        ),
        ProfileContributor(
            key="review", name="Review policy", count_rows=review_policy.count_rows,
            export_rows=review_policy.export_rows, import_rows=review_policy.import_rows, sub_component=REVIEW_POLICIES,
        ),
        ProfileContributor(
            key="baseline", name="Baseline policy", count_rows=baseline_policy.count_rows,
            export_rows=baseline_policy.export_rows, import_rows=baseline_policy.import_rows, sub_component=BASELINE_POLICIES,
        ),
    ),
    stage_workflow_references=stage_workflow_policy.references,
    principal_references=(
        PrincipalReference(
            model=GovernanceReviewPolicy, field="default_owner", label="governance review policy default owners",
            audit_entity_type=review_policy.PROJECT_AUDIT_ENTITY_TYPE,
        ),
    ),
    activity_metadata_types={
        "governance_profile": "structure", "governance_approval_policy": "structure", "governance_review_policy": "structure",
        "governance_baseline_policy": "structure", "governance_health_settings": "structure",
        "governance_health_default": "structure", "governance_health": "structure",
    },
    scheduled_jobs=(ModuleScheduledJob(job_id="health_snapshots", hour=None, minute=7, run=health.run_scheduled_refresh),),
    mcp_tools=build_mcp_tools(),
    mcp_guidance=_MCP_GUIDANCE,
    administrative_permissions=(
        ModuleAdministrativePermission(
            key=MANAGE_ORG_GOVERNANCE, label="Manage organisation governance",
        ),
        ModuleAdministrativePermission(
            key=MANAGE_PROJECT_GOVERNANCE, label="Manage project governance",
            project_roles=(ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.PROJECT_MANAGER),
        ),
        ModuleAdministrativePermission(
            key=MANAGE_ORG_TRACEABILITY, label="Manage organisation traceability",
        ),
        ModuleAdministrativePermission(
            key=MANAGE_PROJECT_TRACEABILITY, label="Manage project traceability",
            project_roles=(ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.PROJECT_MANAGER),
        ),
        ModuleAdministrativePermission(
            key=APPROVE_TRACEABILITY_EXCEPTIONS, label="Approve traceability exceptions",
            org_roles=(OrgRole.ORG_ADMIN,), project_roles=(ProjectRole.PROJECT_MANAGER,),
        ),
    ),
    roles=(
        ModuleRoleDefinition(
            role_key=GOVERNANCE_MANAGER_ROLE, name="Governance Manager",
            description=(
                "Manages the project's lifecycle, approval, review and baseline policy, its profile choices and its "
                "health view."
            ),
            scope="project", permissions=(MANAGE_PROJECT_GOVERNANCE,),
        ),
        ModuleRoleDefinition(
            role_key=GOVERNANCE_ORG_MANAGER_ROLE, name="Organisation Governance Manager",
            description=(
                "Manages the organisation's governance profiles and policy, and the governance policy of every project."
            ),
            scope="org", permissions=(MANAGE_ORG_GOVERNANCE, MANAGE_PROJECT_GOVERNANCE),
        ),
        ModuleRoleDefinition(
            role_key=TRACEABILITY_MANAGER_ROLE, name="Traceability Manager",
            description="Manages the project's requirement types, traceability rules, enforcement levels and matrices.",
            scope="project", permissions=(MANAGE_PROJECT_TRACEABILITY,),
        ),
        ModuleRoleDefinition(
            role_key=TRACEABILITY_ORG_MANAGER_ROLE, name="Organisation Traceability Manager",
            description=(
                "Manages the organisation's requirement types, rules and matrix definitions, and the traceability "
                "configuration of every project."
            ),
            scope="org", permissions=(MANAGE_ORG_TRACEABILITY, MANAGE_PROJECT_TRACEABILITY),
        ),
    ),
)
