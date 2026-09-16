# Module 8 — Governance / Policies — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout, including the
Governance-vs-Traceability-vs-relationships worked distinction table.

**Source:** [future-modules-2026-09-overview.md](future-modules-2026-09-overview.md)
§29–36 ("Module 8 — Governance / Policies" through "Governance Permissions").

**Status:** Proposed. Not started. Sixth in the overview's recommended
build order (§46 Phase 6) — built *before* Traceability (Phase 7), because
"Formal Traceability should require Governance" (overview §3.1).

## Status / Resume Here

0 / 5 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: policy-engine shape & open questions | [ ] Not started |
| 1 | Lifecycle policies (configurable per artefact type) | [ ] Not started |
| 2 | Approval policies (role-based, per artefact type) | [ ] Not started |
| 3 | Review policies (scheduled reassessment, generalised) | [ ] Not started |
| 4 | Baseline policies + Governance Health view | [ ] Not started |
| 5 | Frontend UI | [ ] Not started |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase exists:** Governance is explicitly meta — it "defines how
a project operates, rather than storing the project's engineering
artefacts" (§26.1) and must apply *generically* across every artefact type
this whole roadmap introduces (Requirement, Decision, Strategy, Pain Point,
Risk, Design, and — per §37 — Compliance too). Building it against one
artefact type at a time risks a policy engine that only really works for
whichever module existed when it was designed. This phase must confirm
Governance is built generically from day one, informed by what other
modules already exist by the time this one is picked up.

**Activities:**

1. **Confirm build-order reality check**: by the time Governance is
   actually implemented, which of Modules 1–6 already exist? Governance's
   lifecycle/approval/review/baseline policies (§31–34) are configured
   *per artefact type* — the policy engine needs a registry of "governable
   artefact types" that's extensible as later modules land, not a fixed
   list baked in against whatever exists at Governance's own build time.
   This is the same "extensible without redesign" principle as the
   relationship model (Module 1's Phase 1) — confirm the same discipline
   applies here.
2. Resolve remaining open questions below.
3. Confirm this module's relationship to the *existing* requirement
   lifecycle/approval/baselining logic already in this codebase (§34's
   baseline-policy example — "Required fields / Required approvals /
   Traceability / Verification / Compliance" — closely resembles what
   `services/requirements.py`'s existing approval/baseline gating already
   partially does for Requirements specifically). Read that service before
   designing Governance's generic version, so Governance generalises
   existing logic rather than duplicating it under a new name.

**Exit criteria:** user sign-off on the artefact-type-registry approach and
the four policy categories' schemas, before Phase 1.

### Open questions for Phase 0

1. **Is Governance a generic per-artefact-type policy engine, or a
   collection of purpose-built policies per module?** Recommend generic:
   a `GovernableArtefactType` concept (referencing whatever artefact types
   currently exist — Requirement, Decision, Strategy, Pain Point, Risk,
   Design, Compliance item) with `LifecyclePolicy`, `ApprovalPolicy`,
   `ReviewPolicy`, `BaselinePolicy` each scoped to one artefact type and
   one project. This is more work upfront but is the entire point of
   building Governance as a distinct module rather than hand-rolling
   lifecycle/approval logic per module (which is what the existing
   Requirement-specific logic already does, and what this module should
   generalise rather than replicate a seventh time for Risk, an eighth for
   Design, etc.).
2. **Does Governance *replace* the existing Requirement-specific
   lifecycle/approval/baseline logic, or sit alongside it?** A hard
   question — replacing risks regressing heavily-tested, SOC2-relevant
   existing behaviour (`services/requirements.py`, per `CLAUDE.md`'s
   explicit warning against "weakening org/project-scoped authorization
   checks" and similar regressions). Recommend: Governance's generic engine
   is built to eventually *subsume* the Requirement-specific logic, but the
   migration of Requirements onto the generic engine is its own carefully
   verified sub-phase (with the existing test suite as the regression
   bar), not a side effect of adding Governance for the *new* artefact
   types. New artefact types (Decision, Risk, etc.) should be built against
   the generic engine from the start; Requirements migrates onto it
   deliberately, separately, and only if the user confirms that's wanted
   (it may be entirely reasonable to leave Requirements on its own
   long-proven logic and have Governance apply only to the newer
   artefacts) — this is a real product decision, not a mechanical one.
3. **Review policy generalisation vs. existing `RequirementReview`.**
   §33's review-policy fields (interval, owner, due date, reminder,
   outcome, next review date) closely parallel `RequirementReview` +
   `RequirementVersion.review_date`/`review_lead_days`/`reviewer_id`
   already in this codebase. Same question as Q2, scoped to reviews
   specifically: generalise now for new artefact types, migrate
   Requirements later, don't touch the existing mechanism as a side effect.
4. **Governance Health — real-time computed, or a periodic snapshot?**
   §35's example (percentages per category) reads like a live dashboard
   query. Recommend computed on demand (same reasoning as Requirement Set
   version diffs in Module 5) rather than a scheduled batch job, unless
   performance on a large project later says otherwise.

## Phase 1 — Lifecycle policies (configurable per artefact type)

**Scope** (§31): per-project, per-artefact-type lifecycle state/transition
configuration. For artefact types with an overview-specified default
lifecycle (Requirements' existing Draft/Reviewed/Approved/Archived,
Decisions' Draft/Proposed/Under Review/Approved/Superseded, Pain Points'
branching lifecycle), Governance's job is to make the *transition rules*
(who can move what, when) configurable — not necessarily to replace each
module's own state enum, which stays specific to that artefact.

**Why:** §26.1 — "governs lifecycle... rather than storing the project's
engineering artefacts" — this is explicitly about *rules*, not *data*,
which is why it's a separate module from every artefact-owning module
above it.

## Phase 2 — Approval policies (role-based, per artefact type)

**Scope** (§32): "Architecture Decisions require approval by an Architecture
Approver," etc. — policies reference roles, never individual people (§32's
explicit requirement). This is where Decision Management's own Phase 0 Q2a
(deferred approver-assignment question) gets its real answer: Governance
owns the general policy ("this Decision Type needs this role's approval"),
and Decision Management's own Phase 2 approval endpoint checks against
whatever Governance configured, once Governance exists — until then,
Decision Management's Phase 2 uses a single placeholder role, per that
plan's own note.

**Why:** §32 — without centralising this, each module (Decisions, Risk,
Strategy, Design) would independently reinvent "who can approve this,"
producing exactly the kind of scattered, inconsistent enforcement the
whole modular architecture exists to avoid (per `docs/modules.md`'s stated
motivation).

## Phase 3 — Review policies (scheduled reassessment, generalised)

**Scope** (§33): interval, owner, due date, reminder, outcome, next review
date — generalised across artefact types, per Phase 0 Q3's resolution.

**Why:** §33 — Strategy, Guiding Principles, Risks, and Decisions (per
§13/10.4's implicit "reviewed after major architecture changes" idea) all
plausibly need scheduled reassessment; today only Requirements have this
(`RequirementReview`). Building it generically once avoids a sixth
bespoke review-scheduling mechanism.

## Phase 4 — Baseline policies + Governance Health

**Scope** (§34–35): configurable pre-baseline checks (required fields,
required approvals, traceability, verification, compliance — not all
enabled per project, per §34's explicit "not all checks need to be enabled
for every project"), plus the aggregate Governance Health view (§35) —
percentage-complete per governed category, open-question count, etc.

**Why:** §34 — this is where Governance and Traceability's separation
becomes concrete: the Traceability *rule* says a link is required; the
Baseline *policy* says that missing link blocks baselining. Without this
module, Traceability (once built) would have no lever to actually enforce
anything — it would be purely informational.

## Phase 5 — Frontend UI

Project settings surfaces for configuring each policy category (per the
UX style guide's settings-hierarchy-depth model — this is exactly the kind
of "new settings surface" the style guide's principles govern), plus the
Governance Health dashboard view. Playwright e2e + Storybook coverage.

## Acceptance criteria (from overview §48, Governance subset)

- Governance can be enabled/disabled per project.
- Projects can configure lifecycle policies.
- Projects can configure approval policies.
- Projects can configure review policies.
- Projects can configure baseline policies.
- Policies reference roles rather than requiring specific individuals.
- Governance can use Traceability results. *(depends on Module 7, built after this one)*
- Governance can use Compliance results. *(depends on Module 9 integration)*
- Governance checks can provide an overall project health view.
