# Module 9 — Compliance Integration — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout. This module hard-depends
on [Module 0](module-00-platform-foundations-plan.md), in addition to
Modules 7 and 8 below.

**Source:** [future-modules-2026-09-overview.md](future-modules-2026-09-overview.md)
§37 "Module 9 — Compliance Integration".

**Status:** Proposed — but unlike every other module in this roadmap,
**the underlying module already exists and is complete**: Compliance
shipped as `docs/plans/compliance-module-plan.md`, 44/44 phases done as of
2026-09-13 (per that plan's own status and this project's memory). This
plan is scoped narrowly to the *integration* work the overview asks for
(§37) — participating in Traceability and Governance once those exist — not
a rebuild or a new Compliance plan. It is deliberately much shorter than
the other nine module plans because there is much less net-new work here.

## Why this is a separate, lightweight plan rather than an addition to compliance-module-plan.md

`compliance-module-plan.md` is a 44-phase, ~400KB resumable implementation
history for a shipped, complete module. Appending speculative future phases
to a "done" plan file risks confusing its own resume instructions (which
say 44/44 complete) and mixes a closed implementation record with an
open-ended future dependency. This plan stays a forward-looking pointer;
when Traceability/Governance actually exist and this integration work is
picked up, its phases should be appended to `compliance-module-plan.md`
directly (continuing its existing phase numbering from 44) rather than
staying in this separate file — this file exists only to hold the *plan*
for that future append, per this task's ask to plan every module now.

## Status / Resume Here

0 / 3 phases complete. **All three phases are hard-blocked**: Phase 1 needs
Module 7 (Traceability), Phase 2 needs Module 8 (Governance), Phase 3 needs
both. None of this should start before those modules exist — attempting it
earlier would mean guessing at integration points that don't exist yet.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: confirm integration points once Traceability/Governance are real | [ ] Blocked on Modules 7 & 8 |
| 1 | Compliance participates in Traceability rules | [ ] Blocked on Module 7 |
| 2 | Compliance participates in Governance baseline policies | [ ] Blocked on Module 8 |
| 3 | Compliance ↔ Decisions, Risk, Design relationships | [ ] Blocked on Modules 3, 4, 6 |
| 4 | MCP tools / docs-website coverage | N/A — see "MCP tools and docs-website coverage — determination" note below; this plan adds no new endpoint or user-facing surface of its own |

## Phase 0 — Exploratory: Confirm Integration Points

**Why this phase exists:** §37's example — "Project Requirement must link
to a Business Requirement OR applicable Compliance Requirement" — assumes
Traceability's rule engine can target "Compliance Requirement" as a
first-class artefact type. This phase re-reads the *actual*, shipped
Compliance module's data model (not the overview's assumption of it) to
confirm what a "Compliance Requirement" really is in this codebase's
implementation (its exact model name, e.g. whatever the Compliance module
calls its per-standard requirement rows) before Traceability's rule engine
is asked to reference it.

**Activities:**

1. Read the current Compliance module's models (`backend/app/modules/
   compliance/` or wherever it landed — confirm path) to identify the exact
   artefact type Traceability Module 7's rule engine needs to target.
2. Confirm whether Compliance's existing approval/evidence workflow
   (already built, per compliance-module-plan.md) should remain fully
   independent of Governance's new generic approval-policy engine (Module 8
   Phase 2), or whether Governance should eventually subsume it — same
   "generalise for new work, don't destabilise what's proven" caution as
   Module 8's own Phase 0 Q2, applied here specifically: §37's closing line
   ("Compliance approval and evidence validity remain managed by the
   Compliance module") is the overview's own explicit answer — Governance
   should *consume* Compliance's completion status as a signal, not replace
   Compliance's approval mechanism. Confirm this reading with the user
   before Phase 2, since it settles a real design question the overview
   otherwise leaves ambiguous by not spelling out "remain managed" precisely.
3. Confirm whether this integration work should be recorded as new phases
   appended to `compliance-module-plan.md` (continuing its phase count from
   44) once started, per this plan's own recommendation above.

**Exit criteria:** confirmed integration points and the Governance/
Compliance boundary, signed off by the user, before Phase 1.

## Phase 1 — Compliance participates in Traceability rules

**Scope** (§37's diagram and example): Traceability rules (Module 7) can
target "Compliance Requirement" as a valid relationship target type,
exactly like any other artefact type in that module's rule schema — no new
mechanism on the Compliance side beyond exposing itself as a linkable
target in Module 0's relationship-model infrastructure.

**Why:** §37 — "Project Requirement must link to a Business Requirement OR
applicable Compliance Requirement" only becomes possible once both
Traceability's rule engine and the relationship model can reference
Compliance rows the same way they reference any other artefact type — this
phase is almost entirely Traceability-side plumbing pointed at an existing
Compliance artefact, not new Compliance functionality.

## Phase 2 — Compliance participates in Governance baseline policies

**Scope** (§37): Governance's baseline policy (Module 8 Phase 4) can
include "Compliance complete" as one of its configurable pre-baseline
checks, alongside required fields/approvals/traceability/verification.

**Why:** §37 — "Governance may then specify: the requirement cannot be
baselined until the traceability requirement is satisfied" — extending
this to compliance completion is the natural generalisation, and is
explicitly named in the overview's Compliance Integration acceptance
criteria (§48: "Governance can require Compliance completion before
baseline").

## Phase 3 — Compliance ↔ Decisions, Risk, Design relationships

**Scope** (§37's broader integration list — Requirements, Requirement
Sets, Risk Management, Decisions, Engineering Design, Verification/
actions): wire the remaining relationship types once Modules 3, 4, and 6
exist — Risk → Related to → Compliance obligation (Module 3's own Phase 3
already reserves this), Decision → Addresses/Constrained by → Compliance
(Module 4's own Phase 3 already reserves this).

**Why:** these are relationship-model wiring only, already anticipated and
reserved in the respective modules' own plans — this phase is the
"other side" of those reservations, kept here since Compliance is the
common target across all of them.

## MCP tools and docs-website coverage — determination (2026-09-21)

**Decided by: User** — this session, the user asked that every not-yet-built
module plan in this roadmap make explicit whether it will (a) get narrow,
read-only MCP tools once its backend API ships, and (b) get a docs-website
coverage phase once its frontend or backend ships, following the pattern
`docs/plans/module-04-decision-management-plan.md`'s Phase 4 addendum and
Phase 6 established, and `docs/modules.md` §6 documents generically. Both
determinations below are reached by re-reading this plan's own three
phases rather than assumed, and are **Decided by: Agent**.

**MCP tools: does not apply to this plan.** Each of Phases 1–3 says
explicitly that it adds no new endpoint of Compliance's own: Phase 1 "no
new mechanism on the Compliance side beyond exposing itself as a linkable
target," Phase 2 is Governance's own baseline-policy configuration, and
Phase 3 is relationship-model wiring already reserved by the *other*
modules' own plans (Module 3's Risk phase, Module 4's Phase 3/7). There is
no phase here that stands up a router or endpoint this plan could declare
an `McpToolDefinition` against — `docs/modules.md` §6's own constraint (a
tool's `path_template` must fall inside the declaring module's own router
prefix) means a tool could not legally be declared here even if one were
wanted. Compliance's own already-shipped, read-only MCP tools
(`compliance_list_standards`, `compliance_list_requirements`, etc. —
`backend/app/modules/compliance/module.py`) already expose read access to
the "Compliance Requirement" rows this plan makes referenceable elsewhere;
nothing in this plan changes what they return. If Module 7 (Traceability)
or Module 8 (Governance) later add their own endpoints that surface this
integration (e.g. "list traceability rules that target a Compliance
Requirement"), any MCP tool for that belongs on those modules' own plans,
not here.

**Docs-website coverage: does not apply to this plan.** None of Phases 1–3
add a user-facing surface of their own — Phase 1's Traceability-rule
targeting, Phase 2's Governance baseline check, and Phase 3's relationship
wiring are all consumed through *other* modules' own UI (Traceability's
rule editor, Governance's baseline checklist, the consuming artefact's own
relationship panel), which those modules' own docs-website phases are
responsible for documenting once built. Per `CLAUDE.md`'s Docs Website
Maintenance rule ("if no [user-visible surface], no action is needed — do
not pad the site with updates for purely internal/backend-only changes"),
no phase is added here. The table above carries a fourth row recording
this determination so it is visible alongside the other three phases, not
only in this prose.

**Screenshot requirement (2026-09-22 addendum): this determination stands
for screenshots too, unchanged.** The user asked that every not-yet-built
module plan's Docs website coverage phase make `docs/plans/docs-website-
plan.md`'s screenshot standard explicit (**Decided by: User**); re-checking
that ask against this plan's own N/A finding above rather than overriding
it (**Decided by: Agent**), it doesn't change anything here — with no
docs-site page of its own, there is no page for this plan to add a
screenshot to. Any screenshot showing this integration's effects (e.g. a
Traceability rule targeting a Compliance Requirement, or a relationship
panel showing the link) belongs to the *consuming* module's own
docs-website phase and its own screenshot obligation, per the same
reasoning already given above for MCP tools and docs-website coverage
generally.

## Acceptance criteria (from overview §48, Compliance Integration subset)

- Compliance remains independently configurable. *(already true — shipped)*
- Compliance Requirements can participate in Traceability.
- Compliance evidence and approvals remain managed by Compliance.
  *(already true — this integration must not regress it, per Phase 0
  activity 2's confirmed reading)*
- Traceability can require Compliance relationships.
- Governance can require Compliance completion before baseline.
