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

**Status:** Proposed. Not started. First *content* module in the overview's
recommended build order (§46 Phase 1, after Module 0), though the user has
asked for Decision Management (Module 4) to be picked up first in practice
— see that plan's "Build-order note." This module remains a soft
dependency for Decision Management's own Phase 6 (the five reserved
relationship targets and the "Create Decision from Open Question"
workflow), but nothing here blocks Module 4's own Phases 1–5.

## Status / Resume Here

0 / 6 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: scope & open questions | [ ] Not started |
| 1 | Organisation & Project Strategy | [ ] Not started |
| 2 | Pain Points | [ ] Not started |
| 3 | Guiding Principles | [ ] Not started |
| 4 | Open Questions (+ Future State, folded into Strategy per §7) | [ ] Not started |
| 5 | Cross-artefact relationships wired between all of the above (via Module 0) | [ ] Not started |
| 6 | Frontend UI for all five artefact types | [ ] Not started |
| 7 | Docs website coverage | [ ] Not started — depends on Phase 6 shipping |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase exists:** this module introduces five new artefact types
at once (Strategy, Pain Point, Future State, Guiding Principle, Open
Question). Getting their field lists and lifecycle states wrong is
expensive to unwind once real project data exists, so each gets confirmed
before Phase 1.

**Activities:**

1. **Confirm Module 0 exists and its relationship-model shape** before
   relying on it in Phase 5 — this module no longer needs to make that call
   itself (see the note at the top of this plan), only confirm it's ready.
2. **Resolve open questions** (list below).
3. **Confirm module boundaries against Requirements**: Requirement Types
   already include "Business Requirement" (overview §14/11.1 default list)
   — confirm this module doesn't duplicate or compete with that; Strategy
   and Pain Points *drive* requirements, they aren't requirements.
4. **Confirm scope, org vs. project**: Strategy explicitly supports both
   scopes (§5.2); Pain Point/Guiding Principle types are configurable
   per-project with optional org defaults (§6.2, §8.2) — confirm the
   org-scoping mechanism mirrors `RequirementLinkTypeDefinition` (org-owned,
   referenced by project) rather than inventing a new one.
5. Produce a confirmed field-level spec addendum before Phase 1.

**Exit criteria:** user sign-off on the five artefacts' field lists and
lifecycle states below, before any migration.

### Open questions for Phase 0

1. **Future State: separate artefact or Strategy sub-record?** §7 explicitly
   says it "may be represented as part of Strategy rather than as a separate
   top-level artefact initially" and that it can become first-class later
   "without changing the conceptual model." Recommend: start as fields on
   `ProjectStrategy`/`OrganisationStrategy` (current_state, desired_state,
   target_date, outcomes, success_measures, constraints, assumptions) rather
   than a sixth table — matches the overview's own stated preference and
   avoids building a lifecycle/permission model for an artefact the source
   document itself hedges on. Confirm with user.
2. **Strategy scope duplication.** Organisation Strategy and Project
   Strategy have almost identical field lists (§5.2, §5.3). One table with
   a `scope` discriminator (`organization` / `project`) and a nullable
   `organization_id`/`project_id` pair (exactly one set), or two separate
   tables? Recommend one table with a scope discriminator — matches §5.2's
   explicit ask ("the data model should support a strategy scope... without
   requiring a fundamental redesign" for future Portfolio/Programme scopes),
   which a discriminator column accommodates far more easily than a new
   table per scope every time a scope is added.
3. **Pain Point / Guiding Principle type configurability: org or project
   table?** §6.2 says "configurable on a per-project basis... the
   organisation may optionally provide default types" — this is a
   *seed-then-override* model, not a shared org vocabulary like requirement
   link types. Confirm: project-scoped `PainPointTypeDefinition` rows,
   optionally seeded by copying an org-level default set at project
   creation (copy-on-create), rather than a live org-shared reference —
   this matches the "per-project" wording exactly and lets a project rename/
   remove types without affecting siblings, unlike a shared reference table.
4. **Guiding Principle versioning.** §8.4 says "once active, principles
   should be revision-controlled rather than silently rewritten" — does this
   need a full version-history table (like `RequirementVersion`), or does
   "revision-controlled" just mean status transitions plus an audit trail
   (no separate content-versioning table, since a principle's content is a
   short statement, not a multi-field requirement)? Recommend the lighter
   option (audit trail only) unless the user specifically wants queryable
   historical wording — flag as a case where over-building a versioning
   table for a short text field is disproportionate.
5. **Open Question → Decision link timing.** §9.5's "Create Decision from
   Open Question" workflow is genuinely blocked on Module 4 existing.
   Confirm this module only needs to ship the Open Question artefact and
   *reserve* the relationship type — the actual creation workflow lives in
   Module 4's Phase 6 (already scoped there), not duplicated here.
6. **Comments/attachments/evidence reuse.** Same question as Decision
   Management Phase 0 Q6 — confirm all five artefact types reuse the
   existing generic `ReviewComment`/`CommentFile` machinery via new
   `ReviewTargetType` members, rather than five bespoke comment tables.
7. **Nav placement.** Five new artefact types is a lot of new nav-rail
   surface at once — confirm with the user/UX-style-guide whether these
   group under one "Context & Strategy" nav section (tabs, per the style
   guide's `Tabs` pattern) rather than five separate top-level entries.

## Phase 1 — Organisation & Project Strategy

**Scope** (per Phase 0 Q2's resolution; fields from §5.2–5.3):
`scope` (org/project), objective/strategic theme, current state, desired
future state (or Future State sub-fields, per Q1), rationale, expected
outcomes, constraints, measures of success, priority, time horizon, status.
Lifecycle: `Draft → Proposed → Under Review → Approved → Active →
Superseded/Retired` (§5.4) — a five/six-state lifecycle, distinct from
Requirement's four-state one; needs its own enum. Approved strategy is
revision-controlled (§5.4) — resolve the same way as Q4 for principles.

**Why:** without a first-class Strategy record, "why is this project doing
this" lives in tribal knowledge; §5.2's stated goal (
`Organisation Strategy → Project Strategy → Requirements → Implementation`)
is otherwise unachievable.

**Roles:** Strategy Owner (Manage), Strategy Approver (Approve), project
members (View + Propose) — per §5.5, plus organisation-level equivalents
for org-scoped strategy.

## Phase 2 — Pain Points

**Scope** (fields §6.3, types §6.2, lifecycle §6.4): title, description,
type (configurable per Q3), source, impact, evidence, priority, status,
owner, date identified. Lifecycle: `Submitted → Triaged → {Rejected |
Duplicate | Accepted → Addressed → Closed}` — note the branching structure,
not a linear chain; the enum/state-machine needs to represent that a
Triaged pain point can go to one of three next states.

**Why:** §6.1 — Pain Points capture the *problem*, deliberately distinct
from a requirement (the *solution*). Without this, "why does this
requirement exist" has no upstream anchor other than free text.

**Permissions:** deliberately broad creation (all project members can
submit — §6.5) — this is explicit in the overview and should not be
narrowed to a manager role, since "restricting creation to administrators
would prevent the system from capturing problems discovered by ordinary
users and operators" (§6.5's own stated reasoning).

## Phase 3 — Guiding Principles

**Scope** (fields §8.3, scope §8.2, permissions §8.4): name, principle
statement, rationale, scope (org/project), priority, status, owner,
version/revision (per Q4's resolution). Lifecycle simpler than Strategy's —
propose → approve/activate → retire, no "Under Review"/"Superseded" split
called out explicitly in §8, confirm exact states in Phase 0.

**Why:** §8.1 — principles need to outlive any single decision so future
decisions can be checked against them; §8.4 explicitly calls out that
revision control here "protects historical Decision rationale" — i.e. this
directly serves Module 4's audit trail, not just this module's own users.

## Phase 4 — Open Questions

**Scope** (fields §9.2, lifecycle §9.3): question, context, owner,
priority, status, due/review date, evidence. Lifecycle: `Open →
Investigating → Ready for Decision → Resolved/Withdrawn`.

**Why:** §9.1 — prevents unresolved issues from being "lost in meeting
notes, email or chat"; makes "what's blocking this decision" a queryable
project state rather than something only visible in a meeting note.

**Reserved, not built here:** the "Create Decision from Open Question"
workflow itself (§9.5) — owned by Module 4 Phase 6, once both sides exist.

## Phase 5 — Cross-artefact relationships wired between all of the above

**Goal:** using Module 0's relationship infrastructure, wire the relationship types
listed in §5.6, §6.6, §7, §8.5, §9.2/9.4 — Pain Point → drives → Strategy,
Pain Point → motivates → Requirement, Pain Point → raises → Open Question,
Strategy → drives → Requirement, Strategy → informs → Decision (reserved
target), Guiding Principle → guides → Decision (reserved target), Open
Question → resolved by → Decision (reserved target), plus every artefact's
relationships to Requirement (already exists).

Relationship types whose *target* doesn't exist yet (Decision) are declared
now but only become populatable once Module 4 lands (or, if built in the
other order, vice versa — the two modules' Phase 6-equivalents are mutually
completing).

**MCP tools.** Added 2026-09-21 at the user's explicit instruction, applied
across every not-yet-built module plan (**Decided by: User**), so that
narrow, read-only MCP-tool coverage isn't an afterthought once a module's
API exists — see `docs/modules.md` §6 and
[Module 4 (Decision Management)](module-04-decision-management-plan.md)'s
shipped `mcp_tools` (`backend/app/modules/decisions/module.py`) as the
precedent to follow. This module has no single dedicated "backend API"
phase the way Decision Management's later, more granular plan does — each
of Phases 1–4 stands up one artefact's own data model, RBAC, and (per this
codebase's own convention of never landing a model with no way to reach
it) its CRUD endpoints together, so the full REST surface across all five
artefact types is only actually complete once this phase's relationship
endpoints land, immediately before Phase 6's frontend consumes it. Attaching
the commitment here, at the last purely-backend phase, rather than
retroactively to Phase 1/2/3/4 individually, is a judgment call
(**Decided by: Agent**) — revisit if a future pass splits those phases'
own endpoints out explicitly. Once this phase (and the endpoints it
depends on from Phases 1–4) exists, declare narrow, **read-only-only**
`McpToolDefinition` entries for the safe list/get endpoints — candidates
made concrete by each phase's own scope text: `list_strategies`/
`get_strategy` (Phase 1), `list_pain_points`/`get_pain_point` (Phase 2),
`list_guiding_principles`/`get_guiding_principle` (Phase 3),
`list_open_questions`/`get_open_question` (Phase 4). Explicitly excluded:
anything mutating, and any endpoint that approves/activates/retires/
resolves an artefact (e.g. Strategy approval, Guiding Principle
activation/retirement, Open Question resolution) — those routes must be
marked with `openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA`
(`backend/app/modules/registry.py`) as defence-in-depth, the same
mechanism Compliance and Decision Management already use, so such a route
can never be exposed as an MCP tool even by accident.

## Phase 6 — Frontend UI

**Goal:** list/detail/create/edit/approve UI for all five artefact types,
per Phase 0 Q7's nav-placement decision, following the UX style guide's
settings-hierarchy and confirmation-tier patterns. Enum/status values
render through label maps from day one. Playwright e2e + Storybook coverage
for each new page/component, per standing testing requirements.

## Phase 7 — Docs website coverage

Added 2026-09-21 at the user's explicit instruction, applied across every
not-yet-built module plan (**Decided by: User**); the specific scope and
placement below are this session's own judgment (**Decided by: Agent**),
modelled closely on [Module 4 (Decision Management)](module-04-decision-management-plan.md)'s
Phase 6 of the same name.

**Goal:** add Context & Strategy's user-facing surface to `docs/website/`
(the published docs site, `docs/plans/docs-website-plan.md`) — what each of
the five artefact types is and when to use it, how they relate to each
other and to Requirements, and their lifecycle states — following the
site's existing structure, tone, and Mermaid-diagram conventions (per this
repo's Documentation Requirements: prefer diagrams, validate they render
before finalising).

**Why this is its own tracked phase, not folded silently into Phase 6:**
`CLAUDE.md`'s "Docs Website Maintenance" rule already requires this check
on every change with a user-facing surface, performed in the same change
rather than deferred — so in the ordinary case this would just be part of
Phase 6's own work. It's broken out explicitly here, mirroring Decision
Management's own Phase 6 reasoning, because this module's user-facing
surface is unusually broad for one phase — five artefact types (Strategy,
Pain Point, Guiding Principle, Open Question, and Future State folded into
Strategy), each with its own lifecycle, landing in the same Phase 6 UI at
once — so a dedicated, checklist-visible phase makes the docs-site update
harder to under-scope or miss amid everything else Phase 6 ships.

**Scope:**

- A new docs-site page or section (matching whatever grouping the site
  already uses for other project-scoped modules, e.g. Compliance and
  Decision Management) covering: what each of Strategy, Pain Point, Guiding
  Principle, and Open Question is and when to use it; the Organisation
  Strategy → Project Strategy → Requirements → Implementation chain (§5.2)
  as a Mermaid diagram; each artefact's own lifecycle as a validated Mermaid
  state diagram, including Pain Point's branching `Triaged → {Rejected |
  Duplicate | Accepted → Addressed → Closed}` shape and Strategy's
  `Draft → Proposed → Under Review → Approved → Active → Superseded/Retired`
  chain (Phase 1); how Future State is represented (fields on Strategy, per
  Phase 0 Q1's resolution, not a separate artefact); the cross-artefact
  relationships wired in Phase 5 (Pain Point → drives → Strategy, Strategy
  → drives → Requirement, etc.), including which targets (Decision) are
  reserved pending Module 4.
- Update the site's module/feature index or nav to include Context &
  Strategy alongside the other installed modules it already lists.
- Cross-link from the Requirements documentation to the new page wherever
  the site already documents how a Requirement's rationale traces back to
  an upstream Pain Point or Strategy, if it does.
- **Screenshots.** — **Decided by: User** (2026-09-22, made explicit across
  every not-yet-built module plan's own "Docs website coverage" phase,
  alongside [Module 4](module-04-decision-management-plan.md)'s Phase 6
  addendum of the same date). Follow `docs/plans/docs-website-plan.md`'s
  "Screenshots" standard (1440×900 viewport, captured against the seeded
  demo dataset, stored under `docs/website/static/img/screenshots/`, real
  alt text plus a one-line caption, no surrounding "what this shows/why it
  matters" prose) and its "every Concepts, Core Features, Workflows, and
  Modules page needs at least one screenshot or diagram" bar — not forced
  onto a page whose content is genuinely diagram/table-only. Candidate
  screens for this module's own page — **Decided by: Agent**: a Pain Point
  or Strategy list view, a Strategy detail page showing its lifecycle state
  and the Org → Project → Requirement chain, and the Open Question →
  Decision conversion form.

**Status:** not started — depends on Phase 6 (frontend) actually shipping;
there is no real user-facing workflow to document accurately before then,
the same reasoning Decision Management's own Phase 6 and Compliance's
docs-site page both used. Not a blocker for any other phase.

## Acceptance criteria (from overview §48, Context & Strategy subset)

- Users can record Pain Points.
- Pain Points have configurable project-specific types.
- Default Pain Point types include Market, User and Operator.
- Users can record organisation and project strategy.
- Projects can reference organisation strategy.
- Users can record Guiding Principles.
- Guiding Principles can be organisation- or project-scoped.
- Users can record Open Questions.
- Open Questions can become Decisions. *(completed jointly with Module 4 Phase 6)*
- All artefacts support appropriate typed relationships.
