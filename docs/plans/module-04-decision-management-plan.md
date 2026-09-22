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
- **Soft dependency: Module 1 (Context & Strategy)**, only for Phase 7
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

8 / 9 phases complete. Phase 7 is blocked on Module 1/Module 6; Phase 8 is
blocked on Module 12 — neither is actionable right now.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: requirements clarification | [x] Complete (2026-09-21) — see addendum below |
| 1 | Data model: Decision, Decision Type, Decision Template, lifecycle, module RBAC | [x] Complete (2026-09-21) — verified: full backend suite 1124/1124, new Storybook stories 11/11, new Playwright coverage passing, real migration run against a live DB |
| 2 | Approval, rejection, and supersession workflow | [x] Complete (2026-09-21) — see "Phase 2 notes" below |
| 3 | Relationships (to Requirements, other Decisions, and reserved future types) | [x] Complete (2026-09-21) — see "Phase 3 notes" below |
| 4 | Backend API + audit logging | [x] Complete (2026-09-21) — see "Phase 4 notes", "Phase 4 addendum (2026-09-21) — MCP tools added", and "Phase 4 addendum follow-up (2026-09-22) — approve/reject given the AI-approval gate" below |
| 5 | Frontend — Decision list/detail/create/approve UI | [x] Complete (2026-09-21) — see "Phase 5 notes" below |
| 6 | Docs website coverage | [x] Complete (2026-09-21) — see "Phase 6 notes" below |
| 7 | Reserved-relationship wiring, once Context & Strategy / Engineering Design exist | [ ] Blocked on Module 1 and/or Module 6 |
| 8 | Per-decision-type approver binding | [ ] Blocked on [Module 12](module-12-fine-grained-access-control-plan.md) (not started) — see note below |
| 9 | UX/architecture follow-up: template & type placement, nested decision types, detail page | [x] Complete (2026-09-22) — see "Phase 9 notes" below |

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
  remain reserved but deferred to Phase 7, blocked on modules that don't
  exist yet — not built here, per this plan's own Phase 3/Phase 7 split.

**Verified**: new `app/modules/decisions/tests/test_decisions_relationships.py`
(9 tests) — Implements/Affects link creation (including link-type
lazy-creation on first use), Depends-on/Conflicts-with link creation, and
the validation errors (cross-project for both relationship groups, self-link
for Decision<->Decision, duplicate link for both). `ruff check` clean. Full
backend suite run after this change (see this entry's own `docs/decisions.md`
counterpart for the final pass/fail count).

## Phase 4 notes (2026-09-21)

Builds the module's first real HTTP surface — everything from here down was
already possible to write with only what Phases 0-3 built, and needed no
new core extension point (`get_router`/`get_project_router`/`resolve_file_
owner_project_id` all already existed, added by Compliance's own Phase 7/8).

**New files**: `backend/app/modules/decisions/schemas.py` (Pydantic request/
response models), `backend/app/modules/decisions/project_router.py`
(project-scoped: Decision CRUD, lifecycle transitions, relationships,
comments, files, Decision Type management — mounted at `/api/v1/projects/
{project_id}/modules/decisions`), `backend/app/modules/decisions/router.py`
(org-scoped: Decision Template CRUD — mounted at `/api/v1/orgs/
{organization_id}/modules/decisions`). `service.py` gained one new function,
`resolve_decision_file_project_id` (this module's `resolve_file_owner_
project_id` hook), mirroring `modules.compliance.service.resolve_evidence_
file_project_id`'s exact shape for both attachment kinds (`DecisionFile`
direct, `DecisionCommentFile` via its comment).

**Scope decisions, each tagged inline in `project_router.py`'s own module
docstring too, summarised here:**

- **RBAC composition (Decided by: Agent, reading `module.py`'s own role
  docstrings literally since this is the first phase with code to attach
  them to)**: creating a Decision, proposing/submitting-for-review one's
  *own* Decision, and adding a comment only need `require_project_module_
  enabled("decisions")` — module.py's own text ("ordinary project members
  get View + Propose") settles this directly. `decision_owner` is required
  for editing an existing Decision's content, archiving, direct file
  attach/detach, relationship creation, and Decision Type management.
  `decision_approver` is required for `approve`/`reject`, per Phase 0
  addendum item 3's placeholder role. `propose`/`submit-for-review` accept
  **either** `decision_owner` **or** the Decision's own `owner_id` — a
  judgment call the task brief flagged explicitly as open, resolved this
  way so an ordinary member can move their own Decision through the
  pre-approval part of its lifecycle without needing a project-wide grant.
  Relationship-creation endpoints (supersession, Decision<->Requirement,
  Decision<->Decision) are gated on `decision_owner`, mirroring `routers.
  requirements.create_link`'s own precedent of gating traceability-link
  creation behind the same role that gates other requirement edits, not
  opening it to any viewer.
- **Reject requires a comment (Decided by: Agent)**: resolved the task
  brief's own open question by precedent — `RequirementReviewOutcome.
  FAILED` (`routers/requirements.py:755`) and Compliance's `reject_
  requirement` (`decision_note`) both make a mandatory-comment-on-rejection
  a settled convention in this codebase; `reject_decision_endpoint` 400s if
  `comment` is blank. `approve` keeps `comment` optional, per Phase 2's own
  service-layer signature.
- **Decision Type deletion (Decided by: Agent)**: unlike `Decision
  Template` (org-scoped, no persistent FK — Phase 0 addendum item 6),
  `Decision.decision_type_id` **is** a real, non-null FK, so
  `delete_decision_type` uses `services.definitions.delete_definition_
  with_reassignment` exactly like `ActionTypeDefinition`'s own delete
  endpoint — 409 naming the in-use count if `reassign_to_id` is omitted,
  bulk-reassign-then-delete if provided. `allow_empty=False`: unlike
  `ActionTypeDefinition`, Decision Types have no hierarchical-project
  fallback, so a project must always retain at least one.
- **Org-scoped Decision Template CRUD RBAC (Decided by: Agent)**: gated on
  plain `OrgRole.ORG_ADMIN`, not a new org-scoped module role. Decision
  Management's two declared roles are both `scope="project"` — there is no
  natural "org-scoped Decision Owner" the way Compliance's `compliance_
  manager` is, since a Decision itself is always project-scoped and only
  its *templates* live at the org level. Inventing a new org-scoped role
  solely to gate a small, low-traffic CRUD surface was rejected as
  premature; this can be revisited if a real need for a distinct org-scoped
  role ever appears.
- **List/filter endpoint (Decided by: Agent, scope containment)**: filters
  by `decision_type_id`/`status`/`owner_id`/`decision_maker_id`/`search`
  (title/decision_statement/unique_code) and `include_archived`, mirroring
  `routers.requirements.list_requirements`'s filtering style. No `limit`/
  `offset` pagination yet — a project's Decision set is expected to be
  small relative to its Requirement set, and nothing in this phase's scope
  asked for it; can be added later without a breaking change, the same way
  `list_requirements` added it.
- **`DecisionLinkOut` is a new, module-local schema (Decided by: Agent)** —
  checked `app.schemas`/`services.relationships` first per the task brief's
  own instruction; no generic `ArtefactLink` presentation schema exists to
  reuse, and `RequirementLinkOut` is hard-coded to a requirement-to-
  requirement shape. `DecisionLinkOut` stays polymorphic (`other_type`/
  `other_id`, with best-effort `other_display_code`/`other_display_name`
  resolution for the two target types this module currently produces:
  `"decision"` and core `"requirement"`) rather than assuming one target
  type.
- **`unarchive_decision` endpoint added (Decided by: Agent)** — not named
  in the task brief's own list, but mirrors `routers.requirements.restore_
  requirement`'s "every archive has an unarchive" convention; a one-line
  addition once `archive_decision` existed.
- **`implemented` flips to `True` (Decided by: Agent)** — this phase's own
  testing bar (full backend suite green, `ruff check` clean, comprehensive
  new endpoint coverage) is met, and a real, working API now exists, even
  without a frontend yet (Phase 5). `default_enabled` stays `False`: an
  organisation must still opt in until Phase 5 ships a UI. No MCP tools
  declared — nothing in this phase's scope calls for one, and this module's
  mutating actions (create/approve/reject/supersede) are exactly the kind
  of accountable-human governance action Compliance's own `module.py` has
  repeatedly kept off the MCP tool surface by default.
- **Seed scripts left untouched (Decided by: Agent)** — checked both
  `backend/scripts/seed_demo_data.py` and `seed_e2e_dataset.py` explicitly;
  neither mentions Decision Management. Since the module is still `default_
  enabled=False` and has no frontend yet, seeding demo/e2e Decision data
  now would populate rows nobody can see without manually enabling the
  module and calling the API directly — not worth doing until Phase 5.
  Revisit this when Phase 5 ships.
- **Docs website left untouched (Decided by: Agent)** — checked `docs/
  website/` explicitly per this repo's docs-website-maintenance rule. Phase
  4 is a pure backend API with no user-visible surface (no frontend until
  Phase 5); Compliance's own docs-website page wasn't added until its
  frontend phase either. No update warranted this phase.

**Verified**: new `app/modules/decisions/tests/test_decisions_api.py`
(41 tests) — through the real HTTP API (`client` fixture), covering: CRUD/
list/filter, the content lock (409 once `APPROVED`/`SUPERSEDED`), lifecycle
transitions (including the mandatory-comment-on-reject 400 and an illegal-
transition 409), the RBAC composition (disabled-module-is-404 vs.
wrong-role-is-403, ordinary-member-can-propose-own-decision-but-not-edit,
decision_approver gating), relationship endpoints (supersession with the
predecessor status flip, Decision<->Requirement, Decision<->Decision, each
with their own duplicate/self-link 409s), Decision Type CRUD and delete-
with-reassignment, comments/comment-files (author-only edit/attach),
direct file attachments (with the lock check), cross-project 404s, the
org-scoped Decision Template CRUD (`OrgRole.ORG_ADMIN`-gated, cross-org
isolation), and the `resolve_decision_file_project_id` hook end-to-end
through the real, unmodified `GET /api/v1/files/{id}` download endpoint.
`ruff check` clean across the whole backend. Full backend suite run once
after this change (see this entry's own `docs/decisions.md` counterpart for
the final pass/fail count) — plus a security review following the SOC 2
change-management policy's identify→verify→remediate practice (recorded in
that same `docs/decisions.md` entry).

## Phase 4 addendum (2026-09-21) — MCP tools added

**What changed:** Phase 4's own text above ("No MCP tools declared — nothing
in this phase's scope calls for one... this module's mutating actions...
are exactly the kind of accountable-human governance action Compliance's
own `module.py` has repeatedly kept off the MCP tool surface by default")
is reversed. The user explicitly asked, this session, for this module to
get MCP tools. **Decided by: User.**

**What was built — narrower than a full reversal:** seven read-only (`GET`)
tools, declared in `backend/app/modules/decisions/module.py`'s new
`mcp_tools` tuple: `list_decision_types`, `list_decisions`, `get_decision`,
`list_decision_relationships`, `list_decision_comments`, `list_decision_files`
(all project-scoped, mounted under `project_router.py`'s own prefix), and
`list_decision_templates` (org-scoped, mounted under `router.py`'s own
prefix). Zero mutating tools were added — no tool exists for create/
propose/submit-for-review/approve/reject/supersede/link/comment/attach-file.
This scope decision — read-only-only, mirroring Compliance's own precedent
exactly (see that module's Phase 6/9/11/20/22 notes in `backend/app/modules/
compliance/module.py`'s own docstring) rather than inventing a new
convention for this module — is **Decided by: Agent**, not something the
user specified beyond "add MCP tools."

**Gap fixed as part of this:** `project_router.py`'s `approve_decision_
endpoint`/`reject_decision_endpoint` had never been marked
`APPROVAL_ACTION_ROUTE_EXTRA` (`app.modules.registry`) — Phase 4 had no MCP
tools yet to need the defense-in-depth, so marking them was skipped at the
time. Both routes are now marked, mirroring Compliance's own `approve_
requirement` exactly, with a one-line docstring note on each explaining why.
This is genuinely load-bearing now: the manifest builder mechanically
excludes any tool that would resolve to a route carrying this marker,
regardless of what `module.py` declares, so this closes the one gap that
would otherwise have let a future accidental tool declaration for either
action slip through.

**Testing:** new `backend/app/modules/decisions/tests/test_decisions_mcp_
tools.py` — mirrors `backend/tests/test_module_mcp_tools.py`'s own "against
the REAL registry" integration section (the only prior precedent,
written against Compliance): proves all seven declared tools resolve
against real routes with the correct `path_template`/params/`mutates=False`,
and — the actual defense-in-depth assertion this addendum exists for —
proves the mechanical exclusion fires for this module's real `approve`
route specifically, not just by the absence of a declaration: a test
temporarily appends an `McpToolDefinition` pointing straight at the live
`POST .../{decision_id}/approve` route to the real module's own `mcp_tools`
tuple, rebuilds the registry, and confirms the manifest still excludes it,
restoring the original definition afterwards regardless of outcome.
`ruff check` clean. See `docs/decisions.md`'s "Module 4 (Decision
Management) Phase 4 addendum — MCP tools" entry for the final backend-suite
pass/fail count and the identify→verify→remediate review outcome (this
change touches the approval-exclusion mechanism, a security-adjacent
surface per the SOC 2 change-management policy).

## Phase 4 addendum follow-up (2026-09-22) — approve/reject given the AI-approval gate

**What changed:** the "Gap fixed as part of this" paragraph above — marking
`approve_decision_endpoint`/`reject_decision_endpoint` with `APPROVAL_
ACTION_ROUTE_EXTRA` so neither could ever resolve to an MCP tool — is
superseded. The same day, once Compliance's own `approve_requirement`/
`reject_requirement` were reversed from that identical hard exclusion to a
generalized, opt-in `allow_ai_approvals` gate instead ("Compliance MCP
write tools + generalized AI approval gate," `docs/decisions.md`), this
plan's own approve/reject were flagged as an architecturally identical
candidate for the same treatment, left untouched pending explicit user
sign-off. Asked directly, the user answered: **"Yes, apply the same
treatment."** **Decided by: User.**

**What was built:** `APPROVAL_ACTION_ROUTE_EXTRA` removed from both routes;
each now takes `channel: str = Depends(get_request_channel)` and calls
`require_ai_approvals_enabled(db, project)` when `channel == "mcp"`,
identical to Compliance's own inline pattern. `backend/app/modules/
decisions/service.py::_transition_status` gained a `via_mcp` param, folding
a `"via": "mcp"` marker into the logged `AuditEvent.detail`, matching
Compliance's own convention. Two new `McpToolDefinition`s — `approve_
decision`/`reject_decision` — declared in `module.py`. No longer read-only-
only: this module's MCP surface now has two gated write tools alongside its
seven read-only ones. See `docs/decisions.md`'s "Decision Management MCP
approval gate" entry for the full identify→verify→remediate review and the
exact test-suite pass count.

**Testing:** `test_decisions_mcp_tools.py` rewritten — the old "manifest
mechanically excludes approve/reject" assertion no longer holds (that's the
whole point of this change), replaced with "approve/reject resolve as real,
mutating tools with the expected params, and no *other* mutating tool
exists for this module." New `test_decisions_ai_approvals_via_mcp.py`
mirrors `test_compliance_ai_approvals_via_mcp.py`'s 7-test shape (blocked-
both-off, blocked-one-flag-on, allowed-with-`via:mcp`-marker, reject's same
sequence, UI-call-unaffected regression guard, real-RBAC-still-enforced,
propose/submit-for-review-unaffected).

## Phase 5 notes (2026-09-21)

Built `frontend/src/modules/decisions/` as a new Tier A module, following
`modules/compliance/`'s own established shape. Full account, including a
second core-boundary correction found and fixed mid-implementation (the
`ENTITY_ACCENT_COLOR` core map briefly grew per-module entries, the same
failure mode as `ProjectSequenceCounter.artefact_type`, generalised into a
new `frontend/src/modules/entityAccentColor.ts` extension point and a new
CLAUDE.md bullet), lives in `docs/decisions.md`'s "Module 4 (Decision
Management) Phase 5" entry rather than duplicated here — summarised:

- **UI shipped**: project-scoped Decision list (filterable by type/status,
  searchable, archived toggle), a "Decision Types" tab, create/edit
  `Modal` (with a Decision Template picker in create mode), a `SidePanel`
  detail view (fields, lifecycle action buttons gated on `status`,
  relationships, direct attachments, comments), and the org-scoped
  Decision Template CRUD panel (`orgOverviewSections`).
- **Scoping call (Decided by: Agent)**: no `requirementDetailSections`/
  `requirementLinkPickerTabs` contribution yet (showing/adding Decision
  links from the *Requirement* side) — the backend has no "list Decision
  links touching a given Requirement" endpoint, and building one wasn't in
  this phase's own scope text. Every relationship is still fully visible
  and creatable from the Decision's own detail panel in both directions.
  Mirrors Compliance's own identical Phase 34 scoping call.
- **Testing**: 46 new Storybook interaction tests (8 files, all passing),
  new Playwright coverage (`tests/modules/decisions/decision-lifecycle
  .spec.ts`) for this phase's own exit-criteria journey — create -> propose
  -> approve -> supersede — against a live stack, `tsc`/`eslint` clean.
  `backend/scripts/seed_demo_data.py` updated to enable the module and
  seed 3 demonstration Decisions (Phase 4's own "revisit this when Phase 5
  ships" flag on that script).

**Verified**: see `docs/decisions.md`'s own "Verified" paragraph for the
full account and final backend-suite/Playwright pass counts.

## Phase 6 notes (2026-09-21)

Built `docs/website/docs/modules/decision-management-module/` — five pages
(`overview.md`, `data-model-and-lifecycle.md`,
`relationships-and-templates.md`, `mcp-integration.md`,
`known-limitations.md`), following `compliance-module/`'s own structure,
tone, and page-per-concern split as the only prior precedent for a module's
docs-website coverage.

- **Lifecycle diagram** — a validated `stateDiagram-v2` in `overview.md`,
  drawn directly from `backend/app/modules/decisions/service.py`'s
  `_ALLOWED_TRANSITIONS` and `enums.py`'s `DecisionStatus`, not assumed from
  this plan's own prose (which only names the states, not every edge):
  Draft → Proposed → Under Review → Approved, Proposed/Under Review → 
  Rejected (terminal), Approved → Superseded (terminal, and only once the
  superseding Decision is itself Approved — see `data-model-and-lifecycle
  .md`'s own supersession section and sequence diagram).
- **Reserved relationships corrected from six, not five** — this plan's own
  Phase 3 spec (line 680 above) and `service.py`'s Phase 3 docstring both
  list *six* reserved-but-not-built relationship targets (Open Question,
  Pain Point, Strategy, Guiding Principle, **Compliance**, Design), not the
  five the original task brief for this addendum named. `relationships-and-
  templates.md` documents all six, including Compliance's own entry (
  blocked on integration work between the two modules, not on Compliance's
  own existence, which already shipped) — an inaccuracy in the brief this
  session caught and corrected rather than propagated into the published
  docs, per this repo's own validation-of-assumptions rule.
- **`docs/website/docs/api-integrations/ai-assistants-mcp/overview.md`**
  updated with Decision Management's own seven-tool table, alongside
  Compliance's existing ten — this page enumerates every module's MCP
  tools in one place, so adding tools without updating it would have left
  it silently incomplete rather than just out of date in wording.
- **"Only one module exists" framing fixed everywhere found**: `modules/
  overview.md`, `modules/roadmap.md`, `modules/compliance-module/mcp-
  integration.md`, `api-integrations/ai-assistants-mcp/overview.md`, and
  `reference/glossary.md`'s "Module" entry all previously read as if
  Compliance were the only module (e.g. "the one module shipped today",
  "Compliance is the first module to use this") — all updated to name both
  modules. `modules/roadmap.md`'s table also lost its own "Decision
  Management" row, since it's shipped now, not merely proposed.
- **Cross-link added, not forced**: `core-features/requirements-management
  .md`'s existing "Traceability links" section gained one sentence pointing
  at the new Decision↔Requirement relationship, since that section already
  covers requirement-to-requirement traceability and the new Decision
  relationship is a direct, natural sibling of it. `concepts/requirements-
  versions-and-lifecycle.md` was checked but has no comparable natural
  insertion point (it's about version/identity mechanics, not
  relationships) — left unchanged rather than forcing a link in.
- **Glossary entries not added (Decided by: Agent)** — checked whether
  `reference/glossary.md` follows a per-module-concept-entry convention
  first, per this addendum's own brief. It doesn't: Compliance itself never
  added entries for "Standard", "Compliance Requirement", or "Required
  Action" despite being the established precedent module, only the generic
  "Module" entry got a one-line mention. Adding "Decision"/"Decision
  Type"/"Decision Template" entries here would have started a new
  convention Compliance's own docs never established, not followed an
  existing one — flagged explicitly rather than silently either adding or
  skipping.

**Verified**: `cd docs/website && npm run build` — clean, zero broken-link/
broken-anchor errors (`onBrokenLinks`/`onBrokenAnchors: 'throw'`), including
every new cross-link added above. All four new Mermaid diagrams (the
lifecycle `stateDiagram-v2`, the data-model `flowchart`, the supersession
`sequenceDiagram`, and the relationships `flowchart`) rendered cleanly to
SVG via `@mermaid-js/mermaid-cli` with no parse errors, dangling nodes, or
broken fences, per this repo's Mermaid-validation requirement — inspected
the rendered lifecycle SVG directly to confirm all six states and every
labelled edge appear correctly, not just that the render command exited 0.

## Phase 6 addendum (2026-09-22) — screenshots added

**Decided by: User** — the user asked explicitly for this module's
docs-website pages to carry real screenshots (this repo's own
`docs/plans/docs-website-plan.md` "Screenshots" standard already required
this — 1440×900 viewport, captured against the seeded demo dataset, stored
under `docs/website/static/img/screenshots/`, real alt text plus a
one-line caption — but Phase 6 above shipped with zero screenshots, all
four pages' visuals coming from Mermaid diagrams alone; this addendum
closes that gap). The user also asked for the same screenshot requirement
to be made explicit in the other eleven not-yet-built module plans'
docs-website-coverage phases — see the parallel changes made across
`docs/plans/module-0{0,1,2,3,5,6,7,8,9,10}-*.md`/`module-1{1,2}-*.md`
alongside this entry.

**What was captured**: the rebuilt-from-scratch dev/test stack
(`tests/container/`, rebuilt with `docker compose up -d --build backend
frontend` first, per this repo's own "containers don't bind-mount source"
rule) at the real 1440×900 viewport, against the seeded demo dataset
(`backend/scripts/seed_demo_data.py`'s "Solstice Robotics" org). One real
gap found along the way: that script's own Decision Management section
(added in Phase 5, "enabling the module, then a superseded pair on
Falcon-3") never actually ran against this developer's already-seeded
database — the script's documented idempotent-by-skip design (`if
"Solstice Robotics" already exists, exits without changes` — see the
script's own module docstring) means a database seeded before Phase 5
never picks up a section added after it, short of the documented full
`down -v` reset. Rather than reset a database that might hold other
in-progress local work, the Decision Management portion of that script
was replayed by hand — identical calls, identical demo content (same
titles/rationale text), through the real HTTP API, non-destructively
additive — producing the same three-Decision demo state (a Superseded/
Approved supersession pair plus one Draft) the script itself already
specifies. Three Decision Templates (Nygard/MADR/Y-Statement — the same
seeded-pack content `service.py`'s `DECISION_TEMPLATE_PACKS` defines) were
also added to the org for the templates screenshots, since this
particular org predates the org-creation-choices mechanism (Phase 0
addendum item 1) and had never opted into any.

Four screenshots, all 1440×900 (confirmed via `file`), added to
`docs/website/static/img/screenshots/`: `decision-list.png` (the
Decisions list, showing the Superseded/Approved/Draft mix), `decision-
detail.png` (an Approved Decision's detail view — content fields, the
Supersedes relationship, and the locked-attachments notice), `decision-
templates.png` (the org-scoped Decision Templates admin panel), and
`decision-create-template.png` (the New Decision form with "Start from a
template" set to MADR). Embedded in `overview.md` (list + both template
screenshots, mirroring `compliance-module/overview.md`'s own
image-per-concept placement) and `data-model-and-lifecycle.md` (the detail
view, placed directly under the "Content lock after approval" section it
illustrates) — `relationships-and-templates.md`, `mcp-integration.md`, and
`known-limitations.md` were left as they were (diagrams/tables only),
matching Compliance's own precedent of not forcing a screenshot onto every
single page (`compliance-module/mcp-integration.md` and `known-
limitations.md` carry neither a screenshot nor a diagram either).

**Verified**: `file` confirmed all four screenshots are exactly 1440×900;
`cd docs/website && npm run build` re-run clean after embedding (zero
broken-link/broken-image errors).

## Phase 9 notes (2026-09-22)

Five fixes from a direct user design review of Phase 5's shipped UI — see
the "Phase 9" spec section below for the full per-item rationale and
`Decided by:` tags. Summary of what changed and why, in build order:

1. **`DecisionTemplatesPanel.tsx`**: delete buttons collected in a block
   below the table → a per-row `ActionMenu` listing both "Edit" and
   "Delete" (row-click-to-edit kept as a shortcut, but no longer the only
   way to reach it). `docs/ux-style-guide.md` gained a table-row addendum
   to "Pattern: action menu" and a "never do this" callout on "Pattern:
   directory table."
2. **Decision Types**: moved from a `ProjectDecisionsPage.tsx` tab to
   `ProjectAdminPage.tsx`. Required a new generic extension point —
   `ProjectAdminSectionDef`/`projectAdminSections` on `TierAModuleDefinition`
   — since no project-admin equivalent of `orgAdminSections` existed yet;
   `ProjectAdminPage.tsx` now merges module-contributed sections into its
   `ResourceMenu` groups the same way `OrgAdminPage.tsx` already does.
   `DecisionTypesPanel.tsx` was refactored to fetch/reload its own list
   (previously handed `items`/`onReload` by `ProjectDecisionsPage`'s own
   state) since a `render({projectId})` call from the registry hands it no
   parent state.
3. **Decision detail**: `DecisionDetailPanel.tsx` (`SidePanel`) replaced by
   `DecisionDetailPage.tsx` (a real routed page, self-fetching like
   `RequirementDetailPage.tsx`) plus `DecisionQuickViewPanel.tsx` (a
   minimal read-only `SidePanel` peek opened on row click, linking to the
   page). `docs/ux-style-guide.md`'s "Pattern: entity detail panel" was
   rewritten: its old "no dedicated page exists yet" test was circular, so
   it's now a checklist of four concrete markers (comment thread, file
   attachments, a relationships section, 3+ lifecycle actions each with
   their own `ConfirmDialog`) — 2 or more means a page. Decisions trip all
   four.
4. **Decision Types nested-project fallback**: `service.
   resolve_effective_decision_types` mirrors `resolve_effective_action_
   types` exactly; wired into `list_decision_types` (effective set) and a
   new `_validate_effective_decision_type` (lets a child Decision reference
   an inherited type), while rename/move/delete stay scoped to
   literally-owned rows via the original `_get_decision_type_in_project`.
   `delete_decision_type` gained `allow_empty=project.parent_project_id is
   not None`, mirroring `action_types.py`. **Corollary found during
   implementation, not in the original request**: `_seed_new_project`
   (`module.py`) seeded every project's 5 defaults unconditionally,
   including children — a child seeded with its own would never exercise
   the new fallback, so seeding is now root-only (mirrors `routers.
   projects.create_project`'s own `seed_action_types` gate). New test file
   `test_decisions_hierarchy.py` (four tests, mirroring `test_action_types
   .py`'s own hierarchy suite) plus a new child-seeding test in
   `test_decisions_seeding.py`. This "seeding defeats the fallback" failure
   mode is now called out explicitly in CLAUDE.md's new "Nested
   (Hierarchical) Projects" section so a future module doesn't repeat it.
5. **Decision Templates**: `orgOverviewSections` → `orgAdminSections`
   (Org Dashboard → Org Management), a pure registration-key change.

**Real gap found on first pass, then actually closed**: an initial pass
left the docs-website screenshots stale and the rewritten Playwright spec
unexecuted, noting both as follow-up rather than doing them — called out
directly by the user and corrected in the same session. Rebuilt the
Docker Compose stack (`tests/container/`) against this phase's code; ran
`decision-lifecycle.spec.ts` against it (`--project=default --no-deps`,
skipping the unrelated Keycloak-dependent `global-state-mutators`
project), which caught a real test-timing race (checking page text
immediately after a client-side route change, before the old list view
unmounted — the app's own state was already correct, per the DOM snapshot
captured at the failure) — fixed by adding the same URL-based navigation
wait already used elsewhere in the spec; now passes cleanly end-to-end.
Reviewed every page under `docs/website/docs/modules/decision-management-module/`
line by line and found one more stale spot beyond what the first pass
caught: `building-your-own-module.md`'s own extension-point table was
missing `projectAdminSections` entirely. Regenerated all four
decision-management screenshots via Playwright MCP against the live app
(1440×900, demo org admin persona, Falcon-3 Inspection Drone project) —
`decision-list.png` (tab bar gone), `decision-detail.png` (the new full
page), `decision-templates.png` (Organisation Admin, per-row `ActionMenu`),
`decision-create-template.png` (recaptured for a clean background). `cd
docs/website && npm run build` re-run clean afterward.

**Verified**: full backend test suite (`backend/app/modules/decisions/
tests/`, 49 tests including the new `test_decisions_hierarchy.py`) run in
isolation per the repo's one-pytest-at-a-time rule — all passing; frontend
`npm run typecheck`/`npm run lint` clean; `decision-lifecycle.spec.ts` run
against the live rebuilt stack end-to-end — passing; docs-website build
clean after the screenshot swap.

**Files changed**: see the "Phase 9" spec section's own file list below,
plus `docs/website/docs/modules/building-your-own-module.md` and the four
regenerated screenshots under `docs/website/static/img/screenshots/`.

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
(tracked in Phase 7, blocked on other modules):

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
table creations in Phase 7. Either way, Decision's own schema doesn't need
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

## Phase 6 — Docs website coverage

**Goal:** add Decision Management's user-facing surface to `docs/website/`
(the published docs site, `docs/plans/docs-website-plan.md`) — what a
Decision is, its lifecycle/approval/supersession model, Decision Types and
Templates, and how it relates to Requirements and other Decisions —
following the site's existing structure, tone, and Mermaid-diagram
conventions (per this repo's Documentation Requirements: prefer diagrams,
validate they render before finalising).

**Why this is its own tracked phase, not folded silently into Phase 5:**
`CLAUDE.md`'s "Docs Website Maintenance" rule already requires this check
on every change with a user-facing surface, performed in the same change
rather than deferred — so in the ordinary case this would just be part of
Phase 5's own work, not a separate phase. It's broken out explicitly here
at the user's request, specifically because this module's user-facing
surface is unusually broad for one phase (lifecycle states, approval/
rejection/supersession, two relationship groups, Decision Types, and
Decision Templates all land in the same Phase 5 UI at once) — a dedicated,
checklist-visible phase makes it harder for the docs-site update to be
under-scoped or missed amid everything else Phase 5 ships, and gives it its
own explicit exit criteria rather than being an implicit sub-bullet of
Phase 5's own scope.

**Scope:**

- A new docs-site page (or section of an existing one, matching whatever
  grouping the site already uses for other project-scoped modules e.g.
  Compliance) covering: what a Decision Record is and when to use one: the
  lifecycle diagram (Draft → Proposed → Under Review → Approved, with
  Rejected and Superseded as terminal-ish states) as a validated Mermaid
  diagram; the approval model (today's flat, placeholder `decision_approver`
  project role — Phase 0 addendum item 3 — not yet the per-type binding
  Phase 8 will add); supersession semantics (§13/10.6: a new Decision links
  back to the old one, which only flips to `Superseded` once that new
  Decision is itself `Approved`); Decision Types (seeded defaults,
  project-configurable) and Decision Templates (org-scoped, opt-in at
  organisation creation, the seeded Nygard/MADR/Y-Statement ADR packs);
  the two Phase 3 relationship groups (Decision↔Requirement,
  Decision↔Decision) with a short Mermaid diagram of how a Decision sits
  relative to a Requirement and another Decision.
- Update the site's module/feature index or nav (wherever other installed
  modules like Compliance are listed) to include Decision Management.
- Cross-link from the Requirements documentation to the new Decision
  Management page wherever the site already documents Decision↔Requirement
  traceability links, if it does.

**Status:** [x] Complete (2026-09-21) — see "Phase 6 notes" near the top of
this document for what was actually built.

## Phase 7 — Reserved-relationship wiring, once Context & Strategy / Engineering Design exist

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
  (§3), this is likely the first of Phase 7's reserved relationships to
  actually see real use, once Module 6 exists.

**Status:** blocked until Module 1 and/or Module 6 exist, respectively —
each sub-part unblocks independently of the other. Neither is a blocker
for Phases 1–6.

## Phase 8 — Per-decision-type approver binding

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

**Status:** blocked until Module 12 exists. Not a blocker for Phases 1–7.
Superseded, not duplicated, if/when Module 8 (Governance) later ships its
own generic per-artefact-type Approval Policies (Module 8 Phase 2) — see
Module 12's Phase 5 note.

## Phase 9 — UX/architecture follow-up: template & type placement, nested decision types, detail page

**Decided by: User** — five fixes requested directly after a design review of Phase 5's shipped UI, not agent-initiated:

1. **`DecisionTemplatesPanel.tsx`'s delete buttons, collected in a block below the table, move into a per-row `ActionMenu`.** The list's "Edit" (previously an implicit row-click only) becomes an explicit menu item too, since a row-click shortcut is never a substitute for a menu entry — the menu must always list every action available on that row. New `docs/ux-style-guide.md` guidance (an addendum to "Pattern: action menu," and a "never do this" callout on "Pattern: directory table") generalises the fix beyond this one panel, scoped to this call site only for this phase.
2. **Decision Types move from a `ProjectDecisionsPage.tsx` tab to `ProjectAdminPage.tsx`**, alongside the project's other definition-table settings (Action Types, Custom Fields) — matching where Action Types themselves already live. `ProjectAdminPage.tsx` had no per-module contribution mechanism before this phase (unlike `OrgAdminPage.tsx`'s `orgAdminSections`); a new `projectAdminSections` field on `TierAModuleDefinition` (generic, not decisions-specific, per CLAUDE.md's Modular Feature System Boundary) is added and consumed the same way.
3. **Decision detail moves from a `SidePanel` (`DecisionDetailPanel.tsx`) to a full page (`DecisionDetailPage.tsx`)**, with a new, minimal, read-only `DecisionQuickViewPanel.tsx` (`SidePanel`) opened on row click instead — code/status/title/type/statement only, no actions, with a "View full details" link into the page. `docs/ux-style-guide.md`'s "Pattern: entity detail panel" is revised alongside this: its old "for an entity that doesn't already have its own dedicated page" test was circular (an agent could just not build a page), replaced with a checklist of four concrete "too much for a SidePanel" markers (comment thread, file attachments, a relationships section, 3+ lifecycle actions each with their own `ConfirmDialog`) — Decisions trip all four. **Decided by: Agent** for the specific quick-view-plus-page mechanism (the user explicitly left this implementation choice open); **Decided by: User** for the underlying "the SidePanel carries too much" diagnosis and the requirement that whatever replaces it not be a one-off, un-auditable judgment call.
4. **Decision Types gain the hierarchical-project fallback `ActionTypeDefinition` already has.** This directly supersedes Phase 4's own router docstring, which had explicitly flagged the fallback's absence as a **Decided by: Agent** call at the time ("unlike `ActionTypeDefinition`, Decision Types have no hierarchical-project fallback mechanism") — the user asked directly whether nested projects should work here, making the reversal **Decided by: User**. `service.resolve_effective_decision_types` mirrors `services.project_hierarchy.resolve_effective_action_types` exactly. Implementing this surfaced a needed corollary not in the original request: `_seed_new_project` (`module.py`) was seeding every new project's 5 defaults unconditionally, including children — a child seeded with its own defaults never actually exercises the fallback, so seeding is now root-only, mirroring `routers.projects.create_project`'s own `seed_action_types` gate. This gap (a fallback mechanism whose seeding path defeats it) is now called out as its own explicit check in CLAUDE.md's new "Nested (Hierarchical) Projects" section, alongside the general "does this table need the fallback" check.
5. **Decision Templates move from `orgOverviewSections` (Org Dashboard) to `orgAdminSections` (Org Management)** — a pure registration-key change (both share `OrgAdminSectionDef`'s identical shape).

**Files changed:** `frontend/src/modules/decisions/DecisionTemplatesPanel.tsx` (`ActionMenu` actions column, imports), `frontend/src/modules/decisions/DecisionTypesPanel.tsx` (self-fetching, moved off `items`/`onReload` props), `frontend/src/modules/decisions/ProjectDecisionsPage.tsx` (tab bar removed, `DecisionQuickViewPanel` replaces `DecisionDetailPanel`), `frontend/src/modules/decisions/DecisionDetailPanel.tsx` (removed), `frontend/src/modules/decisions/DecisionDetailPage.tsx` (new), `frontend/src/modules/decisions/DecisionQuickViewPanel.tsx` (new), `frontend/src/modules/decisions/module.ts` (new route, `projectAdminSections`, `orgAdminSections` rename), `frontend/src/modules/types.ts` (`ProjectAdminSectionDef`, `projectAdminSections` field), `frontend/src/pages/ProjectAdminPage.tsx` (`moduleAdminSections` computation, generic render fallback, widened `ProjectAdminGroupKey`), `backend/app/modules/decisions/service.py` (`resolve_effective_decision_types`), `backend/app/modules/decisions/project_router.py` (`list_decision_types`, `_validate_effective_decision_type`, `delete_decision_type`'s `allow_empty`), `backend/app/modules/decisions/module.py` (root-only seeding gate), `backend/app/modules/decisions/tests/test_decisions_hierarchy.py` (new), `backend/app/modules/decisions/tests/test_decisions_seeding.py` (updated docstring + new child-seeding test), Storybook stories for all touched/new components, `tests/playwright/tests/modules/decisions/decision-lifecycle.spec.ts` (updated for the page/quick-view split), `docs/ux-style-guide.md`, `docs/solution-architecture.md`, `CLAUDE.md` (new "Nested (Hierarchical) Projects" section), `docs/website/docs/modules/decision-management-module/overview.md`, `docs/website/docs/modules/building-your-own-module.md` (`projectAdminSections` row), `docs/website/static/img/screenshots/decision-list.png`/`decision-detail.png`/`decision-templates.png`/`decision-create-template.png` (regenerated), `docs/decisions.md` (this phase's entry).

## Acceptance criteria (from overview §48, Decisions subset)

- Decisions support architecture, design, engineering and strategy use cases.
- Decision types are configurable.
- Decisions have formal lifecycle states.
- Decisions can be approved.
- Approved Decisions retain historical integrity.
- Decisions can supersede previous Decisions.
- Decisions can resolve Open Questions. *(Phase 7, deferred)*
- Decisions can record rationale, options and consequences.
