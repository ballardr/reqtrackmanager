"""
Module: modules.compliance

The Compliance Module (docs/Compliance_Module_Requirements.md,
docs/compliance-module-plan.md Phases 5-15) — the first real first-party
module built on top of the modular feature system (module system Phases
0-4). This package is self-contained: its own enums, models, and
`ModuleDefinition` registration live here rather than in `app.models`/
`app.models.enums`, keeping the module's domain cleanly separable from core
application code, per the plan's own "as a module" design principle.

Responsibilities:
- `enums`: compliance-specific vocabulary (standard version lifecycle,
  project compliance status, applicability, approval state) — deliberately
  not added to `app.models.enums`, since these are compliance-module-owned
  concepts, not core ones.
- `models`: the compliance data model (Phase 5) — `ComplianceStandard`,
  `ComplianceStandardVersion`, `ComplianceRequirement`,
  `ComplianceRequiredAction`, `ComplianceActionTypeDefinition`.
- `module`: this module's `MODULE_DEFINITION`, registered into
  `app.modules.registry.INSTALLED_MODULES`.

Design decision: Phase 5 is data model only. `module.py`'s `get_router()`
returns `None` and `mcp_tools` is empty — the Standards Management API
(Phase 6) is what gives this module a router and its first declarative MCP
tools.

External dependencies/integrations: none of its own; reuses the module
system's existing module-contributed RBAC (Phase 2) for its
`compliance_manager`/`compliance_officer` roles rather than a bespoke
permissions mechanism.
"""
