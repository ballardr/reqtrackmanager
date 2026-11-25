"""
Module: modules.traceability.module

Registers the Traceability & Governance module through `MODULE_DEFINITION`: ten independently switchable
sub-components in two halves, the permission atoms and roles that administer them and the engine registration points the
later parts plug into.

Registered contributions:
- Sub-components: Governance (`lifecycle_policies`, `approval_policies`, `review_policies`, `baseline_policies`,
  `governance_health`) and Traceability (`requirement_types`, `traceability_rules`, `traceability_exceptions`,
  `traceability_matrices`, `cross_project_traceability`). An exception and cross-project traceability `require`
  `traceability_rules`: they have no effect while it is off, and their settings are kept.
- `administrative_permissions`: `manage_org_governance`, `manage_project_governance`, `manage_org_traceability`,
  `manage_project_traceability` and `approve_traceability_exceptions`.
- Roles: Governance Manager and Traceability Manager, each as a project role and an organisation role (the organisation
  role also holds the project atom, so it manages every project's policy).

Design decisions:
- The module stores nothing yet, so it declares why it has no bundle hooks; each part that adds tables adds its own.
- `default_enabled=False`: an organisation opts in; a fresh install is switched on through the server default table.
- The engine seams live in core `services/` with each type's current behaviour as the default; this module only
  registers resolvers, checks and adapters on top (`modules.seams`), so core never imports it.

Dependencies: `modules.registry`, `modules.seams`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.models.enums import OrgRole, ProjectRole
from app.modules.registry import ModuleDefinition, ModuleRoleDefinition, ModuleSubComponentDefinition
from app.modules.seams import ModuleAdministrativePermission
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
    """The module's organisation-scoped router; none until a part adds endpoints."""
    return None


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
    no_org_bundle="The module stores no organisation data yet.",
    no_project_bundle="The module stores no project data yet.",
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
