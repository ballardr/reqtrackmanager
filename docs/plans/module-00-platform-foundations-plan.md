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

**Status:** Proposed. Not started. **This should be the first thing built**
in the whole roadmap, ahead of every numbered module, including whichever
one the user picks first.

**Decided by: Agent** — the decision to split this out as its own
plan/module is a structural response to the user's question ("does there
need to be a pre-module set of work done"); it does not change any of the
underlying design content, which was already drafted (originally as Module
1's Phase 1) and is simply relocated here with its dependents updated to
point at it.

## Status / Resume Here

2 / 4 phases complete (Phase 0 + Phase 1). Phase 2 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: relationship-model decision + sequence-numbering decision (the two forks below) | [x] Complete (2026-09-21) |
| 1 | Build the generic cross-artefact relationship model | [x] Complete (2026-09-21) |
| 2 | Per-project sequence-number / unique-code generation | [ ] Not started |
| 3 | Migrate the compliance module's own evidence-link tables onto the new relationship model | [ ] Not started |

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

## Phase 2 — Per-project sequence-number / unique-code generation

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

## Phase 3 — Migrate the compliance module's own evidence-link tables onto the new relationship model

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
