"""
Module: modules.risk_management

The Risk Management module: a
first-class, project-scoped Risk register. A risk is a versioned record with a
configurable type, an owner, a derived inherent and residual rating, comments
and attachments.

Responsibilities:
- `models`: `Risk` (identity), `RiskVersion` (temporal content), the two-tier
  `RiskTypeDefinition`/`ProjectRiskType` vocabulary, and the module-local
  comment/attachment tables.
- `scoring`: the `risk` scheme registered into core's generic scoring-matrix
  mechanism (Likelihood, Consequence, Detectability).
- `service` / `ratings`: CRUD as new versions, level validation, and the
  derived inherent/residual rating.
- `project_router` / `router`: the project-scoped Risk API and the org-scoped
  Risk type vocabulary API.
- `module`: this module's `MODULE_DEFINITION`.

Design decisions: there is no Risk-specific matrix table. Ratings come from
core's scoring service, so the per-cell override, org default and project
override all apply with no module code.

External dependencies: core `services.scoring`, `services.type_vocabulary`,
`services.module_attachments` and `services.sequences`; no other module.
"""
