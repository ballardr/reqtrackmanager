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
