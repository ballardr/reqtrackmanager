# Module 7 — Traceability — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout, especially the
relationship-vs-traceability-vs-governance distinction table. This module
hard-depends on [Module 0 — Platform Foundations](module-00-platform-foundations-plan.md)
for the relationship model — this module is the heaviest *consumer* of
that infrastructure (a generic rule/matrix engine needs it far more than
any single content module does), not its origin.

**Source:** [future-modules-2026-09-overview.md](future-modules-2026-09-overview.md)
§17–28 ("Module 7 — Traceability" through "Traceability Configuration
Permissions") — the most detailed and heavily-specified module in the
entire overview.

**Status:** Proposed. Not started. Seventh in the overview's recommended
build order (§46 Phase 7) — explicitly requires Governance (Module 8) to
exist first, and depends on whichever artefact types its configured rules
target (so realistically depends on however many of Modules 1–6 are live
by the time it's picked up).

## Status / Resume Here

0 / 6 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: rule-engine shape & open questions | [ ] Not started |
| 1 | Traceability enable/disable + rule configuration | [ ] Not started |
| 2 | Enforcement levels + baseline/approval integration (via Governance) | [ ] Not started |
| 3 | Traceability exceptions | [ ] Not started |
| 4 | Cross-project traceability | [ ] Not started |
| 5 | Traceability matrices + coverage reporting | [ ] Not started |
| 6 | Frontend UI | [ ] Not started |
| 7 | Docs website coverage | [ ] Not started — depends on Phase 6 shipping |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase exists:** the overview is unusually prescriptive here
(§19's explicit rule-shape examples, §26's example matrix configs), which
is good — most of the ambiguity other modules face is already resolved.
What remains is confirming this module's rule engine can actually express
everything §19 promises ("Required one of several target types, Required
all target types, Minimum/Maximum number of links, Specific relationship
types, Conditional rules") without turning into a bespoke query-language
project. This phase should produce a concrete rule schema and validate it
against every example in §18–19 and §21 before Phase 1.

**Activities:**

1. Design a concrete `TraceabilityRule` schema and manually check it can
   express every example in §18 ("every Project Requirement must derive
   from ≥1 Stakeholder Requirement"), §19 (OR-of-types, AND-of-conditions
   examples), and confirm it degrades gracefully to the three named UI
   presets (§19: No linking required / Type linking required / Type
   and/or Compliance linking required).
2. Confirm this module's dependency on Governance (Module 8) concretely:
   which parts of §20 ("Required for approval/baseline") are actually
   Traceability's own responsibility (computing "is this rule satisfied")
   vs. Governance's (deciding "does an unsatisfied rule block baselining")?
   Recommend: Traceability computes and exposes a boolean/status per rule
   per artefact instance; Governance's baseline policy (Module 8 Phase 4)
   is what actually consults it and blocks. Traceability should not itself
   block anything — that would blur the exact separation §30 insists on.
3. Confirm the relationship-model shape Module 0 built can support
   arbitrary-type-pair rules without
   per-pair special-casing — if per-pair join tables were chosen instead of
   a polymorphic table, this module's rule engine has to enumerate known
   tables, which is a real constraint worth surfacing to the user now,
   since it's the clearest place in the whole roadmap where that earlier
   choice's cost shows up concretely.
4. Resolve remaining open questions below.

**Exit criteria:** user sign-off on the rule schema (validated against the
overview's own examples) and the Traceability/Governance division of
responsibility, before Phase 1.

### Open questions for Phase 0

1. **Rule schema shape.** Recommend: `TraceabilityRule` = source artefact
   type, relationship type (or type-set), target artefact type(s) (a rule
   can list multiple acceptable target types, combined via ALL or ANY per
   §19's two worked examples), min links, max links (nullable = no max),
   `is_mandatory`, `enforcement_level` (Informational/Warning/Required —
   §20). A rule "requiring Business Requirement AND Verification Action"
   (§19's second example) is two `TraceabilityRule` rows sharing the same
   source type, not one row with compound logic — simpler to implement and
   query, and matches how the first example ("Business Requirement OR
   Compliance Requirement") is naturally one row with two acceptable target
   types. Confirm with user before building — this determines the entire
   rule-evaluation query shape.
2. **Requirement-type hierarchy configuration (§23) — same table as
   general Traceability rules, or a distinct "expected hierarchy" concept?**
   §23 reads as a specific, common case of the general rule schema (Project
   Requirement → Derived From → Stakeholder Requirement, marked mandatory)
   rather than a separate mechanism — recommend implementing it as an
   ordinary `TraceabilityRule` row, with the UI in Phase 6 presenting it
   as a dedicated "requirement hierarchy" configuration screen for
   discoverability, without a second underlying data model.
3. **Exception approval role.** §22 wants exceptions "Requested by /
   Approved by" — same Approve-level role as Governance's approval
   policies, or Traceability's own dedicated role? Recommend reusing
   whatever role Module 8 already establishes for approvals generally
   (Traceability Manager per §28, but exception *approval* specifically
   might need to be a a Governance-level approver, not the person who
   configured the rule in the first place — a self-approval risk worth
   flagging explicitly).
4. **Matrix configuration: stored view definitions, or ad-hoc query
   builder only?** §26 wants user-configurable matrices (any artefact-type
   chain, not just Business→Stakeholder→Project). Recommend a saved
   `TraceabilityMatrixDefinition` (ordered list of artefact types + the
   relationship types connecting them) so a project can name and reuse a
   matrix view, consistent with Reporting's own "configurable report
   templates, themselves versioned" pattern (Module 10 §47.8) — these two
   should probably share design language even if built as separate tables.

## Phase 1 — Traceability enable/disable + rule configuration

**Scope** (§17, §18–19, per Phase 0's rule schema): per-project enable/
disable toggle (§17's explicit requirement — disabling must leave normal
relationships and everything else fully intact, per §2.3/§17's own list);
`TraceabilityRule` CRUD, scoped to Traceability Manager/Project
Administrator (§28).

**Why:** §17.1 — Traceability's entire value proposition is that
enabling/disabling it changes *only* whether rules are enforced, never
whether relationships exist or can be created — this is the module's most
important non-negotiable property and should be the first thing tested
once Phase 1 lands (a project with Traceability disabled must behave
identically, for relationship-creation purposes, to one that never enabled
it at all).

## Phase 2 — Enforcement levels + baseline/approval integration (via Governance)

**Scope** (§20–21, per Phase 0 activity 2's resolved division of
responsibility): Informational / Warning / Required-for-approval
enforcement levels; a computed "traceability status" per artefact instance
(§21's worked example — per-required-relationship-type checkmarks);
exposed to Governance's baseline policy (Module 8 Phase 4) as a queryable
signal, not enforced directly by this module.

**Why:** §20 — "the preferred implementation is generally not to block
creation... a project can prevent formal approval/baselining" — this
directly implements §2.4's design principle (governance affects lifecycle
transitions, not draft creation).

## Phase 3 — Traceability exceptions

**Scope** (§22, per Phase 0 Q3): `TraceabilityException` — artefact, rule,
reason, requested by, approved by, expiry/review date, evidence. Reporting
must distinguish "satisfies the rule" from "has an approved exception" at
every point that surfaces traceability status (§22's explicit audit-
relevant requirement) — this is a rendering/query requirement threaded
through Phases 2, 5, and 6, not just a storage requirement here.

**Why:** §22 — legitimate exceptions ("this specific link genuinely
doesn't apply here") must not silently look identical to "this rule is
satisfied," or an audit reviewing traceability completeness would be misled
into thinking real coverage exists where only a waiver does.

## Phase 4 — Cross-project traceability

**Scope** (§24): relationships between nested/related projects (e.g. a
Hardware/Software project's requirements tracing back to a parent Product
project's Business Requirements), respecting each user's actual access —
"a user should only see or create links to artefacts they are authorised
to access" (§24's explicit constraint). This needs the relationship model
to support cross-project FKs (or cross-project references via IDs checked
against the querying user's actual project permissions at read time, not
just existence) — confirm with existing nested-project permission logic
(from the already-shipped Project Hierarchy work, per memory) before
assuming a straightforward FK suffices.

**Why:** §24 — without this, ReqTrackManager's existing nested/parent-child
project structure (already shipped) can't answer "does this child project's
requirement trace back to the parent's business requirement," which is
exactly the kind of system-decomposition traceability formal engineering
programmes need (§24's own framing).

## Phase 5 — Traceability matrices + coverage reporting

**Scope** (§25–27, per Phase 0 Q4): matrices as **generated views over the
relationship graph**, never a separately maintained data structure (§25's
explicit, load-bearing requirement); configurable artefact-type chains
(§26); coverage metrics (§27 — percentage with required links, percentage
verified, orphan counts, exception-covered counts).

**Why:** §25 — a manually-maintained traceability matrix is exactly the
"second source of truth" anti-pattern this whole roadmap explicitly warns
against elsewhere (§47.1's Reporting principle, stated generally but
directly applicable here); computing it live from real relationship data is
what makes it trustworthy.

**MCP tools.** The instruction to give every not-yet-built module plan this
same explicit MCP-tools and docs-website treatment is **Decided by: User**
(2026-09-21); which phase to amend and the specific candidate names below
are **Decided by: Agent** — Phase 5 is chosen because it's the last
backend-building phase in this plan's own sequence, by which point the full
rule-configuration/enforcement/exception/matrix surface from Phases 1–5
exists (this plan has no single consolidated "Backend API" phase the way
Module 4's plan does). Once these endpoints exist, declare
`McpToolDefinition` entries per [docs/modules.md](../modules.md) §6,
following the Compliance and Decision Management
(`module-04-decision-management-plan.md`) precedent. Concrete candidates:
"list/create traceability rules" (a project's configured rules and their
enforcement level), "get traceability matrix" (a saved
`TraceabilityMatrixDefinition`'s generated view, §25), "get coverage
report" (§27's percentages/orphan counts), "request traceability exception"
(Phase 3, §22 — the request itself, not the decision on it).

**2026-09-22 update (Decided by: User):** this section originally committed
to **read-only-only** MCP tools; per the same reversal applied to the
Compliance module (`docs/decisions.md`'s "Compliance MCP write tools +
generalized AI approval gate" entry), this module should instead commit to
**write-enabled** MCP tools once built — rule configuration and exception
*requests* declared normally (gated by `MCP_WRITES_ENABLED` + the calling
account's own RBAC role). *Approving* a traceability exception remains the
exception: it is an approve/decide-type action — and Phase 0 Q3's own flag
of exception approval as a self-approval risk is exactly the kind of
"specific reason to keep it human-only" this task's own instructions
anticipate — so it should stay marked `openapi_extra=
APPROVAL_ACTION_ROUTE_EXTRA` (option (b)) rather than getting the
generalized `allow_ai_approvals` gate, unlike this plan's other
approve/decide-shaped candidates in the modules 1/3/5/6 revisions. This is
a judgment call at plan-time (**Decided by: Agent**); the underlying
instruction to move this plan's non-approval tools off read-only-only is
**Decided by: User** (2026-09-22).

## Phase 6 — Frontend UI

Rule configuration screens (per Phase 0 Q1's schema, with the three named
presets from §19 as a simplified "quick setup" path over the full rule
editor), per-artefact traceability-status display (§21's checkmark
example), matrix viewer, coverage dashboard, exception request/approval
flow. Playwright e2e + Storybook coverage; enum/status values through
label maps.

## Phase 7 — Docs website coverage

Adding this as its own explicit, tracked phase (rather than leaving it
implicit) is **Decided by: User** (2026-09-21, the same instruction as the
MCP-tools addition above, applied to every not-yet-built module plan); the
specific scope below is **Decided by: Agent**.

**Goal:** add Traceability's user-facing surface to `docs/website/` (the
published docs site, `docs/plans/docs-website-plan.md`) — modeled closely
on `module-04-decision-management-plan.md`'s own "Phase 6 — Docs website
coverage", adapted to this module's own content rather than copied.

**Why this is its own tracked phase, not folded silently into Phase 6:**
`CLAUDE.md`'s "Docs Website Maintenance" rule already requires this check
on every change with a user-facing surface, in the same change rather than
deferred. It is broken out explicitly here, mirroring Decision
Management's own Phase 6 reasoning, because this module's user-facing
surface is unusually broad and easy to under-scope for one phase (rule
configuration, enforcement levels, the Governance integration boundary,
exceptions, cross-project traceability, and matrix/coverage reporting all
land in the same Phase 6 UI at once).

**Scope:**

- A new docs-site page (or section, matching whatever grouping the site
  already uses for other project-scoped modules) covering: what
  Traceability rules are and the explicit, load-bearing guarantee that
  disabling Traceability never disables ordinary relationships (§17.1); the
  three enforcement levels (Informational/Warning/Required-for-approval,
  §20) and — critically, since this is the exact boundary the overview
  insists on (§30) — that Traceability only *computes and exposes* rule
  status, while Governance's baseline policy (Module 8 Phase 4) is what
  actually blocks anything; how the three named UI presets relate to the
  full rule editor (§19); the exception mechanism, including that an
  approved exception is always rendered distinctly from genuine rule
  satisfaction, never merged into the same "covered" indicator (§22); and
  traceability matrices/coverage reporting as generated views over live
  relationship data, never a separately maintained structure (§25). Include
  a Mermaid diagram of the Traceability/Governance/relationship-model
  division of responsibility (Module 0 owns relationships, this module
  computes rule status against them, Governance decides what blocks
  baselining) — this exact three-way boundary is the single most likely
  thing for a reader to conflate.
- Update the site's module/feature index or nav to include Traceability
  once it ships, noting its dependency on Governance (Module 8).
- Cross-link from the Governance documentation wherever it already
  discusses baseline policies consulting Traceability status, and from the
  Requirements documentation wherever it discusses requirement-type
  hierarchy configuration (§23, which this module implements as an
  ordinary `TraceabilityRule` row rather than a separate mechanism).
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
  the rule configuration screen (including the three named quick-setup
  presets), the per-artefact traceability-status indicator, and the
  matrix/coverage dashboard — the Mermaid diagram above already covers the
  Traceability/Governance/relationship-model boundary itself and doesn't
  need a duplicate screenshot.

**Status:** not started. Depends on Phase 6 (frontend) actually shipping —
there is no real user-facing workflow to document accurately before then,
the same reasoning Decision Management's own Phase 6 and Compliance's
docs-site page both used. Also depends, for the Governance cross-link
specifically, on Module 8's own docs-website coverage existing to link to.

## Acceptance criteria (from overview §48, Traceability subset)

- Traceability can be enabled/disabled per project.
- Disabling Traceability does not disable normal relationships.
- Projects can define Traceability Rules.
- Rules can require relationships.
- Rules can target requirement types.
- Rules can target Compliance Requirements.
- Rules can require one or multiple relationships.
- Rules have configurable enforcement.
- Missing mandatory relationships are clearly identified.
- Traceability can prevent approval/baselining where configured. *(via Governance, Module 8)*
- Exceptions can be formally approved.
- Traceability Matrices are generated from actual relationships.
- Traceability supports cross-project relationships subject to permissions.
