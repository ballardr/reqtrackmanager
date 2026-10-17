"""
Module: modules.context_strategy

The Context & Strategy Module: five artefact types — Strategy, Future State,
Pain Point, Guiding Principle and Open Question — plus the cross-artefact
relationships between them.

- **Strategy** (organisation- or project-scoped): a `Draft -> Proposed ->
  Under Review -> Approved -> Active -> Superseded/Retired` review lifecycle
  and a full version-history table.
- **Future State** (org/project scope): a standalone artefact (kept separate
  from Strategy rather than folded into it) with an identical lifecycle shape
  and its own version-history table.
- **Pain Point** (project-scoped only): no version-history table, a
  **branching** `Submitted -> Triaged -> {Rejected | Duplicate | Accepted ->
  Addressed -> Closed}` lifecycle, and a two-tier (org-shared-base,
  project-override) configurable type vocabulary.
- **Guiding Principle** (org/project scope, full version-history table): a
  **shorter** `Draft -> Proposed -> Approved -> Active -> Superseded/Retired`
  lifecycle (no `Under Review` step — see `enums.GuidingPrincipleStatus`'s own
  docstring).
- **Open Question** (project-scoped only, no version-history table): its own
  **branching** `Open -> Investigating -> {Withdrawn | Ready for Decision ->
  {Resolved | Withdrawn}}` lifecycle and two distinct project-scoped roles
  (`open_question_owner`/`open_question_resolver`, §9.4's
  "Question Owner / Project Manager" and "Decision Maker" tiers) rather than
  Pain Point's single-role model — see `module.py`'s own docstring. The
  "Open Question -> resolved by -> Decision" relationship is reserved, not
  wired.

Self-contained, mirroring `app.modules.decisions`'s own "as a module" design
principle: this package owns its enums, models, and `ModuleDefinition`
registration rather than adding any of it to `app.models`/`app.models.enums`.

Responsibilities:
- `enums`: scope discriminators, small fixed vocabularies and each artefact's
  own lifecycle enum. Future State and Guiding Principle keep their own enums
  rather than reusing Strategy's (see `enums.py`'s own module docstring for
  why).
- `models`: `Strategy` (identity row) / `StrategyVersion` (temporal content
  snapshot, mirroring `models.requirement.RequirementVersion` exactly) plus
  this module's own comment/attachment tables (`StrategyComment`,
  `StrategyCommentFile`, `StrategyFile`), repeated for Future State and
  Guiding Principle; Pain Point and Open Question have the same
  comment/attachment tables without the version snapshot.
- `service`: creation, versioning (`apply_new_version`), the lifecycle
  transition functions, and the project-scoped file-ownership resolution
  hook, under distinct function names per artefact.
- `_shared`: helpers shared by the org-scoped (`router`) and project-scoped
  (`project_router`) routers — RBAC composition, the identity-to-API-shape
  mapper, ownership-chain lookup — for every artefact type.
- `router` / `project_router`: the org-scoped and project-scoped
  `APIRouter`s. Strategy, Future State and Guiding Principle ship both
  surfaces, since their org/project dual scope is central to their field
  spec. Pain Point and Open Question are project-scoped only; `router.py`
  carries only the org-level `PainPointTypeDefinition` CRUD that Pain
  Point's type vocabulary needs.
- `module`: this module's `MODULE_DEFINITION`, registered into
  `app.modules.registry.INSTALLED_MODULES`, including the `mcp_tools`
  declarations (read tools for all five artefact types and their
  relationships, and — per the 2026-09-22 write-enabled-MCP decision — write
  tools for create/update/relationship/supersession/lifecycle-transition
  endpoints, with the five approve/decide-tier actions additionally gated by
  `app.services.rbac.require_ai_approvals_enabled` when reached through MCP).

**Deliberate deviation, flagged explicitly**: comments/attachments reuse a
**module-local** `StrategyComment`/`StrategyCommentFile`/`StrategyFile` set
(and the matching sets for each other artefact), not a new `ReviewTargetType`
member on the core `app.models.enums.ReviewTargetType` enum. Decision
Management did not extend `ReviewTargetType` either; its own `models.py`
docstring records the same module-local-table choice. That core machinery has
never been extended by any module, and a Strategy comment/attachment only
ever targets one `Strategy` (no polymorphic target needed), so a
module-local table is simpler than reusing the polymorphic core one, not just
more boundary-correct. Adding a member to `ReviewTargetType` — a plain,
closed `enum.Enum` in a core file — to support one specific module would also
be exactly the "hand-edit a core enum per module" failure mode `CLAUDE.md`'s
"Modular Feature System Boundary" section calls out (the same class of issue
as `ProjectSequenceCounter.artefact_type`'s own correction). See
`docs/decisions.md` for the full account.

Cross-artefact relationships use the platform's generic relationship layer
directly (`RequirementLinkTypeDefinition`/`ArtefactLink`; Pain Point ->
drives -> Strategy, Strategy -> defines -> Future State, Guiding Principle ->
supports -> Strategy, each artefact's own supersession links, etc.). The
three relationship types whose target is a Decision Management `Decision`
(Strategy -> informs -> Decision, Guiding Principle -> guides -> Decision,
Open Question -> resolved by -> Decision) stay reserved, not built — see
`service.py`'s own "Decision-target relationships stay reserved" docstring
section and `docs/decisions.md`.

Design decision: no artefact lands as data-model-only. Every model ships with
a way to reach it (the "never land a model with no way to reach it"
convention, see `docs/modules.md`'s worked checklist), so "is this the org
table or the project table" is never left untested.

External dependencies/integrations: none of its own.
"""
