"""
Module: modules.risk_management

The Risk Management module: a project-scoped Risk register of versioned
records with a configurable type, an owner, derived inherent and residual
ratings, comments and attachments. `models` (Risk, RiskVersion, the two-tier
type vocabulary), `scoring` (the `risk` scheme), `service`/`ratings`,
`project_router`/`router` and `module`. Ratings come from core's scoring
service, so the matrix overrides apply with no module code.
"""
