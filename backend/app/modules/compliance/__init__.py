"""
Module: modules.compliance

The Compliance Module () — the
first real first-party module built on top of the modular feature system.
This package is self-contained: its own enums, models, and
`ModuleDefinition` registration live here rather than in `app.models`/
`app.models.enums`, keeping the module's domain cleanly separable from core
application code.

Responsibilities:
- `enums`: compliance-specific vocabulary (standard version lifecycle,
  project compliance status, applicability, approval state) — deliberately
  not added to `app.models.enums`, since these are compliance-module-owned
  concepts, not core ones.
- `models`: the compliance data model — `ComplianceStandard`,
  `ComplianceStandardVersion`, `ComplianceRequirement`,
  `ComplianceRequiredAction`, `ComplianceActionTypeDefinition`.
- `module`: this module's `MODULE_DEFINITION`, registered into
  `app.modules.registry.INSTALLED_MODULES`.

External dependencies/integrations: none of its own; reuses the module
system's existing module-contributed RBAC for its
`compliance_manager`/`compliance_officer` roles rather than a bespoke
permissions mechanism.
"""
