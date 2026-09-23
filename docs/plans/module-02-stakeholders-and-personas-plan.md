# Module 2 — Stakeholders & Personas — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout, and note this module
consumes the relationship-model infrastructure
[Module 0](module-00-platform-foundations-plan.md) builds — it does not
re-derive it, and does not need Module 1 for that purpose.

**Source:** [future-modules-2026-09-overview.md](future-modules-2026-09-overview.md)
§10 "Module 2 — Stakeholders & Personas".

**Status:** Proposed. Not started. Second in the overview's recommended
build order (§46 Phase 2), after Context & Strategy.

## Status / Resume Here

0 / 4 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: persona-modelling decision & open questions | [ ] Not started |
| 1 | Data model: Stakeholder/Persona, types, module RBAC | [ ] Not started |
| 2 | Stakeholder Needs (as first-class records) | [ ] Not started |
| 3 | Relationships + frontend UI | [ ] Not started |
| 4 | Docs website coverage | [ ] Not started — depends on Phase 3 shipping |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase exists:** §10.1's central modelling call — "personas should
normally be modelled as a specialised stakeholder type rather than an
unrelated concept" — is stated as a preference, not a schema. Getting this
wrong means either an awkward migration later (if personas get their own
table and then need merging into stakeholders) or a confusing UI (if they
share a table with no clear visual/conceptual distinction for users). This
phase settles it before Phase 1.

**Activities:**

1. Resolve the persona-modelling question (below) with the user.
2. Resolve the remaining open questions.
3. Confirm this module's relationship types slot into whatever Module 0
   built (polymorphic table or per-pair tables) — Module 0 is a hard
   prerequisite for this module (per the index's dependency graph), so
   this should just be a confirmation, not an open design question.
4. Confirm scope: org-level stakeholders (e.g. "Regulator" as an
   organisation-wide stakeholder class reused across projects) vs.
   project-only — §10.3 lists "Project/organisation scope" as a field,
   implying both are valid, but doesn't say whether an org-level stakeholder
   is a template projects copy or a live shared record projects reference.

**Exit criteria:** user sign-off on the persona-modelling decision, field
list, and scope model before Phase 1.

### Open questions for Phase 0

1. **Persona modelling — the central question.** Three real options:
   (a) one `stakeholders` table with a `kind` enum (`stakeholder` /
   `persona`) and the same field set for both; (b) a `personas` table with
   its own fields, optionally FK'd to a representative `stakeholder`
   row it "represents" (§10.5 explicitly lists a "Represents Persona"
   relationship, which only makes sense if these are distinct records);
   (c) personas as a `stakeholder_type` value like any other (Customer, End
   User, etc.) with no structural distinction at all. Recommend (a): a
   `kind` discriminator on one table, because §10.2's persona examples
   (Field Technician, Safety Officer) read like specific *named* entries a
   project creates, structurally identical to a specific named stakeholder
   ("Acme Corp Regulator Liaison") — they differ in what they represent
   (a real party vs. a representative behavioural archetype), not in what
   fields they need. This also makes the §10.5 "Represents Persona"
   relationship straightforward (stakeholder-kind row → represents →
   persona-kind row, same table, same relationship infra). Flag as
   **recommendation only** — needs explicit user sign-off given the
   modelling consequences.
2. **Stakeholder/Persona type configurability.** §10.2 says types "should be
   configurable per organisation/project, with useful defaults" — same
   copy-on-create-from-org-defaults pattern as Pain Point types (Module 1
   Phase 0 Q3)? Recommend reusing that exact pattern rather than a third
   variant of "configurable type list."
3. **Stakeholder Need: always a separate record, or optional?** §10.4 says
   needs "should be first-class records where the project requires a
   distinction between the stakeholder's need and the formal requirement" —
   the "where the project requires" phrasing suggests this could be
   optional/skippable for simple projects (consistent with §2.1 "lightweight
   by default"). Confirm: can a Requirement link directly to a Stakeholder
   without an intervening Need record, or is Need mandatory in the chain
   Stakeholder → Need → Stakeholder Requirement → Project Requirement?
   Recommend optional — a direct Stakeholder → Requirement relationship
   should remain valid for simple projects, with the Need record available
   but not forced, matching the module's own "independently of formal
   Traceability" framing (§10.5's closing line).
4. **Comments/attachments reuse.** Same pattern question as other modules —
   confirm reuse of `ReviewComment`/`CommentFile` via a new `ReviewTargetType`
   member rather than a bespoke table.

## Phase 1 — Data model: Stakeholder/Persona, types, module RBAC

**Scope** (fields §10.3, types §10.2, per Phase 0's resolution):
identifier, name, `kind` (stakeholder/persona, if Q1 resolves that way),
type (FK to configurable type definition), description, role,
organisation/group, interests, responsibilities, goals and needs
(free-text summary — distinct from the first-class Need records in Phase
2), priorities, constraints, relevant workflows/use scenarios, contact/
reference info, project/organisation scope, owner, status, revision/history.

**Why:** §10.1 — without an explicit stakeholder/persona record, "stakeholder
needs" and "requirement rationale" have no anchor other than the
requirement's own free text, which is exactly the gap this module exists
to close (the same rationale as Pain Points, one layer earlier in the
chain: Stakeholder/Persona → Need → Stakeholder Requirement → Project
Requirement, per §10.1's own diagram).

**Roles:** per the common permission model — View for all project members,
Propose/Manage for a stakeholder-owning role, no explicit "Approver" role
named in §10 (stakeholders aren't approved/baselined the way requirements
or decisions are) — confirm this asymmetry is intentional in Phase 0 rather
than assumed.

## Phase 2 — Stakeholder Needs (as first-class records)

**Scope** (per Phase 0 Q3's resolution; example in §10.4): a Need record
with its own text, linked to exactly one Stakeholder/Persona and
(optionally) to the Requirement(s) it gave rise to. This is the one place
in this module where the Stakeholder → Need → Requirement chain needs an
intermediate table, distinct from the general relationship-model
infrastructure — a Need isn't a general-purpose linkable artefact type in
its own right so much as a structured annotation between a stakeholder and
a requirement; confirm in Phase 0 whether it should instead just be
another relationship-model-participating artefact type (simpler, more
consistent with everything else) rather than a special case.

**Why:** §10.4's own worked example (Field Technician → "diagnose faults
quickly" → "remote diagnostic info within 30 seconds") is the concrete
case for why this can't just be a Stakeholder→Requirement relationship
with no intermediate: the *need* and the *requirement* are different
statements at different levels of precision, and losing the need's own
wording loses the original intent that justifies the requirement's exact
threshold (why 30 seconds, not 10 or 60).

## Phase 3 — Relationships + frontend UI

**Scope:** wire the relationships in §10.5 (Has Need, Experiences Pain
Point, Provides Requirement, Affected by Requirement, Consulted on
Decision, Approves/Reviews, Uses Design/System Element, Represents
Persona) using Module 0's relationship infrastructure — targets that don't
exist yet (Decision, Design) are reserved the same way Module 4 reserves
its own forward-relationships. Frontend: list/detail/create UI for
Stakeholders/Personas and Needs, per UX style guide conventions, with
Playwright e2e + Storybook coverage.

**MCP tools.** Added 2026-09-21 at the user's explicit instruction, applied
across every not-yet-built module plan (**Decided by: User**) — see
`docs/modules.md` §6 and [Module 4 (Decision Management)](module-04-decision-management-plan.md)'s
shipped `mcp_tools` (`backend/app/modules/decisions/module.py`) as the
precedent to follow. This module has no single dedicated "backend API"
phase; Phase 1 (Stakeholder/Persona) and Phase 2 (Stakeholder Need) each
stand up their own data model, RBAC, and CRUD endpoints together, so the
full REST surface across Stakeholders/Personas, Needs, and their
relationships is only complete once this phase's relationship endpoints
land, immediately before this phase's own frontend work consumes it.
Attaching the commitment here, at the last purely-backend milestone,
rather than retroactively to Phase 1/2, is a judgment call (**Decided by:
Agent**) — revisit if a future pass splits this phase's backend and
frontend halves apart, or splits Phase 1/2's own endpoints out explicitly.
Once these endpoints exist, declare `McpToolDefinition` entries for the
safe list/get endpoints — candidates made concrete by Phase 1/2's own
scope text: `list_stakeholders`/`get_stakeholder` (covering both
`kind=stakeholder` and `kind=persona` rows, per Phase 0 Q1's resolution)
and `list_stakeholder_needs`/`get_stakeholder_need`.

**2026-09-22 update (Decided by: User):** this plan originally committed to
**read-only-only** MCP tools; per the same reversal applied to the
Compliance module (`docs/decisions.md`'s "Compliance MCP write tools +
generalized AI approval gate" entry), this module should instead commit to
**write-enabled** MCP tools once built — CRUD tools for Stakeholders/
Personas and Stakeholder Needs declared normally (gated by
`MCP_WRITES_ENABLED` + the calling account's own RBAC role, no special
treatment). §10 still names no approval/baseline workflow for
Stakeholders/Personas (Phase 1's own RBAC note flags this asymmetry), so
there is no approve/decide-type action here needing either option (a) the
generalized `allow_ai_approvals` gate or (b) `APPROVAL_ACTION_ROUTE_EXTRA`
— if Phase 0 or Phase 1 later confirms some form of stakeholder sign-off
after all, decide between (a)/(b) for it then, defaulting to (a) per the
Compliance precedent absent a specific reason otherwise.

## Phase 4 — Docs website coverage

Added 2026-09-21 at the user's explicit instruction, applied across every
not-yet-built module plan (**Decided by: User**); the specific scope and
placement below are this session's own judgment (**Decided by: Agent**),
modelled closely on [Module 4 (Decision Management)](module-04-decision-management-plan.md)'s
Phase 6 of the same name.

**Goal:** add Stakeholders & Personas' user-facing surface to
`docs/website/` (the published docs site, `docs/plans/docs-website-plan.md`)
— what a Stakeholder/Persona record is, how a Persona differs from (and is
modelled alongside) an ordinary Stakeholder, what a Stakeholder Need is and
why it exists as its own record, and how these relate to Requirements and
other artefacts — following the site's existing structure, tone, and
Mermaid-diagram conventions (per this repo's Documentation Requirements:
prefer diagrams, validate they render before finalising).

**Why this is its own tracked phase, not folded silently into this phase's
own frontend work:** `CLAUDE.md`'s "Docs Website Maintenance" rule already
requires this check on every change with a user-facing surface, performed
in the same change rather than deferred — so in the ordinary case this
would just be part of Phase 3's own work. It's broken out explicitly here,
mirroring Decision Management's own Phase 6 reasoning, so the docs-site
update has its own checklist-visible exit criteria rather than being an
implicit sub-bullet of Phase 3's UI work, which already has plenty of its
own scope (two artefact types, eight relationship kinds, and a
persona-vs-stakeholder distinction that is easy to under-explain if rushed).

**Scope:**

- A new docs-site page or section (matching whatever grouping the site
  already uses for other project-scoped modules, e.g. Compliance and
  Decision Management) covering: what a Stakeholder is and how a Persona
  (per Phase 0 Q1's `kind` discriminator, if resolved that way) sits on the
  same record type rather than as an unrelated concept; the Stakeholder →
  Need → Stakeholder Requirement → Project Requirement chain (§10.1) as a
  Mermaid diagram, including why a Need is optional rather than mandatory
  in that chain (Phase 0 Q3); the relationships wired in Phase 3 (Has Need,
  Experiences Pain Point, Provides Requirement, Represents Persona, etc.),
  including which targets (Decision, Design) are reserved pending Modules 4
  and 6.
- Update the site's module/feature index or nav to include Stakeholders &
  Personas alongside the other installed modules it already lists.
- Cross-link from the Requirements documentation to the new page wherever
  the site already documents how a Requirement traces back to the
  stakeholder or need that motivated it, if it does.
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
  screens for this module's own page — **Decided by: Agent**: the
  Stakeholder/Persona list view, a Stakeholder detail page showing its
  Needs and relationships, and the Persona-vs-Stakeholder `kind` field on
  the create/edit form.

**Status:** not started — depends on Phase 3 (relationships + frontend)
actually shipping; there is no real user-facing workflow to document
accurately before then, the same reasoning Decision Management's own
Phase 6 and Compliance's docs-site page both used. Not a blocker for any
other phase.

## Acceptance criteria (from overview §48, Stakeholders & Personas subset)

- Stakeholders and Personas can be defined at appropriate organisation/
  project scope.
- Stakeholder Needs can be linked to Stakeholders/Personas and Requirements.
- Stakeholder relationships are available independently of formal
  Traceability.
- Stakeholder/Persona changes can participate in Change Impact analysis.
  *(depends on Module 10 Reporting's Engineering Change Impact report —
  this module only needs to expose enough relationship data for that
  report to consume later, not build the analysis itself.)*
