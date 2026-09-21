# Module 10 — Reporting & Analysis — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout. This module hard-depends
on [Module 0](module-00-platform-foundations-plan.md) for relationship
traversal, and otherwise consumes whatever of Modules 1–9 is enabled at
generation time (see "Incremental delivery" below).

**Source:** [future-modules-2026-09-overview.md](future-modules-2026-09-overview.md)
§47 "Module 10 — Reporting & Analysis".

**Status:** Proposed. Not started. Last in the overview's recommended
build order (§46 Phase 9) by design — §47.1's "Authoritative Data
Principle" means this module has nothing to report on until the modules
that own real data exist. This plan's phases can start incrementally as
each source module lands, rather than waiting for all nine others to
finish — see "Incremental delivery" below.

## Incremental delivery, not a single big-bang phase

Overview §47.9's own Phase 9 groups four reports (Business Requirements
Document, Engineering Specification, Executive Gap Analysis, Engineering
Change Impact) as the *first* increment, then extends the same
infrastructure to further report types. This plan follows that shape:
Phase 1 builds the reporting *engine* (template versioning, provenance
recording, output generation) against whatever data already exists at the
time (at minimum: Requirements, which predate this whole roadmap); each
subsequent report type is its own phase, addable independently as its
source modules mature. A report that references an unbuilt module's data
(e.g. Executive Gap Analysis referencing Future State before Module 1
ships) should degrade gracefully (omit that section) rather than block the
whole report type on every other module finishing.

## Status / Resume Here

0 / 8 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: reporting engine shape & provenance model | [ ] Not started |
| 1 | Reporting engine core: templates, provenance, output generation | [ ] Not started |
| 2 | Business Requirements Document | [ ] Not started |
| 3 | Engineering Specification | [ ] Not started |
| 4 | Executive Gap Analysis | [ ] Not started |
| 5 | Engineering Change Impact | [ ] Not started |
| 6 | Remaining report types (matrices, registers, packages, adoption/audit reports) | [ ] Not started |
| 7 | AI-assisted analysis (exploratory extension) | [ ] Not started |
| 8 | Docs website coverage | [ ] Not started — incremental, see Phase 8 |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase exists:** §47.1's Authoritative Data Principle and §47.8's
configurable-template requirement together imply a real templating/
generation engine, not a set of hard-coded report pages — but the overview
doesn't specify an output format (HTML? PDF? both?), a templating mechanism,
or how "configurable" the fields/filters/grouping/ordering in §47.8 need to
be in practice (a full drag-and-drop report builder is a very different
scope than a handful of admin-configurable toggles per report type). This
phase settles that before Phase 1.

**Activities:**

1. Confirm output format(s) required — check whether existing Compliance
   reporting already established a PDF/CSV export pattern
   (`docs/decisions.md`'s "compliance report PDF/CSV output" phases,
   referenced in memory) and reuse that mechanism rather than inventing a
   second one, per the "one component per pattern" principle applied to
   backend export machinery.
2. Confirm the realistic scope of "configurable" for §47.8 — recommend
   starting with per-report-type configuration (which sections, which
   filters, field selection) rather than a generic drag-and-drop builder,
   and treating a true report-builder UI as a later enhancement only if
   real usage shows the fixed configuration surface is insufficient.
3. Confirm the provenance-record shape (§47.2's minimum fields: project,
   generation timestamp, baseline/version, included artefact versions,
   template definition, generator/report version, filters/config) — decide
   whether this is stored as a row per generated report (so a past report
   can be re-opened and still show what it was generated from) or only
   stamped into the output document itself. Recommend a stored row (a
   `GeneratedReport` record) — a document-only stamp can't be queried
   later ("show me every report generated against Requirement Set v1.1
   before it was retired"), which §47.2's own emphasis on provenance
   implies matters.
4. Confirm report templates are versioned as real rows (§47.8's closing
   line), not just a version number embedded in code — this determines
   whether template edits need their own approval/versioning workflow or
   are just ordinary configuration changes.

**Exit criteria:** user sign-off on output format, configuration scope, and
the provenance-record shape, before Phase 1.

### Open questions for Phase 0

1. **Who can configure report templates?** Not addressed explicitly in
   §47 — recommend a project-level "Report Manager"-equivalent role, per
   the common permission model, rather than requiring Project
   Administrator.
2. **Does the reporting engine need its own relationship-traversal query
   layer, or does it call the same generic relationship-query helpers
   Module 0 built?** Recommend the latter — Reporting is
   explicitly meant to be "a presentation layer over project data" (§47's
   closing line), so it should consume existing query infrastructure, not
   build a parallel one.

## Phase 1 — Reporting engine core: templates, provenance, output generation

**Scope** (per Phase 0's resolution): `ReportTemplate` (versioned, per
Phase 0 activity 4), `GeneratedReport` (provenance record, per activity 3),
and the generation pipeline itself (fetch data per template config →
render → stamp provenance → store/export).

**Why:** §47.1–47.2 — every report type built afterward shares this
infrastructure; building report-type-specific generation logic before this
exists would mean re-deriving provenance/templating four separate times
across Phases 2–5.

**MCP tools (2026-09-21 addendum).** This session, the user asked that
every not-yet-built module plan make explicit that it will get narrow,
read-only MCP tools once its backend API ships (**Decided by: User**); the
specifics below are **Decided by: Agent**, following `docs/modules.md` §6
and the Compliance/Decision-Management precedent (`backend/app/modules/
compliance/module.py`; `backend/app/modules/decisions/module.py`'s Phase 4
addendum) rather than re-explaining the mechanism inline. Once this
phase's endpoints exist, declare narrow, read-only (`GET`)
`McpToolDefinition` entries for the safe list/get surfaces — candidates:
`list_report_templates(project_id)`, `get_report_template(project_id,
template_id)`, `list_generated_reports(project_id)` (the provenance-record
listing from Phase 0 activity 3), and `get_generated_report(project_id,
report_id)` (a single provenance record and a pointer to its stored
output). Explicitly excluded: the generation action itself (however Phase
0 ultimately shapes its endpoint), template create/update/delete, and any
future report-type-specific generation endpoint Phases 2–6 add — triggering
generation is a mutating, potentially resource-intensive action, not a
read, so it gets the same treatment this codebase gives every other
mutating action: no `McpToolDefinition` declared for it at all. Exact tool
names may shift once Phase 0 settles the real API shape (output format,
template CRUD surface); this is a scope commitment, not a final contract.

## Phase 2 — Business Requirements Document

**Scope** (§47.3): purpose/scope, Pain Points, Stakeholders/Personas,
Stakeholder Needs, business objectives/Strategy, Future State, Business
Requirements, constraints/assumptions, key Decisions, risks/business
impacts, traceability summary, Open Questions, approval/baseline info.

**Why:** §47.3 — makes the business rationale legible to non-engineering
stakeholders directly from authoritative data, replacing a manually
maintained parallel document.

**Dependency note:** this report's full value depends on Modules 1–4 all
existing (Pain Points, Stakeholders, Strategy, Decisions) — if built before
those modules land, it should render a partial document (omitting
unavailable sections) rather than being blocked entirely, per this plan's
"incremental delivery" framing.

## Phase 3 — Engineering Specification

**Scope** (§47.4): scope/system context, requirement hierarchy/types,
stakeholder/system needs, constraints/assumptions, compliance obligations,
decisions affecting the spec, Engineering Design relationships, interfaces,
verification/validation relationships (via `RequirementAction`, per the
index's confirmed finding), traceability coverage, baselines/revisions.

**Why:** §47.4 — the technical counterpart to the Business Requirements
Document, configurable per engineering discipline (§47.4's closing line).

## Phase 4 — Executive Gap Analysis

**Scope** (§47.5): current vs. required capability, current vs. Future
State, requirement coverage gaps, design maturity gaps, compliance gaps,
high/residual risks, open Decisions/Questions, major dependencies, areas
needing investment — each gap must identify its supporting artefacts
(§47.5's explicit auditability requirement, so a management finding always
traces back to real engineering evidence, never a bare assertion).

**Why:** §47.5 — gives executives a digestible view "without requiring
[them] to navigate the complete engineering model," while keeping every
finding traceable, unlike a hand-written status summary.

## Phase 5 — Engineering Change Impact

**Scope** (§47.6): traversal from a changed artefact through upstream/
downstream requirements, stakeholders, decisions, designs, interfaces/child
projects, verification, compliance, risks, to generated documents/
baselines — distinguishing direct vs. transitive vs. inferred-potential
impacts, artefacts requiring review, baselines potentially invalidated,
reports requiring regeneration. Explicitly reuses the existing Change
Management capability (§47.6's own instruction) rather than a new
change-control system.

**Why:** §47.6 — this is the concrete mechanism behind every other module's
"changes can participate in Change Impact analysis" acceptance criterion
(Stakeholders §48, Risk §48) — those modules only need to expose
relationship data; this phase is where the actual traversal/analysis logic
lives, once, generically.

## Phase 6 — Remaining report types

**Scope** (§47.7): Traceability matrices (reuses Module 7's own matrix
infrastructure directly — this phase's job is presentation/export, not a
second matrix engine), requirement coverage reports, compliance
assessments, risk registers, decision registers, design descriptions,
review packages, baseline comparison reports, requirement-set adoption
reports, audit/history reports. Each is a template built on Phase 1's
engine, addable independently as its source module exists.

## Phase 7 — AI-assisted analysis (exploratory extension)

**Scope** (§47.9): missing/weak traceability, requirement conflicts,
orphaned artefacts, designs lacking rationale, risks without effective
mitigation, stale decisions, evidence needing review, potential change
impacts, potential relationships for confirmation, draft report content,
current/future-state gaps. §47.9's explicit constraint: AI-generated
findings must identify source artefacts and stay clearly distinguishable
from approved project information — never silently alter authoritative
records.

**Why deferred and marked "exploratory extension" rather than a normal
phase:** this is explicitly framed as *future* in the overview itself
("Future AI capabilities should operate...") and depends on essentially
everything else in this roadmap existing first to have enough real data to
analyze meaningfully. This phase's own Phase-0-equivalent work (what
exactly gets automated, what human review gate wraps each finding type)
should happen close to when it's actually picked up, not speculatively now.

## Phase 8 — Docs website coverage

**Goal:** add Reporting & Analysis's user-facing surface to
`docs/website/` (the published docs site, `docs/plans/docs-website-plan.md`)
— what the reporting engine is, the provenance model, and each shipped
report type — following the site's existing structure, tone, and
Mermaid-diagram conventions (per this repo's Documentation Requirements:
prefer diagrams, validate they render before finalising).

This phase is added per this session's instruction that every not-yet-built
module plan make explicit its docs-website coverage commitment
(**Decided by: User**, 2026-09-21); its specific incremental shape below is
**Decided by: Agent**, adapted to this module's own "Incremental delivery"
framing rather than copied from another module's single-shot version of
this phase.

**Why this is its own tracked phase, and incremental rather than a single
pass:** this module's own "Incremental delivery" section above means there
is no single point at which "the frontend" ships — Phase 1 builds the
engine, then each report type (Phases 2–6) and the AI-assisted extension
(Phase 7) lands independently, potentially with real time gaps between
them. A docs-website phase gated on all of them finishing at once would
mean the site describes nothing for a long time after several report types
are already usable, or gets written once and silently drifts as later
report types ship undocumented. This phase is instead a standing
commitment revisited at each source phase's own completion, the same
incremental spirit as the feature it documents.

**Scope, performed incrementally as each source phase ships:**

- On Phase 1 shipping: a docs-site page introducing the reporting engine —
  what a report template and a generated report are, the provenance model
  (§47.2: project, generation timestamp, baseline/version, included
  artefact versions, template definition, generator/report version,
  filters/config), and the "reports do not silently become a second source
  of truth" principle — as a short Mermaid diagram of generation →
  provenance stamping → storage/export.
- On each of Phases 2–6 shipping: a subsection for that report type — what
  it contains, which source modules it draws from, and (per §47.5's own
  auditability requirement, most sharply for the Executive Gap Analysis)
  how a finding traces back to its supporting artefacts — plus an update to
  the site's module/feature index wherever other report types are already
  listed.
- On Phase 7 shipping: a subsection explaining that AI-assisted analysis
  findings are always clearly distinguishable from approved project
  information (§47.9), never presented as authoritative on their own.
- Cross-link from each source module's own docs-website page (e.g.
  Decision Management's, Compliance's) to the report type(s) that consume
  its data, wherever the site already cross-links traceability/consumption
  relationships elsewhere.
- **Screenshot requirement (2026-09-22 addendum).** Making this explicit
  here rather than leaving it implicit is **Decided by: User** (the same
  instruction as the phase itself, applied specifically to screenshots this
  time — `docs/plans/docs-website-plan.md`'s "Screenshots" section already
  bound this page to its standard, but this phase's Scope above never said
  so in as many words). Each slice above is subject to that standard in
  full — 1440×900 viewport, captured against the seeded demo dataset,
  stored under `docs/website/static/img/screenshots/`, real alt text plus a
  one-line caption — and to its "at least one screenshot or diagram per
  page, not forced onto every page" bar (**Decided by: Agent** for how it
  applies here, since this module's own UI isn't concrete yet beyond the
  engine/report-type split): the Phase 1 engine-introduction slice is
  well served by the provenance-stamping Mermaid diagram already scoped
  above and doesn't need a screenshot of its own, but each Phase 2–6
  report-type subsection should carry at least one screenshot of that
  report type's own rendered output (e.g. a generated Business Requirements
  Document, or the Executive Gap Analysis view with a finding traced back
  to its supporting artefact) once that phase actually ships and there is a
  real screen to capture — a generic commitment for now, not a named
  screen, since none of Phases 2–6 have built their actual UI yet.

**Status:** not started. The first slice (Phase 1's own engine
introduction) depends on Phase 1 shipping; each report-type subsection
depends only on that specific phase, not on every other phase in this
plan — consistent with "Incremental delivery" above. Not a blocker for any
other phase.

## Acceptance criteria (from overview §48, Reporting & Analysis subset)

- Business Requirements Documents can be generated from authoritative
  project data.
- Engineering Specifications can be generated from requirements, design
  and related engineering data.
- Executive Gap Analyses can compare defined current and future states.
- Engineering Change Impact reports can identify direct and transitive
  impacts of an existing change.
- Generated reports record source baseline/version and report/template
  provenance.
- Report templates are versioned.
- Reports do not silently become a second source of truth.
- AI-assisted analysis is distinguishable from approved project information.
