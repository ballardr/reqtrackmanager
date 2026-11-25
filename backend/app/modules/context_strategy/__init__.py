"""
Module: modules.context_strategy

The Context & Strategy Module: five artefact types (Strategy, Future State, Pain Point, Guiding Principle, Open
Question) and the relationships between them. The package owns its enums, models and `ModuleDefinition`, not
`app.models`.

- Strategy (organisation or project scope): `Draft -> Proposed -> Under Review -> Approved -> Active ->
  Superseded/Retired`, with a version-history table.
- Future State (organisation or project scope): a standalone artefact with the same lifecycle shape and its own
  version-history table.
- Pain Point (project only): no version history; a branching `Submitted -> Triaged -> {Rejected | Duplicate | Accepted
  -> Addressed -> Closed}` lifecycle and a two-tier (organisation base, project override) type vocabulary.
- Guiding Principle (organisation or project scope, version history): a shorter lifecycle without `Under Review` (see
  `enums.GuidingPrincipleStatus`).
- Open Question (project only, no version history): a branching `Open -> Investigating -> {Withdrawn | Ready for
  Decision -> {Resolved | Withdrawn}}` lifecycle and two project roles (`open_question_owner`,
  `open_question_resolver`; §9.4's "Question Owner / Project Manager" and "Decision Maker" tiers; see `module.py`).

Responsibilities:
- `enums`: scope discriminators, small vocabularies and each artefact's lifecycle enum (Future State and Guiding
  Principle keep their own; see `enums.py`).
- `models`: `Strategy` (identity row) and `StrategyVersion` (temporal snapshot, as `RequirementVersion`) with the module's
  own comment and attachment tables, repeated for Future State and Guiding Principle; Pain Point and Open Question have
  the comment and attachment tables without a snapshot.
- `service`: creation, versioning (`apply_new_version`), lifecycle transitions and the project-scoped file-ownership
  hook, with distinct function names per artefact.
- `_shared`: helpers shared by `router` and `project_router` (RBAC composition, identity-to-API mapper, ownership-chain
  lookup).
- `router` / `project_router`: Strategy, Future State and Guiding Principle have both surfaces; Pain Point and Open
  Question are project-scoped, and `router.py` carries only the organisation-level `PainPointTypeDefinition` CRUD.
- `module`: `MODULE_DEFINITION`, including `mcp_tools` (read tools for all five types and their relationships, write
  tools for create, update, relationship, supersession and lifecycle transitions; the five approve and decide-tier
  actions are gated by `app.services.rbac.require_ai_approvals_enabled` through MCP).

Design decisions:
- Comments and attachments use module-local `StrategyComment`, `StrategyCommentFile` and `StrategyFile` sets (and
  matching sets per artefact), not a new member of the core `ReviewTargetType` enum: a comment targets one record, so
  no polymorphic target is needed, and adding a member to a closed core enum per module breaks the Modular Feature
  System Boundary (as `ProjectSequenceCounter.artefact_type` showed; see `docs/decisions.md`).
- Cross-artefact relationships use the generic relationship layer (`RequirementLinkTypeDefinition`, `ArtefactLink`: Pain
  Point drives Strategy, Strategy defines Future State, Guiding Principle supports Strategy, supersession links). The
  three types targeting a Decision Management `Decision` (Strategy informs, Guiding Principle guides, Open Question
  resolved by) stay reserved (see `service.py` and `docs/decisions.md`).
- Every model ships with a way to reach it (`docs/modules.md`'s worked checklist), so the organisation and project tables
  are both tested.

External dependencies/integrations: none of its own.
"""
