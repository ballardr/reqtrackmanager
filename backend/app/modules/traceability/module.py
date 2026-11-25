"""
Module: modules.traceability.module

Registers the Traceability & Governance module through `MODULE_DEFINITION`: ten independently switchable
sub-components in two halves, the permission atoms and roles that administer them, governance profiles with their
organisation and project APIs and bundles, and the engine registration points the later parts plug into.

Registered contributions:
- Sub-components: Governance (`lifecycle_policies`, `approval_policies`, `review_policies`, `baseline_policies`,
  `governance_health`) and Traceability (`requirement_types`, `traceability_rules`, `traceability_exceptions`,
  `traceability_matrices`, `cross_project_traceability`). An exception and cross-project traceability `require`
  `traceability_rules`: they have no effect while it is off, and their settings are kept.
- `administrative_permissions`: `manage_org_governance`, `manage_project_governance`, `manage_org_traceability`,
  `manage_project_traceability` and `approve_traceability_exceptions`.
- `policy_resolvers` and `profile_contributors`: the lifecycle policy (`lifecycle_policy`) and the approval policy
  (`approval_policy`: the roles that may also approve a record type) of governance profiles and projects, each in force
  while its sub-component is effective.
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

from fastapi import APIRouter

from app.models.enums import OrgRole, ProjectRole
from app.modules.registry import (
    ModuleDefinition,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleSubComponentDefinition,
)
from app.modules.seams import GovernanceSeam, ModuleAdministrativePermission, PolicyResolver, ProfileContributor
from app.modules.traceability import approval_policy, bundle, lifecycle_policy
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
        template_configuration_keys=frozenset({bundle.CHOICES_KEY, bundle.APPROVAL_POLICIES_KEY}),
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
    ),
    profile_contributors=(
        ProfileContributor(
            key="lifecycle", name="Lifecycle policy", count_rows=lifecycle_policy.count_rows,
            export_rows=lifecycle_policy.export_rows, import_rows=lifecycle_policy.import_rows,
            sub_component=LIFECYCLE_POLICIES,
        ),
        ProfileContributor(
            key="approval", name="Approval policy", count_rows=approval_policy.count_rows,
            export_rows=approval_policy.export_rows, import_rows=approval_policy.import_rows,
            sub_component=APPROVAL_POLICIES,
        ),
    ),
    activity_metadata_types={"governance_profile": "structure", "governance_approval_policy": "structure"},
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
