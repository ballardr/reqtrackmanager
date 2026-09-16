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

0 / 6 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: requirements clarification | [ ] Not started |
| 1 | Data model: Decision, Decision Type, lifecycle, module RBAC | [ ] Not started |
| 2 | Approval, rejection, and supersession workflow | [ ] Not started |
| 3 | Relationships (to Requirements, other Decisions, and reserved future types) | [ ] Blocked on Module 0 |
| 4 | Backend API + audit logging | [ ] Not started |
| 5 | Frontend — Decision list/detail/create/approve UI | [ ] Not started |
| 6 | Reserved-relationship wiring, once Context & Strategy / Engineering Design exist | [ ] Blocked on Module 1 and/or Module 6 |

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

## Acceptance criteria (from overview §48, Decisions subset)

- Decisions support architecture, design, engineering and strategy use cases.
- Decision types are configurable.
- Decisions have formal lifecycle states.
- Decisions can be approved.
- Approved Decisions retain historical integrity.
- Decisions can supersede previous Decisions.
- Decisions can resolve Open Questions. *(Phase 6, deferred)*
- Decisions can record rationale, options and consequences.
