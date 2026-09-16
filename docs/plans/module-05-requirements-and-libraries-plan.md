# Module 5 — Requirements & Requirement Libraries — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout.

**Source:** [future-modules-2026-09-overview.md](future-modules-2026-09-overview.md)
§14–16 ("Module 5 — Requirements & Requirement Libraries", "Organisation
Requirement Libraries", "Project Adoption and Baselining").

**Status:** Proposed. Not started. Fourth in the overview's recommended
build order (§46 Phase 4). Unlike the other nine modules, this one extends
an artefact that **already exists and is heavily built out** (`Requirement`,
`RequirementLink`, `Baseline`, `RequirementReview`, etc. in
`backend/app/models/requirement.py`) — this plan is scoped as an *extension*
to existing functionality, not a new module from scratch, and Phase 0 must
read the existing implementation in detail before proposing anything, not
just the overview.

## Status / Resume Here

0 / 4 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: gap analysis against the existing Requirement implementation | [ ] Not started |
| 1 | Requirement Type ordering/hierarchy semantics | [ ] Not started |
| 2 | Organisation Requirement Sets (versioned, reusable) | [ ] Not started |
| 3 | Project adoption, version comparison, and adoption auditing | [ ] Not started |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase exists, and why it differs from other modules' Phase 0:**
every other module in this roadmap introduces a wholly new artefact.
Requirements do not — `Requirement`, `RequirementStatus`
(`Draft/Reviewed/Approved/Archived`), `Baseline`/`BaselineItem`,
`RequirementReview`, and `RequirementLink`/`RequirementLinkTypeDefinition`
already exist and are in production use. This phase's real job is a **gap
analysis**: what does the overview ask for that isn't already there, versus
what it describes that's already solved (possibly differently than the
overview assumes, since the overview appears to have been written without
necessarily cross-checking the current schema in full).

**Activities:**

1. **Read the full existing requirement subsystem** before proposing
   anything: `backend/app/models/requirement.py`,
   `requirement_link_type.py`, the requirement router(s), and
   `docs/solution-architecture.md`'s requirements section.
2. **Requirement Type gap — already confirmed, not just a question to
   check.** Read directly during this planning pass: `Requirement` has no
   type/hierarchy field at all. `RequirementLevel`
   (`backend/app/models/enums.py:134`) is bindingness — Mandatory/
   Recommended/Optional, explicitly documented as "distinct from
   `RequirementStatus`... not `RequirementLevel` either" in its own
   docstring — and `component_id`/`category_id` are separate classification
   axes (project-defined components/categories, not a Business/Stakeholder/
   Project hierarchy). So §14/11.1's "Requirement Type" (Business
   Requirement / Stakeholder Requirement / Project Requirement, ordered,
   configurable) is **genuinely net-new** — there is no existing enum to
   migrate, unlike this plan's original working assumption. This is good
   news for risk (no migration touching every existing requirement row's
   *meaning*) but means the full definable-type table
   (`RequirementTypeDefinition`, mirroring `RequirementLinkTypeDefinition`'s
   pattern: project- or org-scoped, ordinary rows, `sort_order`,
   enable/disable) is built from scratch in Phase 1, plus a new nullable
   `type_id` column added to `Requirement` (nullable, since existing
   requirements predate the concept and shouldn't be forced to backfill a
   type before this ships).
3. **Confirm Requirement Set is genuinely new**, or whether something
   like it exists under a different name (check for any existing
   "template"/"standard requirements" concept before assuming §15/12
   is 100% net-new work).
4. Resolve remaining open questions below.

**Exit criteria:** a written gap analysis (what exists vs. what's missing)
confirmed with the user, before Phase 1 begins — this phase's output is
different in kind from other modules' Phase 0 (a delta, not a fresh spec).

### Open questions for Phase 0

1. **Requirement Type: project-scoped, org-scoped, or both (with project
   override)?** §14/11.1 says "configurable per project"; §15/12 layers an
   org-level Requirement *Set* concept on top (different thing — a
   reusable requirement collection, not the type taxonomy itself). Confirm
   whether the type taxonomy (Business/Stakeholder/Project, or whatever a
   project configures) is purely project-scoped like `ActionTypeDefinition`
   appears to be, or org-seeded-then-project-customised like the Pain Point
   type pattern recommended in Module 1. Recommend the latter for
   consistency across the roadmap's several "configurable type list"
   artefacts (Pain Point, Decision, Stakeholder/Persona, Requirement) —
   one pattern, reused, rather than each module picking its own variant.
2. **Requirement Set organisation vs. reuse of existing "adoption"-like
   concepts.** Confirm no existing mechanism already partially covers this
   (e.g. does `RequirementLinkTypeDefinition`'s org-scoping, or some
   existing "clone project" feature, already solve part of "reusable
   requirement collections")? If nothing exists, §15/12.2's fields (name,
   description, owner, category/type, status, version, effective date,
   review date, requirements, change history) stand as proposed.
3. **Requirement Set versioning: same versioning mechanism as `Baseline`,
   or new?** `Baseline`/`BaselineItem` already versions a *project's*
   requirements at a point in time. A Requirement Set version (§15/12.3) is
   conceptually similar but org-owned and pre-adoption rather than
   project-owned and post-baseline. Recommend a parallel structure
   (`RequirementSetVersion`, `RequirementSetVersionItem`) rather than
   reusing `Baseline` directly — a `Baseline` is *this project's approved
   snapshot*, semantically different from *an org's published template
   version* — but confirm with user since reusing existing baseline
   machinery outright would be less code if the semantics can be stretched
   to fit.
4. **Diff mechanism for Requirement Set versions.** §15/12.5 wants
   added/removed/modified/retired/applicability-changed reported between
   versions — is this computed on demand (diff two version's item sets at
   query time) or precomputed and stored at publish time? Recommend
   computed on demand initially (simpler, no staleness risk) unless
   performance data later says otherwise.

## Phase 1 — Requirement Type ordering/hierarchy semantics

**Goal:** add `RequirementTypeDefinition` (new table, confirmed net-new by
Phase 0 — no existing enum to migrate) as a project- or org-scoped,
ordered, enable/disable-able definition per §14/11.1, seeded with Business/
Stakeholder/Project defaults, plus a nullable `type_id` FK on `Requirement`.
The configured order controls both the conceptual hierarchy (Business →
Stakeholder → Project) and default report ordering (§14/11.1's closing
line) — so ordering isn't cosmetic, it's load-bearing for later
Traceability-hierarchy configuration (overview §23) and Reporting.

**Why:** without configurable ordering, a project stuck with a fixed
three-tier hierarchy can't represent a two-tier or four-tier requirement
structure some organisations actually use — directly contradicts §2.1/2.2's
"lightweight by default, progressive governance" principle if hard-coded.

## Phase 2 — Organisation Requirement Sets (versioned, reusable)

**Scope** (per Phase 0's resolution; fields §15/12.2, versioning §12.3):
`RequirementSet` (org-owned) + `RequirementSetVersion` (explicit version
per Phase 0 Q3/Q4) + the requirements each version contains. Requirement
Set Manager (Manage) / Approver (Approve/Publish) roles per §15/12.6 — not
requiring Organisation Administrator, per that section's explicit statement.

**Why:** §15/12.1 — organisations with multiple projects sharing regulatory/
safety/environmental requirement collections currently have no way to
maintain one authoritative copy; each project either duplicates the text
(drifts over time) or references it informally (no auditability of which
version a project actually used).

## Phase 3 — Project adoption, version comparison, and adoption auditing

**Scope** (§16, §12.4–12.5): a project targets an *exact* Requirement Set
version (never "latest" implicitly — §15/12.3's explicit requirement); an
org-level view answers "which projects use which version" (§12.4's example
table); version-to-version diffs are surfaced when a project considers
adopting a new version; adoption/version-change requires Project Approver
sign-off (§16), never silent auto-upgrade (§12.5's explicit requirement).

**Why:** §12.4's stated purpose — audit and migration analysis — is only
possible if adoption is an explicit, recorded, approved act rather than an
implicit "this project uses the org's environmental requirements" reference
with no version pinning.

## Acceptance criteria (from overview §48, Requirements & Libraries subset)

- Requirement Types are configurable per project.
- Requirement Types can be ordered.
- Organisation Requirement Sets can be created.
- Requirement Sets are versioned.
- Projects target an explicit Requirement Set version.
- Organisations can see which projects use which versions.
- Requirement Set changes can be compared.
- Project adoption is auditable.
