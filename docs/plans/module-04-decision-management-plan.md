# Module 4 — Decision Management — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture (role/permission model, relationship model,
auditing, module-system boundary) referenced throughout this plan rather
than repeated here.

**Source:** [future-modules-2026-09-overview.md](future-modules-2026-09-overview.md),
§13 "Module 4 — Decision Management" (the source document's own heading
numbers repeat `10.x` for both §5 Module 1 subsections and this module —
a pre-existing numbering slip in the overview, not something this plan
corrects; references below use the overview's actual heading text, e.g.
"§13/10.3", to stay unambiguous).

**Status:** Proposed. Not started. This is the first module the user wants
picked up once all ten module plans exist — ahead of Module 1 and 2's
position in the overview's own recommended order (§46). See "Build-order
note" below for what that implies, and the index's "Is building Module 4
first actually possible?" section for the full dependency analysis
(mermaid graph included) that confirms it.

## Build-order note

Overview §46 puts Decision Management third (after Context & Strategy and
Stakeholders & Personas), specifically because §9.5's "Create Decision from
Open Question" workflow assumes Open Questions already exist. Checked
against the actual dependency graph (not just the overview's own narrative
ordering, which conflates "logical reading order" with "build order" —
they aren't the same thing): building Decision Management first is fully
possible, with exactly one real prerequisite.

- **Hard dependency: [Module 0 — Platform Foundations](module-00-platform-foundations-plan.md).**
  Decision ↔ Requirement and Decision ↔ Decision relationships (Phase 3
  below) need the generic cross-artefact relationship model. This used to
  be something Module 1 (Context & Strategy) would have built as a side
  effect of being first — pulling it out into its own Module 0 is what
  actually makes Decision-Management-first work cleanly, rather than this
  plan having to independently invent the same infrastructure Module 1
  would otherwise have owned. **Module 0 must exist before this module's
  Phase 3; everything before that (Phases 0–2) can start immediately.**
- **Soft dependency: Module 1 (Context & Strategy)**, only for Phase 6
  below (five reserved relationship targets — Open Question, Pain Point,
  Strategy, Guiding Principle — plus the "Create Decision from Open
  Question" workflow itself, §9.5). None of this blocks Phases 1–5; it's
  simply unreachable until Module 1 ships, whenever that happens.
- The Decision Record's own fields, lifecycle, approval, and supersession
  mechanics (§13/10.3–10.7) are otherwise entirely self-contained.

This is flagged as **Decided by: User** (the instruction to do Decision
Management first) with the consequence above **Decided by: Agent**
(the specific scoping of what's buildable now vs. deferred, and the
decision to split Module 0 out to make this build order clean rather than
improvised).

## Status / Resume Here

4 / 7 phases complete. Phase 4 (backend API + audit logging) is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: requirements clarification | [x] Complete (2026-09-21) — see addendum below |
| 1 | Data model: Decision, Decision Type, Decision Template, lifecycle, module RBAC | [x] Complete (2026-09-21) — verified: full backend suite 1124/1124, new Storybook stories 11/11, new Playwright coverage passing, real migration run against a live DB |
| 2 | Approval, rejection, and supersession workflow | [x] Complete (2026-09-21) — see "Phase 2 notes" below |
| 3 | Relationships (to Requirements, other Decisions, and reserved future types) | [x] Complete (2026-09-21) — see "Phase 3 notes" below |
| 4 | Backend API + audit logging | [ ] Not started |
| 5 | Frontend — Decision list/detail/create/approve UI | [ ] Not started |
| 6 | Reserved-relationship wiring, once Context & Strategy / Engineering Design exist | [ ] Blocked on Module 1 and/or Module 6 |
| 7 | Per-decision-type approver binding | [ ] Blocked on [Module 12](module-12-fine-grained-access-control-plan.md) (not started) — see note below |

## Phase 2 notes (2026-09-21)

Implemented entirely in `backend/app/modules/decisions/service.py` — no
router exists until Phase 4, so this phase is service-layer functions Phase
4 will later call from behind RBAC (`require_module_role`, per every other
module's own precedent — see this file's module docstring), not HTTP
endpoints of its own:

- `propose_decision` / `submit_decision_for_review` / `approve_decision` /
  `reject_decision` validate the transition against `_ALLOWED_TRANSITIONS`
  and record it via `services.audit.log_event` (`entity_type="decision"`),
  mirroring `services.stages.complete_stage`'s shape (mutate + audit, no
  commit — caller's transaction). An illegal transition raises a plain
  `ValueError`, the same convention `services.relationships.create_link`
  already uses, for Phase 4's router to translate into an HTTP 409.
- `create_supersession` creates the typed `"Supersedes"` `ArtefactLink`
  (Module 0's relationship model) between two Decisions in the same
  project, using a `RequirementLinkTypeDefinition` row this module
  fetches-or-creates on demand per organisation — that table is already a
  generic, org-shared vocabulary (not requirement-specific despite its
  name), so this is an ordinary consumer of an existing extension point,
  not a new mechanism; no core-file default-list edit or migration
  backfill needed, since it's created lazily on first use.
- Per Phase 0 addendum item 8, the *old* Decision only flips to
  `SUPERSEDED` once the link exists **and** the *new* Decision reaches
  `APPROVED` — checked from both directions this can become true
  (`_maybe_supersede` when the link is created after the new Decision is
  already approved; `_supersede_predecessors` when the new Decision is
  approved after the link already exists), and only ever overwrites a
  predecessor that's currently `APPROVED` itself.
- Content-field immutability once a Decision reaches `APPROVED`/
  `SUPERSEDED` (§13/10.6) is deliberately deferred to Phase 4 — every
  existing lock-after-approval check in this codebase
  (`services.requirements.is_locked`'s call sites) lives at the router
  layer, and no Decision update endpoint exists yet.

**Verified**: `app/modules/decisions/tests/test_decisions_workflow.py` (new,
11 tests) — full legal transition sequence with audit trail assertions,
rejection with comment recorded in audit `detail`, a parametrized illegal-
transition matrix, both supersession-flip orderings (link-then-approve and
approve-then-link), link-type reuse across multiple supersessions in one
org, and the validation errors (self-supersession, cross-project, already-
superseded, duplicate link). `ruff check` clean. Full backend suite run
after this change (see this entry's own `docs/decisions.md` counterpart for
the final pass/fail count).

## Phase 3 notes (2026-09-21)

Implemented in `backend/app/modules/decisions/service.py`, same as Phase 2 —
no router exists until Phase 4, so this is service-layer functions only:

- `_get_or_create_supersedes_link_type` (Phase 2) was generalised into
  `_get_or_create_link_type(db, organization_id, *, forward_name,
  reverse_name)` rather than duplicated four more times — the exact same
  fetch-or-create logic against the org-shared, generic
  `RequirementLinkTypeDefinition` table, now parameterised on the link
  type's forward/reverse names. `create_supersession` was updated to call
  it with the `"Supersedes"`/`"Is superseded by"` names; behaviour is
  unchanged (covered by the existing Phase 2 tests, which still pass).
- `create_decision_requirement_link(db, *, decision, requirement, kind,
  actor_id)` — Decision -> Requirement, `kind` one of
  `DecisionRequirementLinkKind.IMPLEMENTS`/`AFFECTS` (source overview
  §13/10.7). Validates same-project (`ValueError` otherwise, mirroring
  `create_supersession`'s convention), then creates the typed `ArtefactLink`
  with `target_type=ArtefactType.REQUIREMENT.value` — no registry change
  needed, since `REQUIREMENT` is one of the two built-in core artefact
  types `services.relationships.create_link` already accepts.
- `create_decision_decision_link(db, *, source_decision, target_decision,
  kind, actor_id)` — Decision -> Decision, `kind` one of
  `DecisionDecisionLinkKind.DEPENDS_ON`/`CONFLICTS_WITH`. Validates
  self-link and same-project, exactly like `create_supersession`.
  `"Supersedes"` itself keeps its own dedicated function rather than
  folding into this one, since only it drives the status-flip side effect.
- "Implements", "Depends on", and "Conflicts with" already exist in
  `services.definitions.DEFAULT_LINK_TYPES` (seeded per new organisation);
  "Affects" does not. Both cases go through the same lazy fetch-or-create
  helper regardless — an org's admin may have renamed/deleted a seeded row,
  or the org may predate a given default, so nothing here relies on the
  seeded rows still existing under their original names.
- Both new functions pre-check with `services.relationships.
  get_link_between` and raise `ValueError` on an exact duplicate, same
  convention as `create_supersession`'s own duplicate check.
- The five other relationship targets in this phase's original scope (Open
  Question, Pain Point, Strategy, Guiding Principle, Compliance, Design)
  remain reserved but deferred to Phase 6, blocked on modules that don't
  exist yet — not built here, per this plan's own Phase 3/Phase 6 split.

**Verified**: new `app/modules/decisions/tests/test_decisions_relationships.py`
(9 tests) — Implements/Affects link creation (including link-type
lazy-creation on first use), Depends-on/Conflicts-with link creation, and
the validation errors (cross-project for both relationship groups, self-link
for Decision<->Decision, duplicate link for both). `ruff check` clean. Full
backend suite run after this change (see this entry's own `docs/decisions.md`
counterpart for the final pass/fail count).

## Phase 0 addendum (2026-09-21) — resolved open questions

Module 0 is confirmed complete (all 4 phases, 2026-09-21) — the one hard
dependency this plan's build-order note flagged. Phase 3 is therefore no
longer blocked; it's simply not started yet, same as every other phase.

**New requirement surfaced when this phase actually ran**: the user asked
for **Decision Templates** (custom, org-managed templates plus seeded
standard ADR formats referencing
[github.com/architecture-decision-record/architecture-decision-record](https://github.com/architecture-decision-record/architecture-decision-record)),
with the ability to seed an organisation with a template set at creation
time. This did not exist anywhere in the source overview (§13/10.x has no
"template" concept at all) — it's a genuinely new scope addition, not a
gap-fill of something the overview already specified. Resolved below
alongside the plan's own original 7 open questions.

**Decided by: User** (via clarifying questions this session):

1. **Template seeding UX**: opt-in picker at organisation-creation time,
   not always-auto-seed. The org-creation form/endpoint offers named
   template-pack choices; only checked ones are seeded. Chosen over
   always-seed-then-let-admin-delete specifically to keep an org's template
   library free of packs its admin never wanted, at the cost of a new,
   generic core extension point (org-creation choices — see Phase 1 scope
   below) that mirrors `on_org_created`/`project_nav_visible`'s existing
   "core file never imports a specific module" pattern rather than
   special-casing Decision Management's own choices into `routers/orgs.py`.
2. **Template shape**: per-field guidance text, not a single free-text
   skeleton. A `DecisionTemplateDefinition` stores placeholder/example
   prompt text for each of Decision's existing free-text fields (context,
   options_considered, chosen_option, rationale, consequences, assumptions,
   constraints). Picking a template at Decision-creation time (Phase 5)
   pre-fills those fields with editable guidance text. No new fields are
   needed on `Decision` itself — a template is a creation-time convenience,
   not a persistent relationship, so `Decision` holds no FK back to the
   template it was created from (see rationale below).
3. **Approval model (original Q2/2a)**: simple placeholder role for now —
   a single configurable `decision_approver` module role per project — not
   a full per-Decision approver-assignment mechanism. Matches the plan's
   own original recommendation: avoids building a bespoke policy engine
   here that the future Governance module (§29-36, Approval Policies) will
   likely replace outright.
4. **Lifecycle (original Q1)**: `Rejected` is a real, explicit status
   value, not just an audit event layered on `Draft`/`Under Review`. Final
   enum: `Draft -> Proposed -> Under Review -> Approved`, with `Rejected`
   and `Superseded` as the two other reachable terminal-ish states —
   `DecisionStatus` in `app.modules.decisions.models`, its own enum, not a
   reuse of `RequirementStatus` (per the plan's original framing).

**Decided by: Agent** (lower-risk, reversible, or already effectively
settled by the overview's own explicit text — flagged here rather than
re-asked):

5. **Decision Type scope (original Q3)**: project-scoped, mirroring
   `ActionTypeDefinition` exactly (id, project_id, name, sort_order; no
   `is_enabled` flag — no existing definition table in this codebase has
   one, and introducing a new column shape not used anywhere else for a
   "disable without deleting" behaviour the overview only mentions in
   passing isn't justified yet). The overview's own text settles this
   directly ("Types should be configurable **per project**... Projects
   should be able to add/rename/reorder/disable/remove types") — this
   was flagged as an open question mainly out of caution, not real
   ambiguity. Seeded 5 defaults (Architecture, Design, Engineering,
   Strategy, Operational) via `on_project_created`, plus a one-time
   migration backfill for every project that already exists, mirroring
   migration 0032's identical backfill for compliance action types.
6. **Decision Template scope and no persistent FK**: org-scoped (matches
   the chosen opt-in-at-org-creation seeding model) and *not* associated
   with a specific Decision Type — `DecisionTypeDefinition` is
   project-scoped while templates are org-scoped, so a template-to-type FK
   would be ambiguous about which project's types it means. A template is
   therefore a pure, decoupled starting-point convenience: pick any
   template with any type at Decision-creation time. `Decision` holds no
   FK to the template used to create it, so deleting a template never
   needs the `delete_definition_with_reassignment` machinery
   statuses/link-types/action-types use — a plain delete, and an org may
   have zero templates without issue (unlike those three, nothing requires
   at least one to exist).
7. **Seeded template packs**: three, all `default_selected=True` on the
   org-creation picker (so "create org, accept the defaults" reproduces
   today's closest equivalent of always-seeding): **Nygard (Classic ADR)**
   — Michael Nygard's original minimal format (Context/Decision/
   Consequences; no Options Considered/Rationale section, prompts say so
   explicitly rather than being left silently blank); **MADR (Markdown
   Architectural Decision Records)** — the fuller format with drivers,
   considered options, and pros/cons; **Y-Statement** — the compressed
   "in the context of X, facing Y, we decided Z to achieve Q, accepting
   R" form. Content lives in `app.modules.decisions.service` as
   `DECISION_TEMPLATE_PACKS`.
8. **Supersession semantics (original Q5)**: adopting the plan's own
   recommendation as written — superseding is a relationship the *new*
   Decision creates back to the old one, and the old Decision's status
   flips to `Superseded` only once that relationship exists *and* the new
   Decision itself reaches `Approved`. Implemented in Phase 2, not Phase 1;
   noted here only so Phase 1's `DecisionStatus` enum is built against the
   agreed final shape.
9. **Comments/attachments (original Q6) — corrected mid-Phase-1, Decided
   by: User**: an earlier version of this addendum proposed reusing
   `ReviewComment`/`CommentFile` via a new `ReviewTargetType.DECISION`
   member and justified it as "the same accepted pattern already used for
   `ArtefactType`." That justification was wrong on inspection — grepping
   confirmed no module has ever extended `ReviewTargetType` before
   (Compliance has its own separate mechanism), so this would have been a
   first precedent, not a followed one, and the user correctly stopped it:
   core files must only grow generic *extension points* for module
   behaviour, never module-specific *data*. Decision Management instead
   gets its own module-local `DecisionComment`/`DecisionCommentFile`/
   `DecisionFile` tables (`app.modules.decisions.models`), with a direct
   `decision_id` FK rather than a polymorphic `target_type` — actually
   simpler than reusing the core machinery would have been, not just more
   boundary-correct, since a Decision comment never needs to target
   anything else. `app.models.enums.ReviewTargetType` is untouched.
10. **Nav placement (original Q7)**: deferred to Phase 5 — no UI exists
    yet in Phase 1, so there's nothing to place. Not resolved here.

**Unique code generation — corrected mid-Phase-1, Decided by: User**: an
earlier version of this addendum proposed adding `DECISION = "decision"`
directly to the core `ArtefactType` enum (`app.models.enums`), reasoning
that `ProjectSequenceCounter.artefact_type`'s own docstring anticipated
exactly this. The user rejected that too, for the same reason as Q6 above,
and pointed out the deeper issue: Module 0 Phase 2 built
`ProjectSequenceCounter.artefact_type` bound to the fixed `ArtefactType`
enum instead of giving it the same dynamic, module-registrable treatment
`ArtefactLink.source_type`/`target_type` already got one phase earlier —
a real gap in Module 0's own work, not something to route around per
module. **Fixed at the root** instead: `ProjectSequenceCounter.
artefact_type` (and `services.sequences.generate_unique_code`'s signature)
now take a plain string, validated against `app.modules.registry.
get_all_registered_artefact_types()` — the exact same merged core-plus-
every-module set `ArtefactLink` already validates against — rather than a
closed Python enum. `Decision.unique_code` uses this corrected mechanism
with `"decision"` declared on `ModuleDefinition.artefact_types`
(`app.modules.decisions.module`), the ordinary way any module declares an
artefact-type string, with zero further edits to any core file required
for this or any future module. See `docs/decisions.md`'s "Module 4
(Decision Management) Phase 1 — ProjectSequenceCounter made
module-registrable" entry and the new `feedback_module_boundary_dynamic_
registration` memory this incident produced.

**New core extension point (Phase 1 scope, beyond this plan's original
text)**: `ModuleDefinition` gains `org_creation_choices: tuple[
OrgCreationChoiceOption, ...]` (declarative: key, group_label, label,
description, default_selected) and `on_org_created_with_choices:
Callable[[Session, UUID, frozenset[str]], None] | None`, plus registry
functions `get_org_creation_choices()` / `default_org_creation_choice_keys()`.
`run_on_org_created_hooks` gains an optional `selected_choice_keys`
parameter (`None` — the default, used by `services.bootstrap.run_bootstrap`
and any caller that predates this — resolves to every `default_selected`
option, so this is purely additive and never breaks an existing caller).
`routers.orgs.create_organization` gains an optional `module_choice_keys`
field on `OrganizationCreate` and a new `GET` endpoint listing the
available choices generically, so the frontend can render the picker
without hardcoding Decision Management's own pack names. See
`docs/modules.md` for the documented contract.

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase exists:** the overview is a proposal, not a spec — several
of its statements are underspecified in ways that materially change the
schema (e.g. "Decision Maker may vary by Decision" (§13/10.5) implies
per-decision approver assignment, not a single fixed role, which changes
whether approval authority is a column on `Decision` or a separate
assignment table). This phase produces a confirmed, field-level spec before
any migration is written. Unlike an earlier draft of this plan, it does
**not** need to resolve the relationship-model fork itself — that now
belongs to [Module 0](module-00-platform-foundations-plan.md), built once,
ahead of every content module, specifically so this module (and every
other) doesn't have to make that call independently.

**Activities:**

1. **Confirm Module 0 is built and usable** before this module's Phase 3
   — Phases 0–2 don't need it and can proceed regardless.
2. **Resolve open questions** (list below) with the user.
3. **Confirm audit-log fit**: read `backend/app/services/audit.py` and
   confirm Decision approval/supersession events fit the existing pattern
   used for requirement approval, rather than assuming.
4. **Confirm module RBAC shape**: read `backend/app/modules/registry.py`'s
   `ModuleDefinition` and an existing module-contributed role (Compliance's)
   to confirm how "Decision Owner" / "Decision Maker" map onto that
   mechanism before Phase 1 designs around it.
5. Produce a short addendum to this plan (or direct edits to Phases 1–3
   below) reflecting what was actually decided, before Phase 1 starts.

**Exit criteria:** user has explicitly signed off on the field list,
lifecycle states, approval model, and relationship-table shape below (as
amended by this phase) before Phase 1 begins.

### Open questions for Phase 0

1. **Lifecycle state names.** Overview §13/10.4 proposes `Draft → Proposed →
   Under Review → Approved → Superseded`, with rejected decisions "remaining
   available for historical purposes" (§10.6) but no explicit `Rejected`
   state in the diagram. Does `Rejected` need to be a fifth state, or is a
   rejected decision just one that stays in `Under Review`/`Draft` with a
   rejection recorded as an event? The existing `RequirementStatus` enum
   (`Draft/Reviewed/Approved/Archived`) is *narrower* than what the overview
   wants here — Decision needs its own enum, not reuse of `RequirementStatus`.
2. **Approval authority.** §13/10.5 says "Decision approval should be
   role-based but should allow the responsible Decision Maker to vary by
   Decision" and gives an example (architecture decisions approved by a
   technical authority, commercial/strategic ones by the PM). Is this: (a)
   a per-Decision-Type default approver role, configurable by a Governance-
   Manager-equivalent, or (b) a per-Decision explicit approver assignment
   (like `RequirementAction.assignee_id`), or (c) both — a type-level
   default that can be overridden per-Decision? This changes the schema
   materially (a join/assignment column vs. a config table).
2a. Does Decision Management need its own approver-assignment mechanism
    now, or does this properly belong to the Governance module (§29–36,
    "Approval Policies") and Decision Management should just consume
    whatever Governance later provides — meaning Phase 2 here builds a
    simple placeholder (a single configurable "Decision Approver" role) and
    Governance replaces it later? Recommend the latter to avoid building a
    bespoke policy engine inside this module that Governance will duplicate.
3. **Decision Types: seeded defaults, editable how?** §13/10.2 lists
   Architecture/Design/Engineering/Strategy/Operational as defaults,
   configurable per project (add/rename/reorder/disable/remove "where
   appropriate"). Mirror `RequirementLinkTypeDefinition`'s pattern (org- or
   project-scoped table, ordinary rows, no protected "builtin" flag) —
   confirm org-scoped (shared vocabulary across a project's org, like link
   types) or project-scoped (like `ActionTypeDefinition` appears to be,
   based on `RequirementAction.action_type_id`)?
4. **Structured rationale/consequences fields — resolved by the Engineering
   Design work.** §13/10.3 says "rationale and consequences should be
   separate structured fields rather than a single free-text description."
   Rationale/Consequences/Assumptions/Constraints are plain text fields
   (Phase 1). "Options Considered" stays a plain text field here too —
   [engineering-design-vs-decisions.md](engineering-design-vs-decisions.md)
   (the supplementary source Module 6 now builds from) settles this
   directly: substantial, evaluated, repeatable design alternatives belong
   on a `Design` record's own `DesignOption` sub-record (Module 6 Phase 2),
   linked back to the Decision that selects one — not duplicated as
   structure inside Decision itself. Decisions that have no associated
   Design (§6 of that doc — "Decisions Can Exist Without Designs," e.g. a
   market/strategy choice) simply use the plain text field with no loss of
   expressiveness. This resolves what was previously an open question here
   without waiting on Module 6 to exist first — the plain-text field is
   correct regardless of build order.
5. **Supersession semantics.** §13/10.6's example (D-102 superseded by
   D-247) — does creating D-247 automatically flip D-102's status to
   `Superseded`, or does a user do that as a separate deliberate action
   after D-247 is approved? Given "approved decisions should not normally be
   edited in-place" (§10.6), recommend: superseding is a relationship a user
   creates from the *new* decision back to the old one, and D-102's status
   changes to `Superseded` only when that relationship is created *and*
   D-247 itself reaches `Approved` — not before. Confirm with user.
6. **Comments/attachments/evidence.** §13/10.3 lists Evidence, Attachments,
   Comments as Decision fields. Confirm reuse of the existing generic
   `ReviewComment`/`CommentFile` machinery (already shared by requirements
   and change requests per `ReviewTargetType`) by adding a `DECISION` member
   to `ReviewTargetType`, rather than a bespoke comment/attachment table —
   this is the "one component per pattern" rule applied to the backend, and
   avoids re-solving a problem already solved twice.
7. **Where does Decision Management's UI live?** Nav rail entry, its own
   page, or nested under an existing project page? Needs a
   `TierAModuleDefinition` nav-rail contribution — confirm expected location
   relative to Requirements/Compliance in the nav (a UX-style-guide
   question, not just a data-model one).

## Phase 1 — Data model: Decision, Decision Type, lifecycle, module RBAC

**Goal:** stand up `Decision` and `DecisionTypeDefinition` as a new module
(`backend/app/modules/decisions/` or similar — exact key TBD in Phase 0),
following the same registration pattern Compliance uses.

**Why (risk/outcome):** without a first-class Decision artefact, decisions
made during a project live only in commit messages, chat, or
`docs/decisions.md`-style prose — informal, unsearchable, and with no
enforceable approval trail. A structured Decision record makes "why was
this built this way" answerable from the product itself, and gives
Governance (later) something concrete to attach approval/review policy to.

**Scope** (fields per overview §13/10.3, pending Phase 0 confirmation):

| Field | Notes |
|---|---|
| `unique_code` | Project-scoped, e.g. `DEC-001`, mirrors `Requirement.unique_code` / `RequirementAction.unique_code` |
| `title` | |
| `decision_statement` | The decision itself, in one sentence/paragraph |
| `decision_type_id` | FK to `DecisionTypeDefinition` |
| `status` | New enum — see Phase 0 Q1 |
| `decision_date` | Date the decision was actually made (may precede formal approval) |
| `decision_maker_id` | Nullable FK to `users` — who made/will make the call (Phase 0 Q2 shapes this) |
| `owner_id` | FK to `users` — maintains the record, distinct from decision maker |
| `context` | Text |
| `options_considered` | Text (Phase 0 Q4) |
| `chosen_option` | Text |
| `rationale` | Text, separate field (§10.3 explicit requirement) |
| `consequences` | Text, separate field |
| `assumptions` | Text |
| `constraints` | Text |
| `creator_id`, `created_at`, `updated_at` | Standard audit columns |
| `is_archived` / `archived_at` / `archived_by` | Soft-delete, matching `Requirement`/`RequirementAction` convention |

`DecisionTypeDefinition`: `name`, `sort_order`, `is_enabled`, scope (org or
project — Phase 0 Q3), mirroring `RequirementLinkTypeDefinition`'s
"ordinary, renamable/deletable rows, seeded defaults, no protected builtin
flag" pattern. Seed defaults: Architecture, Design, Engineering, Strategy,
Operational.

**Module RBAC** (per the common role model): `Decision Owner` (Manage),
`Decision Maker`/`Approver` (Approve), ordinary project members get
View + Propose. Registered as module-contributed roles, not additions to
`ProjectRole`.

## Phase 2 — Approval, rejection, and supersession workflow

**Goal:** implement the lifecycle transitions and the supersession
relationship.

**Why:** a Decision record with no enforced approval step is just a wiki
page with extra fields — the overview's entire premise (§13/10.5–10.6) is
that approval and supersession carry real, auditable weight, distinguishing
"someone proposed this" from "this was formally decided."

**Scope:**

- Status transitions: `Draft → Proposed → Under Review → Approved`, plus
  whatever Phase 0 decides about `Rejected` (Q1) and `Superseded` (Q5).
- Approval action: recorded with actor, timestamp, and optional comment —
  reuse the audit-log pattern (`services/audit.py`) rather than a bespoke
  approval-history table, per Phase 0 activity 3.
- Supersession: a typed relationship (Decision → supersedes → Decision) that,
  per Phase 0 Q5, flips the *original* decision's status to `Superseded`
  under the agreed condition. The original record is never edited in place
  (§10.6) — this is enforced at the API layer (reject any PATCH to
  `rationale`/`consequences`/etc. on an `Approved` or `Superseded` decision;
  only status-transition endpoints may touch it after approval), the same
  "approved content is immutable, transitions are separate actions"
  principle `Requirement`'s own lock-after-approval behaviour already uses.
- Rejected decisions remain queryable (§10.6) — never hard-deleted, same
  `is_archived` convention as everything else in this codebase.

## Phase 3 — Relationships (to Requirements, other Decisions, and reserved future types)

**Goal:** wire Decision into Module 0's relationship model, for the
artefact types that exist today. **This phase is blocked until Module 0
ships** — it's the one real prerequisite for building Decision Management
first (see this plan's "Build-order note").

**Why:** a Decision record with no way to link back to the Requirement it
affects, or forward to the Decision that superseded it, only satisfies half
of §13/10.1's stated purpose — the value is in the trail, not the record in
isolation.

**Scope, buildable now:**

- Decision ↔ Requirement: `Implements / Affects` (overview §13/10.7).
- Decision ↔ Decision: `Depends on`, `Supersedes`, `Conflicts with`.

**Scope, reserved but not built until the target artefact exists**
(tracked in Phase 6, blocked on other modules):

- Decision → Resolves → Open Question (needs Module 1)
- Decision → Addresses → Pain Point (needs Module 1)
- Decision → Supports/Implements → Strategy (needs Module 1)
- Decision → Guided by/Constrained by → Guiding Principle (needs Module 1)
- Decision → Addresses/Constrained by → Compliance (needs Module 9 integration work, though Compliance itself already exists)
- Decision → Selects/Constrains/Influences → Design (needs Module 6 — see
  [engineering-design-vs-decisions.md](engineering-design-vs-decisions.md)
  §8–9; this is the *other side* of Module 6 Phase 6's own reserved
  Design↔Decision relationship, and likely the single most commonly-used
  reserved relationship in this list once both modules exist, per that
  doc's own framing of Decision and Design as usually created together)

If Module 0 chose the polymorphic relationship model, these reserved types
cost nothing extra to declare now (just relationship-type rows with no
valid target rows yet); if per-pair join tables, these are simply deferred
table creations in Phase 6. Either way, Decision's own schema doesn't need
to change later — only the relationship layer does.

## Phase 4 — Backend API + audit logging

**Goal:** CRUD + lifecycle-transition endpoints, list/filter/search,
relationship endpoints, wired into the module registry
(`get_project_router()`), with audit events for create/approve/reject/
supersede/archive per the SOC 2 change-management policy's expectations for
a mutating, governance-relevant action.

## Phase 5 — Frontend — Decision list/detail/create/approve UI

**Goal:** project-scoped Decision list (filterable by type/status/owner),
detail page (fields, relationships, history/audit trail, comments —
reusing whatever shared components exist for comments/attachments per
Phase 0 Q6), create/edit form, and an approve/reject/supersede action flow
respecting the UX style guide's confirmation-tier and feedback-on-mutation
rules. Status/type values render through a label map from day one (per
`CLAUDE.md`'s enum-label rule), not raw enum strings.

Required alongside: Playwright e2e coverage for create → propose → approve
→ supersede, and Storybook stories for every new component, per this
project's standing testing requirements.

## Phase 6 — Reserved-relationship wiring, once Context & Strategy / Engineering Design exist

**Goal:** two independent sub-parts, each unblocked by a different module
and doable in either order relative to the other:

- Once Module 1 ships Open Question, Pain Point, Strategy, and Guiding
  Principle: wire the four Module-1-reserved relationship types from
  Phase 3 and implement the "Create Decision from Open Question" workflow
  (§9.5) — retains a link to the originating question and optionally
  copies question text, context, evidence, and relevant links into the new
  Decision draft.
- Once Module 6 ships Design: wire the Decision → Selects/Constrains/
  Influences → Design relationship from Phase 3. Given how frequently the
  design/decision doc describes these two artefacts being created together
  (§3), this is likely the first of Phase 6's reserved relationships to
  actually see real use, once Module 6 exists.

**Status:** blocked until Module 1 and/or Module 6 exist, respectively —
each sub-part unblocks independently of the other. Neither is a blocker
for Phases 1–5.

## Phase 7 — Per-decision-type approver binding

**Goal:** let an organisation restrict who may approve Decisions of a
specific Decision Type (e.g. only an "Architecture Approver" may approve
an Architecture decision), rather than today's single, flat, project-wide
`decision_approver` module role from Phase 0 addendum item 3.

**Why this is its own phase, blocked, rather than built into Phase 2 or
Phase 4:** Phase 0 addendum item 3 already considered this exact
requirement ("Decision Maker may vary by Decision," overview §13/10.5) and
deliberately built only the flat placeholder role instead, specifically
"to avoid building a bespoke policy engine here that the future Governance
module will likely replace outright." Building per-type restriction
directly into this module without a general mechanism to express "which
role can do what" would repeat exactly the mistake that decision already
avoided once. [Module 12 — Fine-Grained Access Control](module-12-fine-grained-access-control-plan.md)
(requested by the user 2026-09-21, itself partly motivated by this exact
question) is that general mechanism: an organisation-definable custom
role, composed of atomic permissions, that this phase can bind to a
specific `DecisionTypeDefinition` row.

**Scope, once Module 12 exists:** add an optional `approver_role`
reference to `DecisionTypeDefinition` (a role/permission identifier —
either a fixed role or a Module-12 custom role); when set, the approval
endpoint (Phase 4) requires the caller to hold that specific role for the
Decision's own type, instead of the flat `decision_approver` role. Left
unset (the default), behaviour is unchanged — this is strictly additive,
per Module 12's own Design Principle 1. Full detail lives in Module 12's
own plan, Phase 5, rather than duplicated here.

**Status:** blocked until Module 12 exists. Not a blocker for Phases 1–6.
Superseded, not duplicated, if/when Module 8 (Governance) later ships its
own generic per-artefact-type Approval Policies (Module 8 Phase 2) — see
Module 12's Phase 5 note.

## Acceptance criteria (from overview §48, Decisions subset)

- Decisions support architecture, design, engineering and strategy use cases.
- Decision types are configurable.
- Decisions have formal lifecycle states.
- Decisions can be approved.
- Approved Decisions retain historical integrity.
- Decisions can supersede previous Decisions.
- Decisions can resolve Open Questions. *(Phase 6, deferred)*
- Decisions can record rationale, options and consequences.
