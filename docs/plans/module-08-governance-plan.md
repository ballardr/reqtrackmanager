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
| 6 | Docs website coverage | [ ] Not started — depends on Phase 5 shipping |

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

**MCP tools.** The instruction to give every not-yet-built module plan this
same explicit MCP-tools and docs-website treatment is **Decided by: User**
(2026-09-21); which phase to amend and the specific candidate names below
are **Decided by: Agent** — Phase 4 is chosen because it's the last
backend-building phase in this plan's own sequence, by which point the full
lifecycle/approval/review/baseline-policy CRUD surface from Phases 1–4
exists (this plan has no single consolidated "Backend API" phase the way
Module 4's plan does). Once these endpoints exist, declare narrow,
read-only-only `McpToolDefinition` entries per
[docs/modules.md](../modules.md) §6, following the Compliance and Decision
Management (`module-04-decision-management-plan.md`) precedent. Concrete
candidates: "list lifecycle policies", "list approval policies" (both
per-artefact-type, Phases 1–2), and "get governance health" (§35's
aggregate view, Phase 4).

**Extra care, per this task's own instruction: Governance defines Approval
Policies as a core concept (Phase 2, §32) — this is not a smaller exception
to the read-only rule, it is exactly the kind of route the rule exists for.**
The distinction that matters: Phase 2's own CRUD endpoints for *configuring*
an Approval Policy (create/list/get/update/delete "Architecture Decisions
require approval by an Architecture Approver") are ordinary configuration
endpoints — listing/getting them is a safe read-only MCP candidate like any
other definition table in this codebase. What must never be an MCP tool,
here or in any artefact-owning module that later consults a Governance
policy, is the endpoint that actually *executes* an approval decision under
that policy (e.g. a content module's own `approve`/`reject` route, or any
future Governance-side override/exception endpoint that itself finalizes a
blocked baseline or lifecycle transition) — every such route is marked
`openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA` (`backend/app/modules/
registry.py`) at build time, mechanically excluding it from the manifest,
the same way Decision Management's own `approve`/`reject` routes already
are per that plan's MCP-tools addendum. This applies regardless of which
module's router the approval-executing endpoint physically lives in —
Governance owning the *policy* never makes the *act of approving* under it
any safer to expose than it already wasn't.

## Phase 5 — Frontend UI

Project settings surfaces for configuring each policy category (per the
UX style guide's settings-hierarchy-depth model — this is exactly the kind
of "new settings surface" the style guide's principles govern), plus the
Governance Health dashboard view. Playwright e2e + Storybook coverage.

## Phase 6 — Docs website coverage

Adding this as its own explicit, tracked phase (rather than leaving it
implicit) is **Decided by: User** (2026-09-21, the same instruction as the
MCP-tools addition above, applied to every not-yet-built module plan); the
specific scope below is **Decided by: Agent**.

**Goal:** add Governance's user-facing surface to `docs/website/` (the
published docs site, `docs/plans/docs-website-plan.md`) — modeled closely
on `module-04-decision-management-plan.md`'s own "Phase 6 — Docs website
coverage", adapted to this module's own content rather than copied.

**Why this is its own tracked phase, not folded silently into Phase 5:**
`CLAUDE.md`'s "Docs Website Maintenance" rule already requires this check
on every change with a user-facing surface, in the same change rather than
deferred. It is broken out explicitly here, mirroring Decision
Management's own Phase 6 reasoning, because Governance is explicitly meta
(§26.1) and its documentation has to get the module boundary right for
readers, not just describe screens — the four policy categories, the
generic per-artefact-type registry they apply against, and the explicit
non-replacement of any existing Requirement-specific logic (Phase 0 Q2/Q3)
are all easy to under-explain in a single paragraph folded into Phase 5.

**Scope:**

- A new docs-site page (or section, matching whatever grouping the site
  uses for other project-scoped modules) covering: what Governance is and
  is not (it configures *rules* about lifecycle/approval/review/baseline,
  it does not store engineering artefacts itself, §26.1); the four policy
  categories (Lifecycle, Approval, Review, Baseline) and which artefact
  types each currently governs, framed as an extensible registry rather
  than a fixed list; that approval and review policies reference *roles*,
  never specific individuals (§32's explicit requirement); the explicit,
  important caveat that Requirements' own long-established lifecycle/
  approval/baseline logic is not replaced by Governance as a side effect of
  this module shipping — only new artefact types are built against the
  generic engine from the start, per Phase 0 Q2's resolution — so a reader
  should not assume Governance immediately supersedes existing Requirement
  behaviour; and the Governance Health view (§35) as a live, computed
  aggregate, not a periodic snapshot. Include a Mermaid diagram showing how
  Traceability's rule-satisfaction signal feeds a Baseline Policy's
  decision to block or allow baselining (§34, and this module's own
  Phase 4 "Why") — this exact hand-off is the one the roadmap's own
  Governance-vs-Traceability distinction table exists to clarify, and is
  worth restating visually here since Traceability's own Phase 7 docs page
  will describe the same boundary from its side.
- Update the site's module/feature index or nav to include Governance once
  it ships.
- Cross-link from any documentation this repo already has for Requirements'
  existing lifecycle/approval/baseline behaviour, noting explicitly whether
  or not it has migrated onto the generic Governance engine at the time
  this page is written (per Phase 0 Q2's deliberately separate, later
  migration decision) — this cross-link must not silently assume migration
  happened just because Governance shipped.
- **Screenshot requirement (2026-09-22 addendum).** Making this explicit
  here rather than leaving it implicit is **Decided by: User** (the same
  instruction as the phase itself, applied specifically to screenshots this
  time — `docs/plans/docs-website-plan.md`'s "Screenshots" section already
  bound this page to its standard, but this phase's Scope above never said
  so in as many words). This page is subject to that standard in full:
  1440×900 viewport, captured against the seeded demo dataset
  (`backend/scripts/seed_demo_data.py`), stored under
  `docs/website/static/img/screenshots/`, real alt text plus a one-line
  caption, no surrounding "what this shows/why it matters" prose. Per that
  standard's "at least one screenshot or diagram per page, not forced onto
  every page" bar, plausible candidate screens (**Decided by: Agent**) are
  a project settings screen for one of the four policy categories (e.g.
  Baseline Policy configuration, since it's the one this phase's own
  Mermaid diagram above already discusses) and the Governance Health
  dashboard view.

**Status:** not started. Depends on Phase 5 (frontend) actually shipping —
there is no real user-facing workflow to document accurately before then,
the same reasoning Decision Management's own Phase 6 and Compliance's
docs-site page both used.

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
