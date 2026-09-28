# Module 0 — Platform Foundations — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture, and in particular the new "Module dependency
graph" section — this plan is what that graph calls "Module 0," the one
piece of infrastructure every other module in the roadmap sits on top of.

**Source:** not a module from `future-modules-2026-09-overview.md`'s own
list of ten — this plan was split out on 2026-09-16 from what was
originally Module 1 (Context & Strategy)'s own Phase 1, once it became
clear the same infrastructure is a hard prerequisite for Module 4 (Decision
Management) and every other module too, not something specific to Context
& Strategy. Pulling it out into its own module means *which* content
module gets built first no longer determines when this gets built — it
just has to come before all of them.

**Status:** 6/6 phases complete. Phases 0–3 complete (2026-09-21); Phase 4
(module sub-component enablement) and Phase 5 (project-level override of
whole-module enablement) both added and completed 2026-09-28. This was
built first in the roadmap, ahead of every numbered module, as intended —
see "Status / Resume Here" below for the full per-phase record.

**Decided by: Agent** — the decision to split this out as its own
plan/module is a structural response to the user's question ("does there
need to be a pre-module set of work done"); it does not change any of the
underlying design content, which was already drafted (originally as Module
1's Phase 1) and is simply relocated here with its dependents updated to
point at it.

## Status / Resume Here

6 / 6 phases complete (Phase 0 + Phase 1 + Phase 2 + Phase 3 + Phase 4 + Phase 5). Plan closed.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: relationship-model decision + sequence-numbering decision (the two forks below) | [x] Complete (2026-09-21) |
| 1 | Build the generic cross-artefact relationship model | [x] Complete (2026-09-21) |
| 2 | Per-project sequence-number / unique-code generation | [x] Complete (2026-09-21) |
| 3 | Migrate the compliance module's own evidence-link tables onto the new relationship model | [x] Complete (2026-09-21) |
| 4 | Module sub-component enablement (org default + project override) | [x] Complete (2026-09-28) |
| 5 | Project-level override of whole-module enablement | [x] Complete (2026-09-28) |
| — | MCP tools / Docs website coverage | N/A — see "MCP tools and docs-website coverage" note below |

**Phase 3 outcome (2026-09-21), Decided by: User (both corrections below) /
Agent (remaining implementation details)** — see `docs/decisions.md`'s
"Module 0 (Platform Foundations) Phase 3" entry for the full record:

- Migrated `ComplianceEvidenceRequirementLink`/`ComplianceEvidenceActionLink`
  into `artefact_links` (migration 0043, in `app/modules/compliance/
  migrations/`), dropping both old tables; every call site in `service.py`/
  `reports.py`/`export.py`/`project_router.py` repointed onto
  `services.relationships`, REST shapes unchanged.
- **Mid-phase user correction #1**: core files must not name "Compliance"
  in comments/docstrings, even when extending a shared vocabulary enum —
  stricter than CLAUDE.md's import-only module-boundary wording, now the
  standing rule.
- **Mid-phase user correction #2, a real design change**: `ArtefactType`
  redesigned from "modules extend this core enum directly" (Phase 1's
  original approach) to a declarative registry —
  `ModuleDefinition.artefact_types` (`app.modules.registry`) plus
  `get_all_registered_artefact_types()`, mirroring the existing `roles`/
  `scheduled_jobs` pattern. `ArtefactType` itself now holds only the two
  core values; `ArtefactLink.source_type`/`target_type` are plain
  service-layer-validated strings, not a closed enum column, since a fixed
  `enum.Enum` can't gain members at runtime.
- `artefact_links.source_type`/`target_type` widened `VARCHAR(20)` ->
  `VARCHAR(40)` to fit Compliance's longest value (37 chars).
- New `services.relationships.get_links_to_many` (bulk target lookup) for
  `reports.py`/`export.py`'s project-wide queries.
- Full compliance suite (201 tests) + Module 0's own tests + full backend
  suite (1114+ tests) all pass. `docs/solution-architecture.md`'s ER
  diagram/table inventory updated (75 -> 73 tables).

**Phase 2 outcome (2026-09-21), Decided by: Agent (implementation details) /
User (Phase 0 design)** — see `docs/decisions.md`'s "Module 0 (Platform
Foundations) Phase 2" entry for the full record:

- Built `project_sequence_counters` (model
  `app.models.sequence.ProjectSequenceCounter`: `project_id`,
  `artefact_type` (reuses `ArtefactType`), `next_seq`) and
  `app/services/sequences.py`'s `generate_unique_code(db, project,
  artefact_type, prefix)`, additive alongside the untouched
  `next_requirement_seq`/`next_action_seq` columns — no data backfill,
  since no roadmap artefact type consumes this yet.
- Concurrency-safe by reusing `services.rbac.lock_project_for_update`
  (not a new locking helper) to serialize the read-increment-write around
  the counter row, proven with a real multi-threaded test, not just a
  sequential one.
- Found and fixed an incidental, deterministic bug in Phase 1's own
  `test_artefact_links.py::test_untyped_link_partial_unique_index_rejects_duplicate`
  (a `try/except` scoped to the wrong call) while verifying — see the
  decisions-log entry.
- Full backend test suite run: 1114 passed.

**Phase 1 outcome (2026-09-21), Decided by: Agent (implementation details) /
User (Phase 0 design)** — see `docs/decisions.md`'s "Module 0 (Platform
Foundations) Phase 1" entry for the full record:

- Built `artefact_links` (model `app.models.relationship.ArtefactLink`) —
  the generic polymorphic relationship table, with a new shared
  `ArtefactType` enum (`models/enums.py`, mirroring `ReviewTargetType`'s
  precedent) and generic query helpers in the new
  `app/services/relationships.py`.
- Migrated every existing `RequirementLink` row (typed,
  requirement-to-requirement traceability) and `RequirementActionLink` row
  (untyped, action-to-requirement membership) into `artefact_links`
  (migration 0041), preserving row ids so the one live external FK
  (`change_request_versions.proposed_link_id`, from Platform review
  2026-09 Phase 8's `REMOVE_LINK` change-request kind) could be repointed
  rather than broken. Both old tables and the `RequirementLink`/
  `RequirementActionLink` model classes are gone.
- Two separate uniqueness constraints, not one, to correctly handle
  Postgres's NULL-distinctness for the untyped (action-link) case — see
  the decisions-log entry for why a single 5-column constraint would have
  under-enforced duplicate prevention.
- Repointed every call site (`routers.requirements`, `routers.
  change_requests`, `routers.orgs`, `services.project_export`, `services.
  requirement_csv`) onto the generic service, preserving every existing
  REST endpoint's request/response shape and every existing tenant-
  isolation check exactly. The compliance module needed no changes — it
  never imported either old model.
- Full backend test suite run (see decisions-log entry for the result), including a new cross-artefact-type test and a partial-unique-index duplicate-prevention test (`tests/test_artefact_links.py`).

**Phase 0 outcome (2026-09-21), Decided by: User** — see `docs/decisions.md`'s
"Module 0 (Platform Foundations) Phase 0" entry for the full record of the
discussion:

- Relationship model: **polymorphic table** (`source_type`/`source_id`/
  `target_type`/`target_id`/`link_type_id`).
- Existing `RequirementLink` rows: **migrate into the new table** (not kept
  as a separate requirement-only fast path).
- `RequirementActionLink`: **folds into the same polymorphic table** (an
  `Action` is just another `source_type`).
- Sequence numbering: **shared `ProjectSequenceCounter` table** (not a
  per-type column on `Project`). Existing `next_requirement_seq`/
  `next_action_seq` are left as-is, untouched.
- Type-list pattern (non-blocking, decided anyway per activity 4): **shared
  frontend component only** (`TypeDefinitionManager`-style), separate
  backend tables per domain.

## Why this can't just be "Module 1's problem"

Overview §2.3 requires relationships to work *without* Traceability enabled
— e.g. Pain Point → drives → Strategy, Decision → Affects → Requirement.
Almost every module in this roadmap needs to link its own new artefact type
to at least one other new artefact type (or to the existing `Requirement`)
from the moment it ships, not only once Traceability (Module 7) exists.
Checked directly against the current schema: the only relationship
infrastructure that exists today, `RequirementLink`/
`RequirementLinkTypeDefinition` (`backend/app/models/requirement.py`,
`requirement_link_type.py`), links `requirements.id` to `requirements.id`
only — neither column can point at a `Decision`, a `PainPoint`, a `Risk`,
or anything else this roadmap introduces. Every module plan in this
roadmap references this same infrastructure; building it inside any one
module's own directory would violate this project's own module-boundary
rule the moment a second module needed to import it (`CLAUDE.md`'s
"Modular Feature System Boundary" section — no core file or sibling module
may import from another module's directory). So it has to live outside
every content module, built once, before any of them.

## Phase 0 — Exploratory: Requirements Clarification & Design Validation — COMPLETE

**Status: complete (2026-09-21).** All forks below were resolved with the
user directly, including follow-up elaboration on module-removal behaviour,
query-pattern trade-offs, and concurrency implications before the final
calls were made. See `docs/decisions.md`'s "Module 0 (Platform Foundations)
Phase 0" entry for the full record. The fork write-ups below are kept as
historical context for *why*, not as open questions — do not re-litigate
them in Phase 1/2 without new information.

**Why this phase existed:** this was a real architectural fork with a
migration-cost/generality trade-off (below), not a mechanical implementation
detail — it needed explicit user sign-off before Phase 1, the same as every
other module's design-sensitive Phase 0, just with higher stakes since
every other module depends on the outcome.

**The fork**, carried over from the original "Foundational finding":

- **Generalise `RequirementLink` into a polymorphic relationship table** —
  `source_type`/`source_id`, `target_type`/`target_id`, `link_type_id`
  (reusing `RequirementLinkTypeDefinition` as-is, or extending it with an
  optional applicable-type-pair constraint so, e.g., a "Derives from" link
  type can be restricted to specific source/target type pairs if a project
  wants that). One table, one query surface, for every artefact pair this
  roadmap ever introduces. Matches "one component per pattern"; makes a
  future generic Traceability rule/matrix engine (Module 7) straightforward
  — it queries one table, filtered by type, rather than knowing about N
  separate join tables.
- **Keep dedicated per-pair join tables**, one new table per artefact-type
  pair a module introduces (the same shape `RequirementActionLink` already
  uses for Action↔Requirement). Matches existing precedent exactly; no
  migration touching the existing, heavily-used `requirement_links` table;
  smaller, more tightly-typed tables (real FK constraints per pair, not a
  loosely-typed `source_type` string column). Cost: Module 7's Traceability
  rule/matrix engine has to enumerate and query N tables instead of one,
  and every new module-pair (there could eventually be dozens: Decision↔
  Requirement, Decision↔Decision, Risk↔Requirement, Risk↔Design, Pain
  Point↔Strategy, Stakeholder↔Requirement, Stakeholder↔PainPoint...) adds
  another table plus another case Traceability/Reporting has to special-case.

**This fork also covers `RequirementAction`/`RequirementActionLink` — not
just `RequirementLink`.** Caught mid-conversation (2026-09-16) when the
user asked about a general task-assignment capability ("set a task for
someone to create a design document"): the existing `RequirementAction`
model (`backend/app/models/requirement_action.py`) already *is* that
capability — assignee, due date, outcome status, linked to what it's for
— it's just that `RequirementActionLink` is, today, a requirement-only
per-pair table, exactly like `RequirementLink` was before this fork. Left
unaddressed, Module 3 (Risk) and Module 6 (Engineering Design) were each
about to independently extend `RequirementActionLink`-equivalent linking
to their own target type in their own phases — the exact scattered-
reinvention pattern this module exists to prevent, just recurring for a
second table. If this fork resolves polymorphic, Action-to-anything falls
out for free (an Action is just another `source_type`/`target_type` in the
same table, no separate mechanism); if per-pair, `RequirementActionLink`
gets the same per-target-type-table treatment as every other pair,
decided once, here, rather than three times across Modules 0/3/6. Module
3 and Module 6's own plans have been corrected to point at this section
instead of resolving it independently — see those plans' updated notes.

**Recommendation:** the polymorphic table. The overview explicitly asks for
a relationship subsystem "extensible so future artefact types can
participate without redesigning" (§40) and for Traceability matrices
configurable across *arbitrary* artefact-type chains (§26) — both read as
assuming one generic queryable surface, and the per-pair alternative's
table count will only grow as more of these ten modules ship. The
counter-consideration is real, though: this touches `requirement_links`,
a table already in production use, and loosening its FK constraints from
"must be a requirement" to "must be *some* artefact of *some* type" trades
some referential-integrity strength for generality. This is exactly the
kind of call that belongs to the user, not to an agent's own judgement,
given the trade-off is genuine on both sides — **flagged here for explicit
decision, not assumed.**

## The second fork: per-project sequence-number / unique-code generation

Found 2026-09-16 during an explicit audit of the whole roadmap for this
exact class of problem ("what else is being done similarly in multiple
modules"), the same way `RequirementActionLink`'s generalisation was
found. Checked directly against the code: `Requirement.unique_code`
(`SW-PERF-014`) and `RequirementAction.unique_code` (`ACT-003`) are each
generated by an almost identical pair — a dedicated counter column on
`Project` (`next_requirement_seq`, `next_action_seq`,
`backend/app/models/project.py`) plus a near-duplicate
`generate_unique_code`/`_next_sequence` function in that artefact's own
service module (`services/requirements.py`, `services/actions.py`, the
latter's own docstring says outright it "mirrors `services.requirements`'s
`generate_unique_code`/sequence-counter"). This roadmap is about to repeat
that same pair for Decision (`DEC-`), Design (`DES-`), Risk, Pain Point,
Strategy, Guiding Principle, Open Question, and Stakeholder/Persona — eight
more near-identical column-plus-function pairs bolted onto `Project`, all
doing the same thing.

**The fork**, same shape as the relationship-model one:

- **Generalise into one mechanism** — a `ProjectSequenceCounter` table
  (`project_id`, `artefact_type`, `next_seq`) plus one shared
  `generate_unique_code(db, project, artefact_type, prefix)` helper,
  replacing the per-type-column-on-`Project` convention going forward
  (existing `next_requirement_seq`/`next_action_seq` can stay as-is,
  untouched, or migrate in — same "new table alongside, don't touch what's
  proven" sub-choice as the relationship-model fork). One place to look
  for "what's the next code for X in this project," no `Project` model
  growing an unbounded number of near-identical integer columns as this
  roadmap's later phases land.
- **Keep the existing convention** — each new module adds its own
  `next_<type>_seq` column to `Project` plus its own
  `generate_unique_code` function, exactly matching
  `services/requirements.py`/`services/actions.py`'s existing precedent.
  Simplest per-module change (copy an established, working pattern); no
  new table; but `Project` accumulates roughly eight more integer columns
  over the life of this roadmap, and every module's migration touches the
  same core `projects` table for the same reason.

**Recommendation:** generalise. Unlike the relationship-model fork, this
one has a much weaker case for the status quo — `next_requirement_seq`/
`next_action_seq` were reasonable when there were two artefact types with
codes; at eight-plus, a dedicated column per type is the kind of thing
that looks fine each time it's added and awkward in aggregate (`Project`
becomes a wide table of near-duplicate counters, `git blame` on it turns
into "which module added which counter"). Existing `next_requirement_seq`/
`next_action_seq` do **not** need to migrate onto the new mechanism as
part of this — leave them exactly as they are (proven, working, low
value in touching) and have every *new* artefact type from this roadmap
use the new shared counter table instead. Lower-stakes than the
relationship-model fork (no query-surface implications for Traceability/
Reporting the way that one has), but still a real "touch it once or touch
it eight times" call worth the user's explicit sign-off rather than an
agent assumption, since it's genuinely a new table either way.

**Activities:**

1. Get the user's explicit choice on the fork above; record it here and in
   `docs/decisions.md` as **Decided by: User** once chosen.
2. If polymorphic: design the exact migration path for existing
   `RequirementLink` rows (do they migrate into the new table, or does
   `RequirementLink` stay as a requirement-only fast path with the new
   table added alongside it for everything else? — the latter avoids
   touching a proven, heavily-tested table at all, at the cost of two
   relationship tables existing side by side. Worth putting to the user as
   a sub-choice, not assumed.). Decide the same question for
   `RequirementActionLink` at the same time, per the note above — whether
   it folds into the same polymorphic table as `RequirementLink` (one
   generic relationship surface for everything, including task
   assignment) or stays its own dedicated table family, generalised the
   same per-pair way.
3. Confirm scope boundary: this module builds the relationship *storage and
   query* layer only — relationship *types* specific to a domain (e.g.
   "Derives from," "Drives," "Resolves") are seeded by whichever content
   module first needs them, not pre-populated here speculatively. Task/
   action assignment to a new artefact type (e.g. "assign someone to
   produce a Design") is *not* a new capability to design — it's
   `RequirementAction` pointed at a new target type via whichever shape
   this fork resolves to; no new fields, workflow, or lifecycle beyond
   what `RequirementAction` already has.
4. Confirm whether the recurring "configurable type list" pattern (Pain
   Point Type, Decision Type, Risk Type, Requirement Type, Stakeholder/
   Persona Type, Design Type — six near-identical asks across six different
   modules) is worth a shared pattern too. This is explicitly **not** part
   of the hard blocking path the way the relationship model is — see
   "Related, non-blocking" below — but Phase 0 should still decide, once,
   whether each module builds its own definition table following a copied
   convention (simplest, most consistent with existing precedent like
   `RequirementLinkTypeDefinition`/`ActionTypeDefinition`) or whether a
   shared backend mixin/base class and a shared frontend admin component
   (`TypeDefinitionManager`-style — list/add/rename/reorder/enable-disable)
   are built once and reused six times. Recommend the shared *frontend
   component* (concrete UI reuse benefit, low risk — this is exactly what
   the UX style guide's "one component per pattern" rule already asks for)
   but *separate backend tables per domain* (keeps FK integrity simple,
   avoids a generic polymorphic types table on top of an already-polymorphic
   relationships table) — but this is a smaller, lower-stakes call than the
   relationship-model fork and can be decided later without blocking
   anything, unlike that fork.
5. Get the user's explicit choice on the sequence-numbering fork above;
   record it here and in `docs/decisions.md` as **Decided by: User** once
   chosen, same as activity 1.

**Exit criteria:** ~~user has chosen a side of both the relationship-model
fork and the sequence-numbering fork (and, if polymorphic, the migration
sub-choices for each) before Phase 1/2 start.~~ **Met 2026-09-21** — see
outcome recorded in "Status / Resume Here" above.

## Phase 1 — Build the generic cross-artefact relationship model

**Scope:** the polymorphic relationship table (`source_type`/`source_id`/
`target_type`/`target_id`/`link_type_id`) plus generic query helpers ("what
links to X," "what does X link to," filtered by type, with explicit
forward/reverse direction and display names per overview §40). Lands in a
neutral location outside any content module's own directory —
`backend/app/services/relationships.py` and a core `artefact_links` table —
consistent with `CLAUDE.md`'s module-boundary rule, since this is core
infrastructure every module consumes, not any one module's own feature.

Per the Phase 0 outcome, this phase also covers: (a) migrating existing
`RequirementLink` rows into the new table and repointing existing call
sites (`backend/app/services/requirements.py` and anywhere else that
queries `requirement_links` directly — confirm the full call-site list
before touching data), and (b) folding `RequirementActionLink` into the
same table (`Action` as a `source_type`). Both are in scope for this phase,
not deferred follow-ups — the Phase 0 decision was specifically to
consolidate onto one table now rather than leave two tables live.

**Why (risk/outcome):** every module plan in this roadmap (Context &
Strategy, Stakeholders & Personas, Risk Management, Decision Management,
Engineering Design, Traceability, Reporting) has a phase that says "wire
relationships using Module 0's infrastructure." Building this once, first,
generically, is what lets those modules be built in *any* order relative
to each other — including Decision Management before Context & Strategy,
which is what the user actually wants to do — without each one re-deriving
or duplicating the relationship layer, or worse, building an incompatible
one-off that a later module then has to migrate away from.

**Verification bar:** since this is shared infrastructure with no UI or
end-user-visible surface of its own, its test coverage should specifically
exercise the cross-module case (e.g. create a relationship between two
different artefact-type stub rows, or the first two real types once they
exist — likely `Decision` and `Requirement`, if Module 4 goes first per the
user's plan) rather than only a single-type-pair happy path, since the
entire point of building this module is that it generalises past one pair.

## Phase 2 — Per-project sequence-number / unique-code generation — COMPLETE

**Status: complete (2026-09-21).** See "Phase 2 outcome" in "Status / Resume
Here" above and `docs/decisions.md`'s "Module 0 (Platform Foundations)
Phase 2" entry for the full record.

**Scope:** the `ProjectSequenceCounter` table (`project_id`,
`artefact_type`, `next_seq`) plus a shared `generate_unique_code(db,
project, artefact_type, prefix)` helper. Same neutral-location reasoning
as Phase 1 (`backend/app/services/sequences.py`, not inside any content
module's own directory). Existing `next_requirement_seq`/
`next_action_seq` columns on `Project` are left untouched — this phase
only builds the mechanism *new* artefact types will use going forward.

**Why (risk/outcome):** every module plan in this roadmap that defines a
new identified artefact (Decision, Design, Risk, Pain Point, Strategy,
Guiding Principle, Open Question, Stakeholder/Persona) needs a
project-scoped, never-reused, human-readable code the same way
`Requirement`/`RequirementAction` already do. Deciding this once, here,
avoids either eight near-identical migrations each adding one column to
`Project`, or eight sessions independently guessing whether to follow that
convention or invent something else.

**Verification bar:** if generalised, test coverage should confirm
codes are never reused across artefact types sharing one project (i.e. a
`ProjectSequenceCounter` row is correctly scoped per `(project_id,
artefact_type)`, not accidentally shared across types) and that concurrent
creation of two artefacts of the same type in the same project never
produces a duplicate code (mirroring whatever concurrency guarantee
`next_requirement_seq`'s existing increment already relies on).

## Phase 3 — Migrate the compliance module's own evidence-link tables onto the new relationship model — COMPLETE

**Status: complete (2026-09-21).** See "Phase 3 outcome" in "Status /
Resume Here" above and `docs/decisions.md`'s "Module 0 (Platform
Foundations) Phase 3" entry for the full record, including two mid-phase
design corrections from the user that revised part of Phase 1's own
original `ArtefactType` design.

**Added 2026-09-21, at the user's explicit request** once Phase 1 was under
way, on discovering during Phase 1's own call-site audit that the
compliance module (`backend/app/modules/compliance/`) already independently
built exactly the per-pair-table pattern Module 0 exists to replace:
`ComplianceEvidenceRequirementLink` (Evidence↔`ProjectComplianceRequirement`)
and `ComplianceEvidenceActionLink` (Evidence↔
`ComplianceRequiredActionAssessment`), both in
`backend/app/modules/compliance/models.py`, each an untyped many-to-many
join table (`evidence_id`, the target FK, `linked_by`, `created_at` — no
`link_type_id`, unlike core's `RequirementLink`). Their own docstrings
state outright that they were "deliberately owned by this module, not
core" specifically *because* no shared relationship infrastructure existed
yet when the compliance module was built — this phase is that gap closing.

**Scope:** replace both tables with rows in the new `artefact_links` table
(`source_type='compliance_evidence'`, `target_type` one of
`'project_compliance_requirement'`/`'compliance_required_action_assessment'`,
`link_type_id` null — same untyped-link shape Phase 1 already established
for `RequirementActionLink`). Add the two new artefact-type members to the
shared type vocabulary Phase 1 introduces (mirroring `ReviewTargetType`'s
existing precedent of a shared enum in a core file that every consuming
module extends with its own members — not a module-boundary violation
since it's a value in a shared vocabulary, not an import of module-owned
code). Migrate existing `compliance_evidence_requirement_links`/
`compliance_evidence_action_links` rows into `artefact_links`, then drop
both old tables, mirroring exactly how Phase 1 retires `requirement_links`/
`requirement_action_links`. Repoint every call site in `service.py`,
`export.py`, `reports.py`, `project_router.py`, and `schemas.py` (found via
this session's audit — see grep results in the Phase 1 implementation
notes) to the shared relationship service (`services/relationships.py`)
instead of querying the module's own tables directly, preserving the
existing REST API request/response shapes exactly (this is an internal
storage change, not a compliance-module feature change).

**Why (risk/outcome):** without this, the compliance module remains the
concrete counter-example to Module 0's entire premise — new shared
infrastructure that an existing module doesn't use, sitting right next to
it. Doing this now, directly after Phase 1, means the compliance module
becomes the second real consumer of the polymorphic table (alongside core
`Requirement`/`RequirementAction`), which is itself part of Phase 1's own
verification bar ("exercise the cross-module case... rather than only a
single-type-pair happy path") — this phase gives that verification a real,
already-shipped second module to test against, not just a stub.

**Verification bar:** full compliance module test suite passes unchanged
(same external behaviour, different internal storage); a new test confirms
`artefact_links` correctly returns compliance evidence links alongside
core requirement/action links when queried generically (i.e. Module 0's
"what links to X" helper works across a content-module boundary, not just
within core). `backend/scripts/seed_demo_data.py`/`seed_e2e_dataset.py`
checked for any direct references to the old table/model names.

## Phase 4 — Module sub-component enablement (org default + project override)

**Added 2026-09-28, at the user's explicit request**, made while Module 1
(Context & Strategy)'s own Phase 1 was mid-implementation: the user asked
whether a project admin could enable/disable individual sub-components of
a module (e.g. keep Pain Points but turn off Strategy and Future State)
rather than only the whole module at once. No such mechanism exists today
— `is_module_enabled` (this plan's own Phase 1/module-system-Phase-1
infrastructure) is whole-module, org-scoped only; there is no project-level
override table for module enablement at all yet, whole-module or
otherwise. Landed here, in Module 0, rather than as a Context & Strategy
phase, because — per `CLAUDE.md`'s Modular Feature System Boundary rule —
a generic capability every module may want (Governance's policy types,
Decision Management's own artefact surface, etc.) must be built as a
reusable core extension point, never hand-built once inside the one module
that happened to ask for it first.

**Scope decisions, all Decided by: User (asked directly, 2026-09-28):**

1. **Granularity:** independently toggleable per sub-component (for
   Context & Strategy: Strategy, Future State, Pain Point, Guiding
   Principle, Open Question each on/off individually), not coarser
   groupings.
2. **Control scope — two-tier:** the organisation can set a **default**
   enabled/disabled state per sub-component (an org-wide policy lever,
   parallel to how `OrganizationModuleEntitlement` sits above
   `OrganizationModuleEnablement` for whole modules), and a **project
   admin** can further override that default for their own project only.
   This is a new capability at the project level — today, whole-module
   enablement itself has no project-level override at all, only this
   finer-grained sub-component layer gets one. A project admin's own
   choice always wins over the org default when both exist.
3. **Disable semantics:** fully hidden, identical to how a disabled whole
   module already behaves — 404, not 403, "indistinguishable from not
   existing" (same rationale as `require_project_module_enabled`'s own
   docstring). No new "read-only" state; existing rows under a disabled
   sub-component simply become unreachable through the API/UI while
   disabled, same as an existing row under a wholly disabled module today.
4. **Build as generic core infrastructure now,** not narrowed to Context &
   Strategy — required by this plan's own boundary rule, and this module
   (Context & Strategy) is simply the first real consumer, the same way
   Decision Management was Module 0 Phase 1's first real consumer of the
   relationship model.

**Design (Decided by: Agent, following directly from the above):**

- **Registry** (`backend/app/modules/registry.py`): a new
  `ModuleSubComponentDefinition` frozen dataclass (`key`, `name`,
  `default_enabled: bool = True`), the same shape/spirit as the existing
  `ModuleRoleDefinition`/`EntityScopeDefinition` sibling dataclasses. Add a
  `sub_components: tuple[ModuleSubComponentDefinition, ...] = ()` field to
  `ModuleDefinition`, defaulting to empty so every already-shipped module
  (Compliance, Decision Management, Fine-Grained Access Control) needs no
  change unless it later wants this too.
- **New models** (`backend/app/models/module.py`, alongside the existing
  `OrganizationModuleEntitlement`/`OrganizationModuleEnablement`):
  - `OrganizationModuleSubComponentDefault` — `organization_id` FK,
    `module_key`, `subcomponent_key`, `enabled`, `updated_by`; unique on
    `(organization_id, module_key, subcomponent_key)`. Same
    explicit-override-only shape as `OrganizationModuleEnablement`:
    absence of a row means "use the registry's own `default_enabled`."
    Org-admin-managed (`OrgRole.ORG_ADMIN`, same role that already manages
    whole-module enablement).
  - `ProjectModuleSubComponentEnablement` — `project_id` FK, `module_key`,
    `subcomponent_key`, `enabled`, `updated_by`; unique on `(project_id,
    module_key, subcomponent_key)`. Same explicit-override-only shape:
    absence of a row means "use the org default (above), or the registry
    default if the org has none either." Project-admin-managed.
- **Resolution function**, `is_module_subcomponent_enabled(db, project_id,
  module_key, subcomponent_key)`: first calls the existing
  `is_module_enabled` for the project's owning organisation — a disabled
  whole module always wins, no sub-component lookup needed if so. Then
  checks `ProjectModuleSubComponentEnablement` (project override, highest
  precedence), then `OrganizationModuleSubComponentDefault` (org default),
  then falls back to the registry's own `default_enabled`.
- **RBAC dependency** (`backend/app/services/rbac.py`):
  `require_project_subcomponent_enabled(module_key, subcomponent_key)`,
  mirroring `require_project_module_enabled`'s factory shape and 404-not-
  403 rationale exactly, calling `is_module_subcomponent_enabled` instead
  of `is_module_enabled`.
- **Endpoints:**
  - Org-level default setter: `GET`/`PUT
    /orgs/{organization_id}/modules/{module_key}/subcomponents[/{subcomponent_key}]`
    in `backend/app/routers/orgs/settings.py`, mirroring
    `list_org_modules`/`update_org_module_enablement`'s existing shape and
    audit-logging call (`log_event`) exactly, gated by `require_org_role(OrgRole.ORG_ADMIN)`.
  - Project-level override setter: new endpoints in
    `backend/app/routers/projects/module_roles.py` (already the home for
    "which module roles/nav entries are currently available on this
    project" — the natural existing location for a second
    project-scoped, module-related settings surface), gated by whatever
    this codebase's existing project-admin-equivalent role dependency is
    (check `require_project_manage`/an equivalent — do not invent a new
    role for this). Response should include the *effective* state, the org
    default, and whether a project-level override exists, so the frontend
    can render the UX style guide's "platform-default override visibility"
    pattern (a project admin should see "using org default: disabled" vs.
    "overridden to: enabled" distinctly, not just a flat toggle) —
    Principle already named directly in `docs/ux-style-guide.md`, this is
    a textbook case for it.
- **Frontend: deferred, not built in this phase (Decided by: Agent,
  2026-09-28, when this phase's implementation was scoped).** Context &
  Strategy — the only real consumer this phase has — has no artefact UI of
  its own yet (that's its own Phase 7); a project admin toggling "Pain
  Points on/off" with no Pain Points page to show for it is exactly the
  half-finished-implementation shape `CLAUDE.md` warns against, and
  building a new project-admin settings surface speculatively ahead of any
  feature that needs it is premature. Build this phase as **backend-only**
  (registry, models, migration, resolution function, RBAC dependency,
  endpoints, tests) plus wiring Strategy's own `sub_components` entry and
  switching its endpoints onto the new dependency. The org admin page's
  existing whole-module toggle UI and any new project-admin settings
  surface both get their frontend once Context & Strategy's own Phase 7
  lands and there's a real artefact list to gate — extend the existing
  shared toggle component then rather than building one now with nothing
  to demonstrate it against.

**Not in scope for this phase:** wiring any specific module's own
sub-components into `sub_components=` — that's each consuming module's own
job, done as part of building the relevant artefact type. Context &
Strategy's own Phase 1 (Strategy) should be updated to declare its
`sub_components` entry and gate its endpoints with
`require_project_subcomponent_enabled` once this phase's infrastructure
exists — coordinate so the two changes don't collide (Module 1 Phase 1's
own implementation may already be underway using only the whole-module
gate; fold this in as a follow-up on that same artefact rather than a
second, redundant enablement mechanism).

**Verification bar:** a test organisation/project pair exercises all four
resolution paths (registry default; org default overriding registry
default; project override overriding org default; whole-module-disabled
overriding everything) against a fake `ModuleDefinition` with
`sub_components` set, not a real content module, so this phase's own test
suite doesn't depend on Context & Strategy existing yet. `ruff check .`
clean; full backend pytest suite green (single invocation, per this
repo's no-concurrent-pytest rule).

**Phase 4 outcome (2026-09-28), Decided by: Agent (all judgment calls
below; every scope/design decision was already user-approved before this
implementation pass, per the "Scope decisions" list above)** — built
exactly as designed:

- `ModuleSubComponentDefinition` (`backend/app/modules/registry.py`) and
  `ModuleDefinition.sub_components` (empty-default tuple).
- `OrganizationModuleSubComponentDefault`/`ProjectModuleSubComponentEnablement`
  (`backend/app/models/module.py`), migration `0049_module_subcomponent_
  enablement.py` (`backend/alembic/versions/`, chained off `0048` — Context
  & Strategy's own Phase 1 migration, landed the same day by a different
  agent) — a core migration, not module-colocated, matching how this
  plan's own Phase 1/2 migrations are placed.
- `is_module_subcomponent_enabled`/`is_org_module_subcomponent_enabled`
  (`backend/app/modules/registry.py`) and `require_project_subcomponent_
  enabled`/`require_org_subcomponent_enabled` (`backend/app/services/
  rbac.py`).
- Org-tier `GET`/`PUT /orgs/{id}/modules/{module_key}/subcomponents[/{key}]`
  (`backend/app/routers/orgs/settings.py`) and project-tier `GET`/`PUT
  /projects/{id}/modules/{module_key}/subcomponents[/{key}]`
  (`backend/app/routers/projects/module_roles.py`, gated by `require_
  project_manage` — the same project-settings-management dependency every
  other project-settings endpoint already uses, no new role). Both `GET`s
  return the effective state alongside the org default/registry default
  and whether an override exists, per the plan's own "platform-default
  override visibility" requirement.

**The org-scoped-Strategy gating design question the task brief flagged
was resolved (Decided by: Agent, flagged prominently as instructed):**
Context & Strategy's org-scoped Strategy records have no `project_id` at
all — there is no project for `ProjectModuleSubComponentEnablement` to
hold an override against. Rather than inventing a second, parallel
override mechanism for the org-scoped half, `is_org_module_subcomponent_
enabled`/`require_org_subcomponent_enabled` simply omit the project-
override tier: the organisation's own `OrganizationModuleSubComponentDefault`
row (or, absent one, the registry default) *is* the effective value for
an org-scoped artefact, not merely a fallback beneath a higher tier that
doesn't exist for it. This reuses the exact same org-default table/
endpoint the project-scoped resolution's own tier 3 already uses — one
org-admin lever means "the default a project may override" for
project-scoped artefacts and "the actual on/off state" for org-scoped
ones, since those are the same thing from an org admin's point of view
when there is no project to override it. Recorded here and in `docs/
decisions.md`'s "Module 0 (Platform Foundations) Phase 4" entry, and in
`docs/soc2/policies/access-control-policy.md`'s Authorization section
(item 4's block), per the SOC 2 change-management requirement to record
this class of decision where the policy documents the surrounding
authorization scopes.

Context & Strategy's Strategy artefact is wired onto this mechanism as
its first real consumer: `sub_components=(ModuleSubComponentDefinition
(key="strategy", ...),)` on its `ModuleDefinition`
(`backend/app/modules/context_strategy/module.py`); `project_router.py`'s
`_require_view` switched from `require_project_module_enabled` to
`require_project_subcomponent_enabled("context_strategy", "strategy")`;
`router.py`'s `_require_view` switched from `require_org_module_enabled`
to `require_org_subcomponent_enabled("context_strategy", "strategy")`.
Both dependencies still check whole-module enablement internally first,
so this is a strict narrowing of each router's original gate, not a
parallel or weaker one.

**A real bug found and fixed during this phase's own verification, not
just a test artefact:** both new sub-component endpoints' `log_event`
calls originally built `entity_id=f"{organization_id_or_project_id}:
{module_key}:{subcomponent_key}"` — a UUID (36 chars) plus two colon-
joined keys, which overflows `audit_events.entity_id`'s `VARCHAR(64)`
column for any real module/sub-component key pair only moderately longer
than Context & Strategy's own `"context_strategy:strategy"` (already a
tight 63-of-64 fit). Caught directly by this phase's own test suite (a
deliberately-named fixture module key reproduced the overflow, not a
contrived edge case). Fixed by dropping the UUID prefix in both — the
organisation/project id is already its own dedicated `AuditEvent` column,
so `entity_id=f"{module_key}:{subcomponent_key}"` loses no real
information and stays comfortably under the limit.

**Testing:** `backend/tests/test_module_subcomponent_enablement.py` (new)
covers all four resolution paths against a fake two-sub-component module
(mirroring `test_module_registry.py`'s own `fake_module` fixture
convention) plus the org-/project-tier admin endpoints and both RBAC
dependencies' 404-not-403 behaviour. `backend/app/modules/context_strategy/
tests/test_context_strategy_api.py` gained three real end-to-end tests
against the actual Strategy endpoints: project-scoped 404 when the org
default disables `"strategy"`, a project override re-enabling it over that
org default, and the org-scoped 404 counterpart. Full backend pytest suite
run as a single invocation against the `tests/container` Docker Compose
stack (backend rebuilt/recreated first); `ruff check .` clean. See this
plan's own "Files changed" note in `docs/decisions.md` for the exact
pass count.

**Frontend:** deliberately not built this phase, per the "Frontend:
deferred" design note above — no change to `frontend/` at all.

## Phase 5 — Project-level override of whole-module enablement

**Added 2026-09-28, at the user's explicit request**, immediately after
Phase 4 shipped: today, whole-module enablement (`OrganizationModuleEnablement`)
has no project-level override at all — the org's own row is the one and
only effective value for every project in that org, full stop. The user's
framing: the org's enablement row is already, conceptually, "the org-wide
default every project gets" — this phase just gives a project the same
override lever over *that* default that Phase 4 just gave it over each
*sub-component's* default. Same shape, one level up the same stack
(registry default → org default → project override), not a new concept.

**Scope decision, Decided by: User (asked directly, 2026-09-28):** the
project override is **symmetric** — a project admin's own choice always
wins over the org default, in either direction (can enable a module the
org's own default has off, or disable one the org's default has on).
Matches the rule Phase 4 already established for sub-components, chosen
for the same consistency reason over a one-directional ("can only narrow")
alternative that was also raised and explicitly rejected.

**Design (Decided by: Agent, following directly from the above, mirroring
Phase 4's own shape exactly):**

- New model (`backend/app/models/module.py`, alongside `OrganizationModuleEnablement`):
  `ProjectModuleEnablement` — `project_id` FK, `module_key`, `enabled`,
  `updated_by`; unique on `(project_id, module_key)`. Same
  explicit-override-only shape: absence of a row means "use the org's own
  `OrganizationModuleEnablement` row, or the registry default if the org
  has none either." Project-admin-managed (`require_project_manage`, same
  dependency Phase 4's project-tier sub-component endpoints already use).
- Resolution: a new `is_module_enabled_for_project(db, project_id,
  module_key)` in `backend/app/modules/registry.py`, replacing the
  project-resolution path that today just calls the org-level
  `is_module_enabled` directly. Order: entitlement check first (unchanged,
  still an absolute ceiling no override tier can cross — an org not
  entitled to a module stays disabled for every one of its projects no
  matter what any override says); then `ProjectModuleEnablement` (project
  override, highest precedence); then `OrganizationModuleEnablement` (org
  default); then the registry's own `default_enabled`.
- **Phase 4's own sub-component resolution must be repointed onto this**:
  `is_module_subcomponent_enabled`'s current first step ("calls the
  existing `is_module_enabled` for the project's owning organisation")
  needs to call the new `is_module_enabled_for_project` instead, so a
  project that has used *this* phase's override to disable a whole module
  correctly disables all of that module's sub-components too, not just
  the org-level disable case Phase 4 alone could see. This is the one
  piece of this phase that isn't purely additive — get it right, and add a
  regression test proving a project-level whole-module override correctly
  cascades to sub-component resolution (Phase 4's own tests only proved
  the *org-level* disable case cascades; that's not the same code path
  once this phase's project-override tier exists ahead of it).
- RBAC: `require_project_module_enabled`/`require_project_module_enabled_dynamic`
  (`backend/app/services/rbac.py`) switch from resolving the project's
  `organization_id` and calling `is_module_enabled` directly, to calling
  the new `is_module_enabled_for_project` — same 404-not-403 behaviour,
  same call sites, no router changes needed anywhere else in the app
  purely from this switch (every existing module-gated endpoint keeps
  working unchanged; only the resolution *depth* changes, and every
  existing project keeps its current effective state on migration day —
  correct by construction, since day one has zero `ProjectModuleEnablement`
  rows and the fallback is exactly today's org-only behaviour).
- Endpoints: `GET`/`PUT /projects/{project_id}/modules/{module_key}` in
  `backend/app/routers/projects/module_roles.py`, alongside Phase 4's own
  sub-component endpoints in the same file — same effective-state/org-
  default/override-exists response shape, same "platform-default override
  visibility" UX principle.
- **Org-scoped artefacts** (e.g. Context & Strategy's own org-scoped
  Strategy rows) have no project to hold this override against, the exact
  same situation Phase 4 already resolved for org-scoped sub-component
  gating: `require_org_module_enabled` is untouched by this phase and
  remains the sole gate for org-scoped endpoints — this phase only adds a
  *project*-level tier, it doesn't change what already governs an
  org-scoped artefact.
- **Frontend:** deferred, same reasoning as Phase 4 — no consuming feature
  exists yet to gate. Pick up together with Phase 4's own deferred
  frontend once Context & Strategy's Phase 7 (or any other module's
  frontend) actually ships.

**Verification bar:** same four-path test shape as Phase 4
(registry/org/project/entitlement precedence) plus the cascade regression
test named above; full backend pytest suite green (single invocation);
`ruff check .` clean.

**Phase 5 outcome (2026-09-28), Decided by: Agent (all judgment calls
below; the symmetric-override scope decision itself was already user-
approved before this implementation pass)** — built exactly as designed,
plus one class of gap found during implementation and fixed in the same
pass rather than deferred:

- `ProjectModuleEnablement` (`backend/app/models/module.py`), migration
  `0050_project_module_enablement.py` (`backend/alembic/versions/`,
  chained off `0049` — Phase 4's own migration), `is_module_enabled_for_
  project` (`backend/app/modules/registry.py`), `GET`/`PUT /projects/{id}/
  modules/{module_key}` (`backend/app/routers/projects/module_roles.py`,
  gated by `require_project_manage`), all exactly as specced.
- `is_module_subcomponent_enabled`'s whole-module check repointed onto
  `is_module_enabled_for_project` (was: the org-only `is_module_enabled`)
  — the one specifically-flagged non-additive change, with its own
  regression test (`test_project_level_whole_module_override_cascades_to_
  subcomponent_resolution`, `backend/tests/test_project_module_
  enablement.py`).
- `require_project_module_enabled`/`require_project_module_enabled_dynamic`
  switched onto `is_module_enabled_for_project`, per spec.

**Found during implementation, fixed in the same pass (not deferred,
per this repo's fix-don't-defer rule) — three more project-scoped call
sites that resolved `organization_id` from `project_id` and then checked
the org-only `is_module_enabled` directly, the identical class of gap this
phase's own brief already flagged for `is_module_subcomponent_enabled`,
just not enumerated exhaustively there:**

1. `list_project_enabled_modules` (`backend/app/routers/projects/
   module_roles.py`) — the project nav-rail listing endpoint. Left
   unfixed, a project that used this phase's own override to disable a
   module would still show its nav entry (a dead link, 404 on click), and
   a project that enabled a module its organisation's default has off
   would never see the nav entry appear at all. Repointed onto
   `is_module_enabled_for_project`.
2. `require_module_role`'s project-scoped branch (`backend/app/services/
   rbac.py`) — gates every project-scoped module-contributed role
   (Compliance's `compliance_officer`, Decision Management's
   `decision_owner`, Context & Strategy's `strategy_owner`/`strategy_
   approver`). Left unfixed, a project-level whole-module override would
   correctly 404 `require_project_module_enabled`-gated endpoints but
   silently *not* 404 `require_module_role`-gated ones for the same
   module — an authorization-surface inconsistency, not just a display
   one. Repointed onto `is_module_enabled_for_project`; regression test
   `test_require_module_role_project_scope_respects_phase5_project_
   override` added to `backend/tests/test_module_contributed_roles.py`
   (both override directions: project disables over an enabled org
   default, and project enables over a disabled org default).
3. `_module_role_permission_grants` (inside `get_effective_permissions`,
   `backend/app/services/rbac.py`) — whether a module-contributed role's
   optional `permissions` field (Fine-Grained Access Control) contributes
   to a caller's effective permission set. Same class of gap, same fix
   (branches on `is_module_enabled_for_project` when `project_id` is
   given, keeps the org-only `is_module_enabled` when it isn't); regression
   test `test_module_role_permissions_field_absent_when_project_level_
   override_disables` added to `backend/tests/test_effective_permissions.py`.

Searched exhaustively for every other `is_module_enabled(` call site in
`backend/app` resolving its `organization_id` from a `project_id` first
(`require_project_role`/`require_project_view`, `require_project_
subcomponent_enabled`, `require_permission`'s own scope-resolution branch)
— none of the rest needed a change: the first two check core project
roles, not module enablement, at all; `require_project_subcomponent_
enabled` already resolves via `is_module_subcomponent_enabled`, itself
fixed by this phase; `require_permission` has no direct `is_module_
enabled` call of its own, relying entirely on `get_effective_permissions`
(fixed above).

**A fourth bug, the same class Phase 4's own two sub-component endpoints
already hit and fixed:** this phase's new project-level whole-module
`log_event` call originally built `entity_id=f"{project_id}:{module_key}"`
— same `AuditEvent.entity_id` `VARCHAR(64)` overflow risk one tier up.
Fixed the same way, dropping the UUID prefix (`entity_id=module_key`
alone; `project_id` is already its own dedicated column).

**A fifth, more severe bug found during this phase's own verification —
a real routing collision, not a resolution-logic gap:** the new `GET`/
`PUT /projects/{project_id}/modules/{module_key}` endpoints, as originally
built, were mounted on the core `routers.projects` router — included into
the app in `main.py` **before** the mount loop that adds each registered
module's own `get_project_router()`. Since `{module_key}` is an ordinary
path parameter, it matches *any* literal segment at that position,
including a real module's own key. Decision Management's project router
(`app.modules.decisions.project_router.core`) declares a bare `GET ""`/
`POST ""` at its own literal base path,
`/api/v1/projects/{project_id}/modules/decisions` — so
`GET /api/v1/projects/{project_id}/modules/decisions` matched *this
phase's* new generic endpoint first (registered earlier), silently
returning a `ProjectModuleEnablementOut` body instead of the expected
list of decisions. Caught by the full pytest suite itself: `app/modules/
decisions/tests/test_decisions_api.py::
test_create_get_list_update_and_lock_after_approval` started failing with
`TypeError: string indices must be integers, not 'str'` (iterating a dict
response body as if it were a list) the moment this phase's endpoints
were added — a real, would-have-shipped regression against an existing,
already-working module, not a hypothetical.

Fixed by adding a distinguishing path segment, `/enablement`, mirroring
Phase 4's own `/subcomponents` convention one field over
(`GET`/`PUT /projects/{project_id}/modules/{module_key}/enablement`) —
structurally impossible for a module's own bare-base route to collide
with, current or future, since no module route in this codebase uses an
`/enablement` (or `/subcomponents`) literal segment of its own (checked
directly, not assumed). Verified two ways: (1) a heuristic route-table
scan of every registered `app.routes` entry, grouping by method and
segment count and flagging any pair differing only in wildcard-vs-literal
position, confirmed no other pair actually risks a real-world collision
(the remaining flagged pairs are either pre-existing, already-correctly-
ordered literal-before-wildcard pairs, like `orgs/creation-choices` before
`orgs/{organization_id}`, or theoretically flagged pairs that can only
collide if a UUID-typed path parameter like `decision_id` happened to
literally equal a reserved suffix word, which cannot occur since real ids
are database-generated UUIDs); (2) a new regression test,
`test_project_module_enablement_endpoint_does_not_shadow_a_modules_own_
bare_project_router_route` (`backend/tests/test_project_module_
enablement.py`), exercises the **real, `main.py`-registered** `decisions`
module (not a fake fixture module, since the bug is specifically about
whole-app route registration order, which a fixture module appended to
`INSTALLED_MODULES` at test time doesn't reproduce the same way) and
asserts `GET /api/v1/projects/{project_id}/modules/decisions` still
returns a real (empty) list of decisions, not this phase's own response
shape.

**Testing:** `backend/tests/test_project_module_enablement.py` (new)
covers `is_module_enabled_for_project`'s four resolution paths against a
fake module, the cascade regression, `require_project_module_enabled`/
`require_project_module_enabled_dynamic`'s 404/pass behaviour under a
project override in both directions, and the project-tier whole-module
endpoints. Full backend pytest suite run as a single invocation against
the `tests/container` Docker Compose stack (backend rebuilt/recreated
first); `ruff check .` clean. See this plan's own "Files changed" note in
`docs/decisions.md` for the exact pass count.

**Frontend:** deliberately not built this phase, same reasoning as Phase
4 — no change to `frontend/` at all.

**Addendum (Decided by: Agent — the coordinating/reviewing session, not
the implementing one):** while independently re-verifying this phase, the
coordinating session found and fixed one more issue, narrower than the
four above and not a design/implementation gap in the shipped code
itself: `backend/tests/test_project_module_enablement.py`'s own
`FAKE_MODULE_KEY` fixture (`"fake_project_enablement_test_module"`, 36
characters) combined with a 36-character UUID in the *pre-existing*
`update_org_module_enablement`'s audit-log call
(`entity_id=f"{organization_id}:{module_key}"`, `backend/app/routers/orgs/
settings.py`, unrelated to and predating both Module 0 phases) to exceed
`audit_events.entity_id`'s `VARCHAR(64)` column, raising `psycopg2.errors.
StringDataRightTruncation` inside that one test. Fixed by shortening the
fixture to `"fake_pme_test_module"` (21 characters) rather than touching
the pre-existing endpoint — no real, currently-registered module key
(`compliance`, `decisions`, `context_strategy`, `fine_grained_access_
control`) comes anywhere near the ~27-character budget that column
actually allows once a UUID and a colon are accounted for, so this was a
test-fixture-only fix, not a product defect.

## Related, non-blocking: patterns worth a shared convention but not shared infrastructure

Found during the same 2026-09-16 audit that surfaced the sequence-numbering
fork above. None of these block a content module's own start — unlike the
two forks above, each is either already backed by existing generic
infrastructure, or cheap enough to fix locally per-module without a shared
table.

**The repeated "configurable type list" pattern.** Six modules each
independently ask for a project- or org-scoped, ordered, enable/disable-able
"type" list: Pain Point Type (Module 1), Decision Type (Module 4), Risk
Type (Module 3), Requirement Type (Module 5), Stakeholder/Persona Type
(Module 2), Design Type (Module 6). Each can build its own definition
table following the existing `RequirementLinkTypeDefinition` convention
independently, in any order — see Phase 0 activity 4 for the shared
frontend-component recommendation.

**Archive/soft-delete columns — worth a shared mixin, not new infrastructure.**
`is_archived`/`archived_at`/`archived_by` are hand-repeated (not a mixin)
on both `Requirement` and `RequirementAction` today
(`backend/app/models/base.py` only defines `UUIDPKMixin`/`TimestampMixin`,
no archive equivalent). Roughly eight more models in this roadmap want the
identical three columns (Decision, Design, Risk, Pain Point, and others
already say so explicitly in their own plans, e.g. "matching
Requirement/RequirementAction convention"). Worth adding an
`ArchivableMixin` to `models/base.py` when the first of those new models is
actually built — same DDL either way (mixins don't change the generated
columns), so this is a pure DRY win with no data-model trade-off, unlike
the two forks above. Not urgent enough to force into Module 0's own scope;
whichever module's Phase 1 is implemented first should add it, and note
having done so for the rest to reuse.

**Supersession/revision-control — already covered by Module 0's relationship
model, not a new mechanism.** Decision Management, Engineering Design,
Context & Strategy, and Requirement Set versions (Modules 4, 6, 1, 5) each
want an "approved content is immutable, a new revision supersedes the old
one" pattern. Checked whether this needs its own shared table: it doesn't
— it falls out of three things that already exist or are already planned:
a status enum value (e.g. `Superseded`), a `Supersedes` relationship (an
ordinary row in Module 0's relationship model, no special table), and
API-layer immutability enforcement (reject mutation once a record reaches
an approved/terminal status) — business logic, not shared data
infrastructure. Worth stating explicitly here so Modules 1/4/5/6 apply the
same three-part pattern consistently rather than each inventing slightly
different immutability wording.

**Invalidation — an overlay marker plus a relationship, not a new
mechanism, added 2026-09-17.** Raised directly by the user for Engineering
Design ("designs that are developed and then someone says oh that won't
work because of X") and already implicit in Risk Management's own plan
("a linked requirement/design changes in a way that may invalidate its
mitigation," Module 3 Phase 4) — the same underlying need shows up twice
independently, the exact pattern this section exists to catch. Two parts,
neither of which is new shared infrastructure:

- **Detection + notification**: when an artefact changes, notify the
  owner of anything that links to it, so a human can judge whether the
  change actually breaks what depends on it. This is just Module 0's own
  Phase 1 "what links to X" query (already in scope) plus the existing,
  already-generic `Notification` model (confirmed enum-extensible, no
  structural change needed) — no new table, and every module that wants
  this (so far: Risk Module 3, Design Module 6) should call the same
  query rather than each writing its own reverse-relationship lookup.
- **Recording the outcome, once a human has judged it**: for an artefact
  whose approved state is otherwise immutable once approved (Design
  revisions, per Module 6's supersession model above) — an
  `is_invalidated`/`invalidated_at`/`invalidated_by` overlay, the same
  shape as `Requirement.is_completed` (a marker layered on top of the
  normal status, not replacing it, and reversible the same way completion
  is), plus an ordinary `Invalidated by` relationship (Module 0's
  relationship model again) pointing at whichever specific artefact
  caused it — never just a free-text reason standing alone. For an
  artefact whose status is *already* mutable and reassessable (Risk's own
  lifecycle, which can move back to an earlier state on reassessment),
  no new overlay is needed at all — the existing status field already
  has somewhere to record the outcome; only the detection/notification
  half applies. Confirm which shape a given module needs (immutable
  content needing an overlay, vs. mutable status needing none) rather
  than assuming every module wants the full overlay pattern.

**Not in this roadmap's scope: `ChangeRequestTask`.** While checking
`ReviewComment`/`CommentFile` (confirmed already fully generic —
`target_type` enum plus `target_id`, no FK tying it to one table, so every
module's own "reuse via new `ReviewTargetType` member" note is already the
correct, minimal action, nothing to pull in here), found a third,
pre-existing task-shaped model: `ChangeRequestTask`
(`backend/app/models/change_request.py`) — assignee, due date, `is_done` —
narrower than and structurally inconsistent with `RequirementAction`
(no independent identity/code, hard-FK'd to one `ChangeRequest` only, no
many-to-many linking). This predates this roadmap entirely and reconciling
it with `RequirementAction` would be an unrelated refactor of shipped,
tested functionality — flagged for awareness, not recommended as part of
this roadmap's Module 0 work.

## MCP tools and docs-website coverage — evaluated, neither applies here

Added 2026-09-21, at the user's explicit instruction (**Decided by: User**)
to make explicit, across every not-yet-built module plan in this roadmap,
that each module should commit to (a) narrow, read-only-only MCP tools once
its backend API phase ships, and (b) docs-website coverage once its
frontend (or backend, if it has none) ships — the same pattern
[Module 4 (Decision Management)](module-04-decision-management-plan.md)'s
shipped `mcp_tools` declarations (`backend/app/modules/decisions/module.py`)
and its Phase 6 "Docs website coverage" now follow. Checked against this
module's own actual shape rather than applied by rote (**Decided by:
Agent**, the specific determination below, per `docs/modules.md` §6 and
this repo's docs-website-maintenance rule in `CLAUDE.md`):

- **MCP tools: does not apply.** Module 0 has no `ModuleDefinition` and no
  `get_router()`/`get_project_router()` of its own at all — per this plan's
  own "Why this can't just be Module 1's problem" section, it deliberately
  lands as core infrastructure (`backend/app/services/relationships.py`,
  `backend/app/services/sequences.py`), consumed by every content module's
  own service layer, precisely so no content module has to import from
  another module's directory. It is not a registered module with a REST
  surface that `docs/modules.md` §6's `McpToolDefinition`/`path_template`
  mechanism (which validates a tool's path against its *declaring* module's
  own router prefix) could attach to. There is no module-owned, safe-to-
  expose endpoint here for a tool to proxy — a "list relationships" or
  "get next sequence code" style tool would only ever make sense declared
  by the *content* module that owns the artefact being queried (Decision
  Management, and this roadmap's other nine), gated by that module's own
  key, never by Module 0's.
- **Docs-website coverage: does not apply.** Per `CLAUDE.md`'s "Docs
  Website Maintenance" section ("if no, no action is needed — do not pad
  the site with updates for purely internal/backend-only changes that have
  no user-visible surface"): Module 0 has no frontend phase, no nav entry,
  and no end-user-visible concept of its own — it is a shared relationship/
  sequence-numbering mechanism that other modules' own UIs surface (e.g. a
  Decision's "Implements" link to a Requirement, or a Decision's own
  `DEC-001` unique code), never a page or feature a user opens directly. A
  docs-website page describing `artefact_links`/`ProjectSequenceCounter`
  directly would document an implementation detail, not a product
  capability — the content-module plans that consume this infrastructure
  are where a user-facing relationship or unique-code concept actually gets
  documented (see, e.g., Module 4's own Phase 6 scope, which documents its
  Decision↔Requirement and Decision↔Decision relationships, not Module 0's
  underlying table).

**Screenshots note (2026-09-22):** the user asked for `docs/plans/
docs-website-plan.md`'s screenshot standard (1440×900 viewport, seeded
demo dataset, alt text plus a one-line caption) to be made explicit in
every not-yet-built module plan's "Docs website coverage" phase —
**Decided by: User**. This module's own determination above already
stands for screenshots too: there is no docs-website page for Module 0
(see "Docs-website coverage: does not apply" above), so there is nothing
to screenshot — **Decided by: Agent**, not a reversal of the N/A finding
above.
