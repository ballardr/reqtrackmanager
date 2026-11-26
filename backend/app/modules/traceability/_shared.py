"""
Module: modules.traceability._shared

Keys the Traceability & Governance module shares across its files: the module key, its sub-component keys, its role
keys and its permission atoms.

Responsibilities:
- Name each constant once so the module definition, its services and its tests agree.

Design decisions:
- The five atoms are bare administrative permissions the module contributes through
  `ModuleDefinition.administrative_permissions`; core's `ADMINISTRATIVE_PERMISSIONS` never names them.
- Governance atoms cover policy (lifecycle, approval, review, baseline, profiles, Health); traceability atoms cover
  rules, enforcement and matrices. Each is split into an organisation and a project atom so a project
  can be trusted with its own policy without being able to change what every project in the organisation inherits.

Dependencies: none.
"""

from __future__ import annotations

TRACEABILITY_MODULE_KEY = "traceability"

LIFECYCLE_POLICIES = "lifecycle_policies"
APPROVAL_POLICIES = "approval_policies"
REVIEW_POLICIES = "review_policies"
BASELINE_POLICIES = "baseline_policies"
GOVERNANCE_HEALTH = "governance_health"
TRACEABILITY_RULES = "traceability_rules"
TRACEABILITY_EXCEPTIONS = "traceability_exceptions"
TRACEABILITY_MATRICES = "traceability_matrices"
CROSS_PROJECT_TRACEABILITY = "cross_project_traceability"

GOVERNANCE_SUBCOMPONENTS = (
    LIFECYCLE_POLICIES, APPROVAL_POLICIES, REVIEW_POLICIES, BASELINE_POLICIES, GOVERNANCE_HEALTH,
)
TRACEABILITY_SUBCOMPONENTS = (
    TRACEABILITY_RULES, TRACEABILITY_EXCEPTIONS, TRACEABILITY_MATRICES, CROSS_PROJECT_TRACEABILITY,
)

MANAGE_ORG_GOVERNANCE = "manage_org_governance"
MANAGE_PROJECT_GOVERNANCE = "manage_project_governance"
MANAGE_ORG_TRACEABILITY = "manage_org_traceability"
MANAGE_PROJECT_TRACEABILITY = "manage_project_traceability"
APPROVE_TRACEABILITY_EXCEPTIONS = "approve_traceability_exceptions"

GOVERNANCE_MANAGER_ROLE = "governance_manager"
GOVERNANCE_ORG_MANAGER_ROLE = "governance_org_manager"
TRACEABILITY_MANAGER_ROLE = "traceability_manager"
TRACEABILITY_ORG_MANAGER_ROLE = "traceability_org_manager"
