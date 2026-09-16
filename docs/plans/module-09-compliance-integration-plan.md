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

## Acceptance criteria (from overview §48, Compliance Integration subset)

- Compliance remains independently configurable. *(already true — shipped)*
- Compliance Requirements can participate in Traceability.
- Compliance evidence and approvals remain managed by Compliance.
  *(already true — this integration must not regress it, per Phase 0
  activity 2's confirmed reading)*
- Traceability can require Compliance relationships.
- Governance can require Compliance completion before baseline.
