"""
Module: modules.compliance

The Compliance Module, a first-party module of the modular feature system. The package is self-contained: its enums,
models and `ModuleDefinition` live here rather than in `app.models`.

Responsibilities:
- `enums`: compliance-owned vocabulary (standard version lifecycle, compliance status, applicability, approval state).
- `models`: the data model (`ComplianceStandard`, `ComplianceStandardVersion`, `ComplianceRequirement`,
  `ComplianceRequiredAction`, `ComplianceActionTypeDefinition` and the project-level rows).
- `module`: `MODULE_DEFINITION`, registered into `app.modules.registry.INSTALLED_MODULES`.

External dependencies: none of its own; the `compliance_manager` / `compliance_officer` roles use the module system's
module-contributed RBAC.
"""
