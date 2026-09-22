"""
Module: modules.decisions

The Decision Management Module (docs/plans/module-04-decision-management-
plan.md) — a formal record of decisions made during a project's lifecycle
(architecture, design, engineering, strategy, operational, or other
project-specific areas), with configurable decision types, an approval
lifecycle, supersession, and org-managed Decision Templates (custom, plus
seeded standard ADR formats). Self-contained, mirroring
`app.modules.compliance`'s own "as a module" design principle: this
package owns its enums, models, and `ModuleDefinition` registration rather
than adding any of it to `app.models`/`app.models.enums`.

Responsibilities:
- `models`: `DecisionStatus` (this module's own lifecycle enum),
  `DecisionTypeDefinition` (project-scoped, seeded defaults),
  `DecisionTemplateDefinition` (org-scoped, opt-in-seeded ADR template
  packs), `Decision` itself, and this module's own comment/attachment
  tables (`DecisionComment`, `DecisionCommentFile`, `DecisionFile`) — kept
  module-local rather than reusing the core `ReviewComment`/`CommentFile`/
  `ReviewTargetType` machinery, since that machinery has never been
  extended by any module before and doing so here would set a precedent
  for a mechanism this module doesn't need (no polymorphic target — a
  comment/attachment only ever targets a `Decision`).
- `service`: seeding logic for default decision types
  (`seed_decision_types`, called from `on_project_created`) and the three
  seeded ADR template packs (`seed_decision_templates`, called from
  `on_org_created_with_choices`).
- `module`: this module's `MODULE_DEFINITION`, registered into
  `app.modules.registry.INSTALLED_MODULES`.

Design decision: Phase 1 is data model only (`docs/plans/module-04-
decision-management-plan.md`). `module.py`'s `get_router()` returns `None`
and `mcp_tools` is empty; `implemented=False` and `default_enabled=False`
reflect that nothing here is usable by an end user yet — the backend API
(Phase 4) and frontend (Phase 5) are what make it real.

External dependencies/integrations: none of its own. Reuses the module
system's module-contributed RBAC (`decision_owner`/`decision_approver`)
and Module 0's generic `services.sequences.generate_unique_code` (via this
module's own `"decision"` entry in `ModuleDefinition.artefact_types`) for
`Decision.unique_code`, rather than bespoke mechanisms for either.
"""
