"""
Module: modules.context_strategy

The Context & Strategy Module (docs/plans/module-01-context-and-strategy-
plan.md) — Phases 1–6 (Organisation & Project Strategy; Future State; Pain
Points; Guiding Principles; Open Questions; cross-artefact relationships).
Phase 1 records a formal
Strategy artefact, either organisation- or project-scoped, with a `Draft ->
Proposed -> Under Review -> Approved -> Active -> Superseded/Retired` review
lifecycle and a full version-history table. Phase 2 adds a standalone
Future State artefact (Phase 0 Q1: kept separate from Strategy rather than
folded into it) with an identical lifecycle shape and its own
version-history table. Phase 3 adds Pain Points — project-scoped only, no
version-history table, a **branching** `Submitted -> Triaged -> {Rejected |
Duplicate | Accepted -> Addressed -> Closed}` lifecycle, and a two-tier
(org-shared-base, project-override) configurable type vocabulary (Phase 0
Q3). Phase 4 adds Guiding Principles — back to the Strategy/Future State
shape (org/project scope, full version-history table), but with a
**shorter** `Draft -> Proposed -> Approved -> Active -> Superseded/Retired`
lifecycle (no `Under Review` step — see `enums.GuidingPrincipleStatus`'s own
docstring). Phase 5 adds Open Questions — back to Pain Point's shape
(project-scoped only, no version-history table), with its own **branching**
`Open -> Investigating -> {Withdrawn | Ready for Decision -> {Resolved |
Withdrawn}}` lifecycle and two distinct project-scoped roles
(`open_question_owner`/`open_question_resolver`, source overview §9.4's
"Question Owner / Project Manager" and "Decision Maker" tiers) rather than
Pain Point's single-role model — see `module.py`'s own docstring. This
module's fifth and final artefact type; the "Open Question -> resolved by
-> Decision" relationship is reserved, not wired, here (Phase 0 Q5) — that
workflow is Module 4's own Phase 7. Self-contained, mirroring
`app.modules.decisions`'s own "as a module" design principle: this package
owns its enums, models, and `ModuleDefinition` registration rather than
adding any of it to `app.models`/`app.models.enums`.

Responsibilities:
- `enums`: `StrategyScope` (org/project discriminator), `StrategyPriority`/
  `StrategyTimeHorizon` (small fixed vocabularies), `StrategyStatus` (this
  module's own seven-value lifecycle enum). Phase 2 adds `FutureStateScope`/
  `FutureStateStatus`, kept as their own enums rather than reused from
  Strategy's (see `enums.py`'s own module docstring for why).
- `models`: `Strategy` (identity row) / `StrategyVersion` (temporal
  content snapshot, mirroring `models.requirement.RequirementVersion`
  exactly — Phase 0 Q4's full version-history requirement) plus this
  module's own comment/attachment tables (`StrategyComment`,
  `StrategyCommentFile`, `StrategyFile`). Phase 2 adds the exact same
  five-class shape for `FutureState`.
- `service`: creation, versioning (`apply_new_version`), the seven
  lifecycle-transition functions, and the project-scoped file-ownership
  resolution hook — for both Strategy and (Phase 2) Future State, under
  distinct function names.
- `_shared`: helpers shared by the org-scoped (`router`) and project-scoped
  (`project_router`) routers — RBAC composition, the identity-to-API-shape
  mapper, ownership-chain lookup — for both artefact types.
- `router` / `project_router`: the org-scoped and project-scoped
  `APIRouter`s — both a real, working HTTP surface as of Phase 1 (unlike
  Decision Management's own Phase 1, which was data-model-only; that
  phase's own scope combined what that module split across two phases),
  extended in Phase 2 with the same surface for Future State.
- `module`: this module's `MODULE_DEFINITION`, registered into
  `app.modules.registry.INSTALLED_MODULES`.

**Deliberate deviation from Phase 1's own brief, flagged explicitly**:
comments/attachments reuse a **module-local** `StrategyComment`/
`StrategyCommentFile`/`StrategyFile` set, not a new `ReviewTargetType.
STRATEGY` member on the core `app.models.enums.ReviewTargetType` enum the
brief asked for. Checked against actual precedent before deciding this,
per that phase's own instruction to "check how Decision Management wired
its own `ReviewTargetType` member end-to-end" — **Decision Management did
not extend `ReviewTargetType` at all**; its own `models.py` docstring
records the same module-local-table choice, for the same reason repeated
here: that core machinery has never been extended by any module, and a
Strategy comment/attachment only ever targets one `Strategy` (no
polymorphic target needed), so a module-local table is simpler than
reusing the polymorphic core one, not just more boundary-correct. Adding a
member to `ReviewTargetType` — a plain, closed `enum.Enum` in a core file —
to support one specific module would also be exactly the "hand-edit a
core enum per module" failure mode `CLAUDE.md`'s "Modular Feature System
Boundary" section calls out (the same class of issue as
`ProjectSequenceCounter.artefact_type`'s own correction). See
`docs/decisions.md`'s dated entry for this phase for the full account.
Phase 2 repeats the same module-local choice for Future State
(`FutureStateComment`/`FutureStateCommentFile`/`FutureStateFile`), by
direct extension of this same reasoning, not a re-litigation of it.

Design decision: Phase 1 ships both org-scoped and project-scoped backend
API surfaces in one phase (unlike Decision Management, whose Phase 1 was
data-model-only) because Strategy's org/project dual scope (Phase 0 Q2) is
central to its own field spec, not an add-on — a data-model-only phase
with no way to reach either scope would leave "is this the org table or
the project table" untested until a later phase, contrary to this
codebase's own "never land a model with no way to reach it" convention
(see `docs/modules.md`'s worked checklist). Phase 2 follows the same
posture for Future State. Phase 3 (Pain Point, project-scoped only) ships
its full CRUD/lifecycle/type-vocabulary surface in `project_router.py`
alone; `router.py` (org-scoped) gains only the org-level
`PainPointTypeDefinition` CRUD Pain Point's own type vocabulary needs
(Phase 0 Q3), not a Pain Point resource itself.

Phase 4 (Guiding Principles) repeats Phase 2's own posture — both org- and
project-scoped backend API surfaces ship in this one phase, since Guiding
Principle's org/project dual scope is again central to its field spec, not
an add-on — and repeats the module-local comments/attachments choice above
a third time (`GuidingPrincipleComment`/`GuidingPrincipleCommentFile`/
`GuidingPrincipleFile`), by the same direct extension, not a re-litigation.

Phase 5 (Open Questions) goes back to Phase 3's posture instead — project-
scoped only, so its full CRUD/lifecycle/comments/files surface ships in
`project_router.py` alone; `router.py` (org-scoped) gains nothing at all
this time, since (unlike Pain Point) Open Question has no org-level type
vocabulary or any other org-scoped half to speak of. Repeats the
module-local comments/attachments choice a fourth time (`OpenQuestionComment`/
`OpenQuestionCommentFile`/`OpenQuestionFile`). See `module.py`'s own
docstring for why this phase's RBAC needs two distinct flat roles rather
than reusing Pain Point's single-role-plus-FGAC-fallback shape.

Phase 6 (Cross-artefact relationships) adds the actual `ArtefactLink`
wiring Phases 1-5 each deferred (Pain Point -> drives -> Strategy,
Strategy -> defines -> Future State, Guiding Principle -> supports ->
Strategy, the three artefacts' own supersession links, etc.), using
Module 0's generic relationship layer directly — no new migration, since
`RequirementLinkTypeDefinition`/`ArtefactLink` already cover it. Also adds
this module's first `mcp_tools` declarations: read tools for all five
artefact types plus their relationships, and (per the 2026-09-22
write-enabled-MCP decision) write tools for create/update/relationship/
supersession/lifecycle-transition endpoints, with the five approve/
decide-tier actions additionally gated by `app.services.rbac.
require_ai_approvals_enabled` when reached through MCP. The three
relationship types whose target is a Decision Management `Decision`
(Strategy -> informs -> Decision, Guiding Principle -> guides -> Decision,
Open Question -> resolved by -> Decision) stay reserved, not built here —
see `service.py`'s own "Decision-target relationships stay reserved"
docstring section and `docs/decisions.md`'s dated Phase 6 entry.

External dependencies/integrations: none of its own. No frontend UI yet —
Phase 7 (and Phase 8 for docs-site coverage), out of scope for this phase.
"""
