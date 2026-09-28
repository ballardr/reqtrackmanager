# Module 1 — Context & Strategy — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout. **This module now depends
on [Module 0 — Platform Foundations](module-00-platform-foundations-plan.md)**
for the generic cross-artefact relationship model — that infrastructure was
originally drafted as this module's own Phase 1, then split out on
2026-09-16 once it became clear Module 4 (Decision Management) needed the
exact same thing and shouldn't have to wait on Context & Strategy to get
it. See the index's "Module dependency graph" for the full picture.

**Source:** [future-modules-2026-09-overview.md](future-modules-2026-09-overview.md)
§5–9 (Context & Strategy, Pain Points, Future State, Guiding Principles,
Open Questions).

**Status:** Phase 0 complete (2026-09-28, user sign-off obtained — see
"Phase 0 resolutions" below). Phase 1 complete (2026-09-28 — see "Phase 1
notes" below). Phase 2 (Future State) complete (2026-09-28 — see "Phase 2
notes" below); Phase 3 (Pain Points) is next. First *content* module in
the overview's recommended build order (§46 Phase 1, after Module 0),
though the user asked for Decision Management (Module 4) and Fine-Grained
Access Control (core) to be picked up first in practice — both now shipped;
see [future-modules-2026-09-index.md](future-modules-2026-09-index.md)'s
resequenced table. This module remains a soft dependency for Decision
Management's own Phase 7 (the reserved relationship targets and the
"Create Decision from Open Question" workflow), but nothing here blocks any
other already-shipped module.

**2026-09-28 update:** Phase 0 sign-off changed the shape of this module
from five artefact types to **six** — Future State is now a separate,
first-class artefact rather than fields folded into Strategy (Phase 0 Q1,
**Decided by: User**, reversing this plan's own original recommendation).
This added a phase (Future State gets its own build phase, inserted as
Phase 2) and rippled into the relationships/frontend/docs phases below.
Every phase number below is post-resequencing; do not cross-reference the
pre-2026-09-28 numbering from other plans without checking this note.

## Status / Resume Here

3 / 9 phases complete.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: scope & open questions | [x] Complete (2026-09-28) |
| 1 | Organisation & Project Strategy | [x] Complete (2026-09-28) |
| 2 | Future State | [x] Complete (2026-09-28) |
| 3 | Pain Points | [ ] Not started |
| 4 | Guiding Principles | [ ] Not started |
| 5 | Open Questions | [ ] Not started |
| 6 | Cross-artefact relationships wired between all of the above (via Module 0) | [ ] Not started |
| 7 | Frontend UI for all six artefact types | [ ] Not started |
| 8 | Docs website coverage | [ ] Not started — depends on Phase 7 shipping |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase exists:** this module introduces new artefact types at
once (Strategy, Pain Point, Future State, Guiding Principle, Open
Question — six, after Q1's resolution below). Getting their field lists
and lifecycle states wrong is expensive to unwind once real project data
exists, so each gets confirmed before Phase 1.

**Activities:**

1. **Confirm Module 0 exists and its relationship-model shape** before
   relying on it in Phase 6 — confirmed: `ArtefactLink`
   (`backend/app/models/relationship.py`), `ReviewTargetType`
   (`backend/app/models/enums.py`), and `RequirementLinkTypeDefinition`
   (`backend/app/models/requirement_link_type.py`) all exist and match the
   shapes this plan's recommendations assume.
2. **Resolve open questions** (below).
3. **Confirm module boundaries against Requirements**: Requirement Types
   already include "Business Requirement" (overview §14/11.1 default list)
   — confirmed this module doesn't duplicate or compete with that; Strategy
   and Pain Points *drive* requirements, they aren't requirements.
4. **Confirm scope, org vs. project**: Strategy explicitly supports both
   scopes (§5.2) — resolved as a single table with a scope discriminator
   (Q2). Pain Point type configurability (§6.2) resolved as a two-tier
   org-shared-with-project-override model (Q3), not a straight mirror of
   `RequirementLinkTypeDefinition`.
5. Produced a confirmed field-level spec addendum below — **user sign-off
   obtained 2026-09-28.**

**Exit criteria:** user sign-off on the six artefacts' field lists and
lifecycle states below, before any migration. **Met.**

### Phase 0 resolutions (2026-09-28, all Decided by: User unless noted)

1. **Future State: separate artefact or Strategy sub-record?** This plan
   originally recommended folding Future State into Strategy as fields,
   per §7's own hedge ("may be represented as part of Strategy... without
   changing the conceptual model"). **User overrode this recommendation:**
   Future State is a **separate, first-class artefact** with its own
   table, lifecycle and RBAC. Reasoning given: organisation strategy and
   project/product strategy are tracked separately, and organisational
   outcomes are typically vaguer/higher-level than project outcomes —
   collapsing Future State onto Strategy would force one shape onto both.
   Strategy itself keeps its own short current-state/desired-future-state
   text fields (§5.2/5.3, unchanged), while the new Future State artefact
   provides the fuller structured elaboration (current_state, desired_state,
   target_date, outcomes, success_measures, constraints, assumptions),
   connected via the `Strategy → defines → Future State` relationship
   (§5.6) rather than embedded as columns. See Phase 2 below.
   - **Follow-on, Decided by: User:** Future State's lifecycle and
     permissions mirror Strategy's in full — `Draft → Proposed → Under
     Review → Approved → Active → Superseded/Retired`, Strategy
     Owner/Approver-equivalent roles, and (per Q4 below, applied
     consistently) a full version-history table, not an audit-trail-only
     model. Reasoning: target dates and outcomes are consequential enough
     to warrant the same review gate as the Strategy driving them.
   - **Follow-on, Decided by: Agent (flagged for awareness, not asked
     separately):** Future State gets the same org/project scope
     discriminator as Strategy (Q2), by direct analogy — the overview
     doesn't say whether Future State itself carries a scope or only
     inherits one implicitly from whichever Strategy defines it, but since
     it's now a standalone artefact linked via `ArtefactLink` rather than a
     child row with an FK to one specific Strategy, it needs its own scope
     to be listed/filtered independently the same way Strategy is. Revisit
     if a future phase finds a Future State record that logically needs to
     belong to more than one Strategy at differing scopes.
2. **Strategy scope duplication.** Confirmed: one table with a `scope`
   discriminator (`organization` / `project`) and exactly one of
   `organization_id`/`project_id` set, matching §5.2's explicit ask that
   the model support future Portfolio/Programme scopes without a
   fundamental redesign.
3. **Pain Point type configurability: org or project table?** This plan
   originally recommended pure project-scoped copy-on-create. The user's
   first answer ("live shared org reference," i.e. the
   `RequirementLinkTypeDefinition` pattern) directly conflicted with
   §6.2's explicit "configurable on a per-project basis... project
   administrators should be able to add/rename/reorder/disable/remove
   types" wording — a live shared reference means one project's rename
   would affect every sibling project referencing the same row. Flagged
   this conflict back to the user (**Decided by: Agent**, per this
   codebase's Critical Thinking instruction to say so when disagreeing,
   not silently implement a contradiction). **Resolved, Decided by:
   User:** a **two-tier model** — org table is the shared base; a project
   can locally override an org type's display name and enabled/disabled
   state without affecting siblings.
   - **Design (Decided by: Agent, following from the user's resolution):**
     `PainPointTypeDefinition` (org-scoped: `organization_id`, `name`,
     `display_order`, `is_active` — org admins manage, same shape as
     `RequirementLinkTypeDefinition`), plus `ProjectPainPointType`
     (project-scoped: `project_id`, nullable `org_type_id` FK, nullable
     `name_override`, nullable `display_order_override`, `is_enabled`
     default `true`). A row with `org_type_id` set overrides one org type
     locally (name/order/enabled) without touching the org row or other
     projects' overrides; a row with `org_type_id` null is a fully
     project-local type not backed by any org row, satisfying §6.2's "Add
     types" as a genuinely project-only action too. Effective list for a
     project = every active org type (name/order taken from its project
     override if one exists) plus every project-local type.
   - **Note correcting this plan's original text:** the original Phase 0
     Q3 also named "Guiding Principle type configurability" alongside Pain
     Point's. Re-checked against §8.3 — Guiding Principles have no `type`
     field at all (only `scope`, already resolved as org/project, same as
     Strategy). That was a copy/paste error in this plan; this two-tier
     model applies to Pain Point types only.
   - **Nested-projects fallback check (per `CLAUDE.md`'s "Nested
     (Hierarchical) Projects" rule), Decided by: Agent:** this table
     shape does not need the `resolve_effective_action_types`-style
     parent/child fallback. That mechanism exists for a vocabulary that
     lives *only* at the project level (so an unconfigured child needs to
     borrow its parent's rows); here the org table is already the always-
     present base every project — root or child — sees identically, and
     an empty `ProjectPainPointType` table already means exactly "use org
     defaults as-is," which is the correct empty-state reading with no
     extra inheritance logic needed. Revisit only if child-project-specific
     org-type overrides are later requested (i.e. a child inheriting its
     *parent project's* overrides, not just the org's).
4. **Guiding Principle versioning.** This plan originally recommended an
   audit-trail-only model as disproportionate for a short text field.
   **User overrode this: a full version-history table**
   (`GuidingPrincipleVersion`, mirroring `RequirementVersion`'s temporal
   shape — `valid_from`/`valid_to`, snapshot columns, no separate
   audit-log-only path). Applied consistently (per Q1's follow-on) to
   Strategy's own revision control (§5.4, already required, previously
   left "resolve the same way as Q4") and to Future State — so
   `StrategyVersion`, `FutureStateVersion`, and `GuidingPrincipleVersion`
   are all full version-history tables, each following `RequirementVersion`'s
   pattern.
5. **Open Question → Decision link timing.** Confirmed, unchanged from
   this plan's original text: this module ships the Open Question artefact
   and *reserves* the relationship type only; the "Create Decision from
   Open Question" workflow itself lives in Module 4's Phase 7 (renumbered
   from Phase 6 — see that plan's own Status section), not duplicated here.
6. **Comments/attachments/evidence reuse.** Confirmed: all six artefact
   types reuse the existing generic `ReviewComment`/`CommentFile`
   machinery via new `ReviewTargetType` members
   (`STRATEGY`, `FUTURE_STATE`, `PAIN_POINT`, `GUIDING_PRINCIPLE`,
   `OPEN_QUESTION`) rather than bespoke per-artefact comment tables.
7. **Nav placement.** This plan originally recommended one grouped
   "Context & Strategy" nav section using the UX style guide's `Tabs`
   pattern. **User overrode this: separate top-level nav-rail entries**
   for each of the six artefact types, diverging from the style guide's
   usual grouping preference. Noted explicitly per `CLAUDE.md`'s
   requirement to flag style-guide deviations rather than silently diverge
   — this is the user's deliberate call, not an oversight, so Phase 7
   should proceed with six top-level entries and does not need a `Tabs`
   grouping component built for this module.

## Phase 1 — Organisation & Project Strategy

**Scope** (fields from §5.2–5.3, per Phase 0 Q2/Q4 resolutions): one
`Strategy` table with `scope` (org/project) discriminator and exactly one
of `organization_id`/`project_id` set; objective/strategic theme, current
state, desired future state (short free-text fields — the fuller
structured elaboration lives on the separate Future State artefact, Phase
2), rationale, expected outcomes, constraints, measures of success,
priority, time horizon, status. Lifecycle: `Draft → Proposed → Under
Review → Approved → Active → Superseded/Retired` (§5.4) — a six-state
lifecycle, distinct from Requirement's four-state one; needs its own enum.
Approved strategy is revision-controlled via a full `StrategyVersion`
table (Phase 0 Q4, applied to Strategy).

**Why:** without a first-class Strategy record, "why is this project doing
this" lives in tribal knowledge; §5.2's stated goal (
`Organisation Strategy → Project Strategy → Requirements → Implementation`)
is otherwise unachievable.

**Roles:** Strategy Owner (Manage), Strategy Approver (Approve), project
members (View + Propose) — per §5.5, plus organisation-level equivalents
for org-scoped strategy.

## Phase 1 notes (2026-09-28)

Built the Strategy artefact's full backend: data model, versioning,
lifecycle, RBAC, comments/attachments, and a working CRUD/lifecycle API for
both org- and project-scoped Strategies — combining what Decision
Management's own plan split across two phases (data model, then API) into
this one phase, since a data-model-only phase would have left Strategy's
central org/project dual-scope design (Phase 0 Q2) untested until later.

**New files** (all under `backend/app/modules/context_strategy/`, a new
first-party module registered in `backend/app/modules/__init__.py`):
`__init__.py`, `enums.py` (`StrategyScope`, `StrategyPriority`,
`StrategyTimeHorizon`, `StrategyStatus`), `models.py` (`Strategy`,
`StrategyVersion`, `StrategyComment`, `StrategyCommentFile`,
`StrategyFile`), `service.py` (creation, `apply_new_version`, the seven
lifecycle-transition functions, `resolve_strategy_file_project_id`),
`schemas.py`, `_shared.py` (RBAC composition and the identity+version ->
API-shape mapper shared by both routers), `router.py` (org-scoped,
mounted at `/api/v1/orgs/{organization_id}/modules/context_strategy`),
`project_router.py` (project-scoped, mounted at `/api/v1/projects/
{project_id}/modules/context_strategy`), `module.py` (`MODULE_DEFINITION`),
`migrations/0048_context_strategy_data_model.py` (five tables:
`strategies`, `strategy_versions`, `strategy_comments`,
`strategy_comment_files`, `strategy_files`), and
`tests/test_context_strategy_api.py` (15 tests).

**Scope decisions, each a judgment call this phase had to make that the
plan text didn't fully settle:**

- **Comments/attachments: module-local tables, not a new `ReviewTargetType.
  STRATEGY` member (Decided by: Agent — flagged explicitly, a genuine
  deviation from this phase's own brief).** The brief asked to "check how
  Decision Management wired its own `ReviewTargetType` member end-to-end
  and mirror that" — checked, and **Decision Management never added a
  `ReviewTargetType` member at all**; its own `models.py` docstring records
  the same module-local-table choice for the same reason repeated here (the
  core `ReviewComment`/`CommentFile`/`ReviewTargetType` machinery has never
  been extended by any module, and a Strategy comment/attachment only ever
  targets one `Strategy`, so a module-local table is simpler, not just more
  boundary-correct). Adding a member to `ReviewTargetType` — a plain, closed
  `enum.Enum` in a core file (`app/models/enums.py`) — to support one
  specific module would also be exactly the "hand-edit a core enum per
  module" failure mode `CLAUDE.md`'s Modular Feature System Boundary
  section prohibits (the same class of issue as `ProjectSequenceCounter.
  artefact_type`'s own prior correction). Built `StrategyComment`/
  `StrategyCommentFile`/`StrategyFile` instead, mirroring `DecisionComment`/
  `DecisionCommentFile`/`DecisionFile` exactly.
- **No `unique_code` field (Decided by: Agent).** Unlike `Decision`, this
  phase's own field-level spec (above) lists no unique-code/identifier
  field for Strategy, and `services.sequences.generate_unique_code`'s
  underlying `ProjectSequenceCounter` is project-scoped only — an org-scoped
  Strategy has no project to hang a per-project sequence counter off of.
  Rather than inventing an org-level sequence mechanism this phase's scope
  never asked for, Strategy is identified by UUID + title only, same as
  `DecisionTemplateDefinition` (also org-scoped, also no unique code).
- **Seven `StrategyStatus` enum members reconciled against the plan's own
  "six-state lifecycle" phrasing (Decided by: Agent, flagged for
  awareness).** `Draft -> Proposed -> Under Review -> Approved -> Active ->
  Superseded/Retired` reads as six *positions*, the last of which resolves
  to one of two distinct terminal values a single `status` column can't
  combine into one — so `SUPERSEDED` and `RETIRED` are both real, separate
  enum members (seven total), the same shape `DecisionStatus` already uses
  for its own linear-chain-plus-terminal-branches lifecycle. See
  `enums.StrategyStatus`'s own docstring for the full reasoning.
- **No `REJECTED` state; `PROPOSED`/`UNDER_REVIEW` send back to `DRAFT`
  instead (Decided by: Agent).** The plan's own lifecycle text names no
  rejection-branch state (unlike `DecisionStatus`), so a Strategy sent back
  for rework returns to `DRAFT` via a `send-back` endpoint (comment
  mandatory, mirroring every other mandatory-comment-on-rejection rule in
  this codebase) rather than landing in a new terminal state nothing asked
  for.
- **No automatic supersession-link side effect on `ACTIVE -> SUPERSEDED`
  (Decided by: Agent, deliberately narrower than Decision Management's own
  `create_supersession`).** Decision Management's `SUPERSEDED` transition is
  driven by creating a typed `ArtefactLink` between two Decisions; building
  the equivalent for Strategy would mean doing part of Phase 6's job
  (cross-artefact relationship wiring) inside Phase 1. `supersede_strategy`
  is a plain status transition here — a future Phase 6 pass can layer the
  actual `ArtefactLink` recording on top of it without changing this
  function's contract.
- **RBAC: four module roles, not two (Decided by: Agent, following
  directly from Phase 0 Q2).** Strategy is the first module whose own
  artefact is scoped at *either* the org or the project level, so it
  registers `strategy_owner`/`strategy_approver` (project) *and*
  `org_strategy_owner`/`org_strategy_approver` (org) side by side —
  `_shared.py` picks whichever pair applies from the Strategy row's own
  `scope`. Approve-tier actions additionally accept a Fine-Grained Access
  Control custom-role grant of the unscoped `(strategy, approve_baseline)`
  permission atom (`_shared.require_approve_permission`), mirroring Decision
  Management's own approve gate but without that module's later sub-type
  scoping — Strategy's `scope` discriminator is structural, not a
  permission sub-type dimension, so there is nothing analogous to Decision
  Type for a permission atom to narrow against.
- **Content lock past `UNDER_REVIEW`, not just past `APPROVED`   (Decided
  by: Agent).** Unlike Decision (locked at `APPROVED`/`SUPERSEDED` only),
  Strategy keeps moving through `ACTIVE`/`SUPERSEDED`/`RETIRED` after
  approval, so the lock (`service.LOCKED_STATUSES`) covers all four of
  those states — an approved-but-not-yet-active Strategy is already past
  the point where direct content edits should bypass the review gate.
- **`seed_e2e_dataset.py` deliberately left untouched (Decided by: Agent,
  matching real precedent, not an oversight).** Checked first: Decision
  Management — also a backend-only module with no frontend yet at the time
  of its own Phase 1/4 — was never added to `seed_e2e_dataset.py` either,
  since that script backs the Playwright suite, which drives the frontend,
  and this module has none yet (Phase 7). `seed_demo_data.py` **was**
  updated (see below) since that script has no such constraint.

**`seed_demo_data.py` changes:** added `create_org_strategy`/
`create_project_strategy`/`propose_and_approve_org_strategy`/
`propose_and_approve_project_strategy` helpers and one seeded Strategy of
each scope on the existing demo org/project (an organisation-level "lead
the market" Strategy and a Falcon-3 project Strategy that traces down to
it), both walked to `Active` — ran the full script end-to-end against the
live dev/test stack to confirm it actually works, not just that it parses
(per this repo's "verify reachable and readable output" convention).

**Tests:** `backend/app/modules/context_strategy/tests/test_context_strategy_api.py`,
15 tests — create/get for both scopes, any-member-may-create, update
creates a new version, plain-member-cannot-edit (403), the full lifecycle
to `Active` via `strategy_approver`, mandatory-comment-on-send-back,
illegal-transition 409, owner-role-cannot-approve (403), a custom-role
`approve_baseline` grant satisfying the approve gate, the org-scoped
lifecycle via `org_strategy_approver`, disabled-module-404-not-403,
cross-project 404 isolation, comment add/list/author-only-edit, and direct
file attachment upload/list/unlink plus the lock check on upload.

**Verified:** full backend pytest suite green (single invocation, per this
repo's own concurrency rule), `ruff check` clean on every new/changed file,
`test_schema_migrations_match_models.py` (the model/migration drift guard)
green. A pre-existing, unrelated schema-documentation drift was found and
fixed in the same pass (see `docs/solution-architecture.md`'s updated
table-count note): the Fine-Grained Access Control (core) plan's four
tables (`custom_role_definitions`, `custom_role_permissions`,
`user_custom_role_grants`, `group_custom_role_grants`) had never been added
to that document's exhaustive table list across that plan's entire ten
phases — added alongside this phase's own five new tables rather than left
as a further, unrelated gap.

## Phase 2 — Future State

**Scope** (fields §7, per Phase 0 Q1's resolution — now a standalone
artefact, not fields on Strategy): `scope` (org/project, same discriminator
pattern as Strategy, per Q1's follow-on), current_state, desired_state,
target_date, outcomes, success_measures, constraints, assumptions.
Lifecycle mirrors Strategy's in full: `Draft → Proposed → Under Review →
Approved → Active → Superseded/Retired`, with a full `FutureStateVersion`
version-history table.

**Why:** §7 — describes the desired end state an organisation or project
is attempting to reach; §5.2's chain implies Strategy and Future State are
tightly coupled but distinctly scoped (organisational outcomes are
typically vaguer than project-level ones — the user's own reasoning for
keeping this separate from Strategy, Phase 0 Q1).

**Roles:** same as Strategy (Phase 1) — Strategy Owner-equivalent (Manage),
Strategy Approver-equivalent (Approve), project members (View + Propose).

**Relationships:** `Strategy → defines → Future State`; also linkable to
Pain Points, Requirements, Decisions (reserved target), and Guiding
Principles per §7 — wired in Phase 6 alongside every other artefact's
relationships.

## Phase 2 notes (2026-09-28)

Built the Future State artefact's full backend, into the same
`backend/app/modules/context_strategy/` package Phase 1 already
established (per this phase's own brief — not a new top-level module):
data model, temporal versioning, a seven-state lifecycle, module-
contributed RBAC for both org- and project-scoped Future States,
module-local comments/attachments, and a working CRUD/lifecycle API for
both scopes — an exact structural mirror of Phase 1's Strategy
implementation throughout, per this phase's own instruction to replicate
it "extremely closely." Everything but cross-artefact relationship wiring
(Phase 6), MCP tools (Phase 6), and frontend UI (Phase 7) is in scope and
built.

**Files changed** (all existing Phase 1 files extended, no new module
files besides the migration and this phase's own test file, per this
phase's own instruction to keep adding to the existing single large
module-wide files rather than splitting by artefact type):
`__init__.py`/`enums.py`/`models.py`/`service.py`/`_shared.py`/`schemas.py`
(module docstrings updated, new `FutureState*` symbols added under
distinct names from their `Strategy*` counterparts), `router.py`/
`project_router.py` (new `/future-states` CRUD/lifecycle/comments/files
surface appended after the existing `/strategies` surface in each file),
`module.py` (`FUTURE_STATE_ARTEFACT_TYPE` added to `artefact_types`, a
new `"future_state"` sub-component, four new `ModuleRoleDefinition`
entries, `resolve_file_owner_project_id` now tries Strategy's resolution
then Future State's), `migrations/0051_future_state_data_model.py` (five
tables: `future_states`, `future_state_versions`,
`future_state_comments`, `future_state_comment_files`,
`future_state_files`), and a new sibling test file,
`tests/test_context_strategy_future_state_api.py` (16 tests — see below
for why a sibling file rather than appending to Phase 1's own).

**Scope decisions, each a judgment call this phase had to make that the
plan text didn't fully settle:**

- **`FutureStateScope`/`FutureStateStatus` as their own enums, not a reuse
  of `StrategyScope`/`StrategyStatus` (Decided by: Agent).** Phase 0 Q1's
  follow-on says Future State's scope and lifecycle "mirror Strategy's in
  full," which settles the *shape* but not whether the two artefacts
  should share one Python enum or each own an identical one. Resolved by
  direct analogy to this module's own existing precedent one level up:
  `DecisionStatus` and `StrategyStatus` are already separate enums
  despite an identical linear-chain-plus-terminal-branches shape (see
  `enums.StrategyStatus`'s own docstring). Two independent artefact types
  sharing one vocabulary object would also mean a future divergence in
  either artefact's own lifecycle (e.g. Strategy someday gaining an
  `ARCHIVED`-distinct-from-`RETIRED` state Future State never needs)
  could only be expressed by breaking the shared enum for both, rather
  than extending one in isolation.
- **A `title` field, again (Decided by: Agent), following Strategy's own
  precedent exactly.** Source overview §7's field list doesn't name a
  title for Future State either, the same omission Phase 1 hit for
  Strategy — resolved the same way, for the same reason (every other
  artefact in this codebase has one for list/display purposes).
- **`target_date` gets its own `target_date_explicitly_set` flag on
  `apply_future_state_new_version`, not the plain `None`-means-"unchanged"
  convention every other field here uses (Decided by: Agent).**
  `target_date` is itself nullable (a Future State may have no target
  date at all), so a caller explicitly clearing it must be distinguishable
  from a caller not mentioning it. Rather than invent a new pattern, this
  reuses `services.requirements.apply_new_version`'s own existing
  `review_date`/`review_date_explicitly_set` pair verbatim — the same
  "nullable field on an otherwise carry-forward-by-`None` version-apply
  function" shape already has a precedent in this codebase, so this
  phase followed it instead of a novel sentinel.
- **Comments/attachments: module-local tables again, not a `ReviewTargetType.
  FUTURE_STATE` member (Decided by: Agent, by direct extension of Phase
  1's own flagged deviation, not a re-litigation of it).** Same reasoning
  as `StrategyComment`/`StrategyCommentFile`/`StrategyFile` — see Phase 1
  notes above and `models.py`'s own docstring.
- **No automatic supersession-link side effect on `supersede_future_state`
  (Decided by: Agent), for the same reason `supersede_strategy` has
  none** — building the actual `ArtefactLink` recording which Future
  State supersedes which is Phase 6's job, not this phase's.
- **`resolve_file_owner_project_id` tries both artefact types in sequence
  (Decided by: Agent) — Strategy's resolution first, then Future State's,
  returning whichever resolves non-`None`.** The two resolution functions
  are mutually exclusive by construction (a given `file_id` can only ever
  be attached to one Strategy or one Future State, never both), so trying
  them in sequence rather than merging their internal logic into one
  function keeps each resolver's own docstring/precedent
  (`resolve_strategy_file_project_id`, unchanged from Phase 1) intact and
  independently testable.
- **A new sibling test file, `test_context_strategy_future_state_api.py`,
  rather than appending to Phase 1's `test_context_strategy_api.py`
  (Decided by: Agent — the plan explicitly left this as the implementing
  session's own call).** Future State's own test suite is already
  comparable in size to Strategy's; one file per artefact type reads more
  cleanly than a single, ever-growing combined file as this module adds
  four more artefact types over Phases 3–5, while both files still share
  the same `tests/` package and API-helper conventions (each file defines
  its own copies of the small per-file helpers, matching this codebase's
  existing precedent of not sharing test helpers across module test files
  via a common fixture module).
- **`seed_e2e_dataset.py` deliberately left untouched (Decided by: Agent),
  matching Phase 1's own precedent exactly** — same reasoning: this
  module still has no frontend (Phase 7), and that script backs the
  Playwright suite, which drives the frontend. `seed_demo_data.py` **was**
  updated (see below).

**`seed_demo_data.py` changes:** added `create_org_future_state`/
`create_project_future_state`/`propose_and_approve_org_future_state`/
`propose_and_approve_project_future_state` helpers (mirroring the
existing Strategy helpers exactly) and one seeded Future State of each
scope on the existing demo org/project, both walked to `Active`, written
to read as the future state the existing demo Strategies are aiming at
(no actual `ArtefactLink` relationship — that's Phase 6's job; just
demo content that traces in spirit) — ran the full script end-to-end
against the live dev/test stack to confirm it actually works.

**Tests:** `backend/app/modules/context_strategy/tests/
test_context_strategy_future_state_api.py`, 16 tests — create/get for both
scopes, any-member-may-create, update creates a new version, an explicit
`target_date`-clearing update (the one behaviour Future State's own field
set adds over Strategy's), plain-member-cannot-edit (403), the full
lifecycle to `Active` via `future_state_approver`,
mandatory-comment-on-send-back, illegal-transition 409,
owner-role-cannot-approve (403), a custom-role `approve_baseline` grant
satisfying the approve gate, the org-scoped lifecycle via
`org_future_state_approver`, disabled-module-404-not-403,
disabled-sub-component-404 (both scopes), cross-project 404 isolation,
comment add/list/author-only-edit, and direct file attachment
upload/list/unlink plus the lock check on upload.

**Verified:** full backend pytest suite green — **1329 passed, 0 failed**,
single invocation, run against a fully reset `tests/container` stack
(`docker compose down -v && up -d --build`, needed to actually exercise
`seed_demo_data.py`'s new code rather than short-circuit on the
pre-existing demo org's idempotent-skip guard; this also brought
`mailhog`/`keycloak` into the running service set, resolving 14
previously-known mailhog-DNS failures as a side effect, not a regression
— see `docs/decisions.md`'s dated entry for the full account).
Migrations replayed cleanly from `0001` through this phase's own `0051`
on that fresh boot. `ruff check` clean across the whole backend.
`test_schema_migrations_match_models.py` (the model/migration drift
guard) green. `seed_demo_data.py` run end-to-end against the live
dev/test stack (rebuilt the backend container first, per this repo's own
convention that Compose services don't bind-mount source) — the new
Future State rows were independently confirmed via direct SQL (both
scopes, `active` status, `target_date` round-tripping as a real `date`).

## Phase 3 — Pain Points

**Scope** (fields §6.3, types §6.2, lifecycle §6.4): title, description,
type (per Phase 0 Q3's two-tier `PainPointTypeDefinition` +
`ProjectPainPointType` design), source, impact, evidence, priority,
status, owner, date identified. Lifecycle: `Submitted → Triaged →
{Rejected | Duplicate | Accepted → Addressed → Closed}` — note the
branching structure, not a linear chain; the enum/state-machine needs to
represent that a Triaged pain point can go to one of three next states.

**Why:** §6.1 — Pain Points capture the *problem*, deliberately distinct
from a requirement (the *solution*). Without this, "why does this
requirement exist" has no upstream anchor other than free text.

**Permissions:** deliberately broad creation (all project members can
submit — §6.5) — this is explicit in the overview and should not be
narrowed to a manager role, since "restricting creation to administrators
would prevent the system from capturing problems discovered by ordinary
users and operators" (§6.5's own stated reasoning).

## Phase 4 — Guiding Principles

**Scope** (fields §8.3, scope §8.2, permissions §8.4): name, principle
statement, rationale, scope (org/project, same discriminator pattern as
Strategy), priority, status, owner, and a full `GuidingPrincipleVersion`
version-history table (Phase 0 Q4). No `type` field — corrected from this
plan's original Q3 text, which mistakenly listed Guiding Principles
alongside Pain Point's type-configurability question; Guiding Principles
have no configurable type vocabulary in §8. Lifecycle simpler than
Strategy's — propose → approve/activate → retire, no "Under Review"/
"Superseded" split called out explicitly in §8; confirm exact enum values
against the versioning table design when this phase starts (not blocked
on anything, but worth a final check since Q4's answer changed the shape
of "revision-controlled" from what Phase 0 originally scoped).

**Why:** §8.1 — principles need to outlive any single decision so future
decisions can be checked against them; §8.4 explicitly calls out that
revision control here "protects historical Decision rationale" — i.e. this
directly serves Module 4's audit trail, not just this module's own users.

## Phase 5 — Open Questions

**Scope** (fields §9.2, lifecycle §9.3): question, context, owner,
priority, status, due/review date, evidence. Lifecycle: `Open →
Investigating → Ready for Decision → Resolved/Withdrawn`.

**Why:** §9.1 — prevents unresolved issues from being "lost in meeting
notes, email or chat"; makes "what's blocking this decision" a queryable
project state rather than something only visible in a meeting note.

**Reserved, not built here:** the "Create Decision from Open Question"
workflow itself (§9.5) — owned by Module 4's own Phase 7 (renumbered from
Phase 6), once both sides exist.

## Phase 6 — Cross-artefact relationships wired between all of the above

**Goal:** using Module 0's relationship infrastructure, wire the
relationship types listed in §5.6, §6.6, §7, §8.5, §9.2/9.4 — Pain Point →
drives → Strategy, Pain Point → motivates → Requirement, Pain Point →
raises → Open Question, Strategy → drives → Requirement, Strategy →
defines → Future State (Phase 2), Strategy → informs → Decision (reserved
target), Guiding Principle → guides → Decision (reserved target), Open
Question → resolved by → Decision (reserved target), Future State's own
links to Pain Points/Requirements/Decisions/Guiding Principles (§7), plus
every artefact's relationships to Requirement (already exists).

Relationship types whose *target* doesn't exist yet (Decision) are declared
now but only become populatable once Module 4's own Phase 7 lands (already
complete on Module 4's side except for this soft dependency).

**MCP tools.** Added 2026-09-21 at the user's explicit instruction, applied
across every not-yet-built module plan (**Decided by: User**), so that
narrow, read-only MCP-tool coverage isn't an afterthought once a module's
API exists — see `docs/modules.md` §6 and
[Module 4 (Decision Management)](module-04-decision-management-plan.md)'s
shipped `mcp_tools` (`backend/app/modules/decisions/module.py`) as the
precedent to follow. This module has no single dedicated "backend API"
phase the way Decision Management's later, more granular plan does — each
of Phases 1–5 stands up one artefact's own data model, RBAC, and (per this
codebase's own convention of never landing a model with no way to reach
it) its CRUD endpoints together, so the full REST surface across all six
artefact types is only actually complete once this phase's relationship
endpoints land, immediately before Phase 7's frontend consumes it. Once
this phase (and the endpoints it depends on from Phases 1–5) exists,
declare `McpToolDefinition` entries for the safe list/get endpoints —
candidates made concrete by each phase's own scope text: `list_strategies`/
`get_strategy` (Phase 1), `list_future_states`/`get_future_state` (Phase
2), `list_pain_points`/`get_pain_point` (Phase 3), `list_guiding_
principles`/`get_guiding_principle` (Phase 4), `list_open_questions`/
`get_open_question` (Phase 5).

**2026-09-22 update (Decided by: User):** this plan originally committed to
**read-only-only** MCP tools; per the same reversal applied to the
Compliance module (`docs/decisions.md`'s "Compliance MCP write tools +
generalized AI approval gate" entry), this module should instead commit to
**write-enabled** MCP tools once built — CRUD tools for Strategies, Future
States, Pain Points, Guiding Principles, and Open Questions declared
normally (gated by `MCP_WRITES_ENABLED` + the calling account's own RBAC
role, no special treatment). Strategy/Future State approval, Guiding
Principle activation/retirement, and Open Question resolution remain the
one exception: each is an approve/decide-type action, so it should use the
generalized org+project `allow_ai_approvals` gate
(`app.services.rbac.require_ai_approvals_enabled`, called inline the same
way Compliance's `approve_requirement`/`reject_requirement` now do) rather
than staying hard-excluded via `openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA`
— defaulting to this option for consistency with Compliance's new posture,
per no specific reason in this plan to keep them human-only instead. This
is a judgment call at plan-time (**Decided by: Agent**) about *which*
option (a)/(b) to pick per action; the underlying instruction to move this
plan off read-only-only is **Decided by: User** (2026-09-22).

## Phase 7 — Frontend UI

**Goal:** list/detail/create/edit/approve UI for all six artefact types,
using **separate top-level nav-rail entries** per Phase 0 Q7's resolution
(a deliberate divergence from the UX style guide's usual grouping
preference — see that resolution's note; no `Tabs` grouping component
needed for this module), following the UX style guide's settings-hierarchy
and confirmation-tier patterns otherwise. Enum/status values render
through label maps from day one. Playwright e2e + Storybook coverage for
each new page/component, per standing testing requirements.

## Phase 8 — Docs website coverage

Added 2026-09-21 at the user's explicit instruction, applied across every
not-yet-built module plan (**Decided by: User**); the specific scope and
placement below are this session's own judgment (**Decided by: Agent**),
modelled closely on [Module 4 (Decision Management)](module-04-decision-management-plan.md)'s
docs-website phase of the same name.

**Goal:** add Context & Strategy's user-facing surface to `docs/website/`
(the published docs site, `docs/plans/docs-website-plan.md`) — what each of
the six artefact types is and when to use it, how they relate to each
other and to Requirements, and their lifecycle states — following the
site's existing structure, tone, and Mermaid-diagram conventions (per this
repo's Documentation Requirements: prefer diagrams, validate they render
before finalising).

**Why this is its own tracked phase, not folded silently into Phase 7:**
`CLAUDE.md`'s "Docs Website Maintenance" rule already requires this check
on every change with a user-facing surface, performed in the same change
rather than deferred — so in the ordinary case this would just be part of
Phase 7's own work. It's broken out explicitly here, mirroring Decision
Management's own docs phase reasoning, because this module's user-facing
surface is unusually broad for one phase — six artefact types (Strategy,
Future State, Pain Point, Guiding Principle, Open Question), each with its
own lifecycle, landing in the same Phase 7 UI at once — so a dedicated,
checklist-visible phase makes the docs-site update harder to under-scope
or miss amid everything else Phase 7 ships.

**Scope:**

- A new docs-site page or section (matching whatever grouping the site
  already uses for other project-scoped modules, e.g. Compliance and
  Decision Management) covering: what each of Strategy, Future State,
  Pain Point, Guiding Principle, and Open Question is and when to use it;
  the Organisation Strategy → Project Strategy → Requirements →
  Implementation chain (§5.2) as a Mermaid diagram; each artefact's own
  lifecycle as a validated Mermaid state diagram, including Pain Point's
  branching `Triaged → {Rejected | Duplicate | Accepted → Addressed →
  Closed}` shape and Strategy/Future State's shared `Draft → Proposed →
  Under Review → Approved → Active → Superseded/Retired` chain (Phases 1–2);
  the cross-artefact relationships wired in Phase 6 (Pain Point → drives →
  Strategy, Strategy → defines → Future State, etc.), including which
  targets (Decision) are reserved pending Module 4's own Phase 7.
- Update the site's module/feature index or nav to include Context &
  Strategy alongside the other installed modules it already lists, and to
  reflect the six separate top-level nav entries (Phase 0 Q7).
- Cross-link from the Requirements documentation to the new page wherever
  the site already documents how a Requirement's rationale traces back to
  an upstream Pain Point or Strategy, if it does.
- **Screenshots.** — **Decided by: User** (2026-09-22, made explicit across
  every not-yet-built module plan's own "Docs website coverage" phase,
  alongside [Module 4](module-04-decision-management-plan.md)'s docs-phase
  addendum of the same date). Follow `docs/plans/docs-website-plan.md`'s
  "Screenshots" standard (1440×900 viewport, captured against the seeded
  demo dataset, stored under `docs/website/static/img/screenshots/`, real
  alt text plus a one-line caption, no surrounding "what this shows/why it
  matters" prose) and its "every Concepts, Core Features, Workflows, and
  Modules page needs at least one screenshot or diagram" bar — not forced
  onto a page whose content is genuinely diagram/table-only. Candidate
  screens for this module's own page — **Decided by: Agent**: a Pain Point
  or Strategy list view, a Strategy detail page showing its lifecycle state
  and the Org → Project → Requirement chain, a Future State detail view,
  and the Open Question → Decision conversion form.

**Status:** not started — depends on Phase 7 (frontend) actually shipping;
there is no real user-facing workflow to document accurately before then,
the same reasoning Decision Management's own docs phase and Compliance's
docs-site page both used. Not a blocker for any other phase.

## Acceptance criteria (from overview §48, Context & Strategy subset)

- Users can record Pain Points.
- Pain Points have configurable project-specific types (org-shared base
  with project-level overrides, per Phase 0 Q3).
- Default Pain Point types include Market, User and Operator.
- Users can record organisation and project strategy.
- Projects can reference organisation strategy.
- Users can record Future State as its own artefact, linked to Strategy.
- Users can record Guiding Principles.
- Guiding Principles can be organisation- or project-scoped.
- Users can record Open Questions.
- Open Questions can become Decisions. *(completed jointly with Module 4's
  own Phase 7)*
- All artefacts support appropriate typed relationships.
