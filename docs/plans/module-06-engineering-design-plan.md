# Module 6 — Engineering Design — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout. This module hard-depends
on [Module 0](module-00-platform-foundations-plan.md) for its relationship
infrastructure.

**Source:** [future-modules-2026-09-overview.md](future-modules-2026-09-overview.md)
§3's six-line Module 6 entry, now substantially superseded by
[engineering-design-vs-decisions.md](engineering-design-vs-decisions.md)
("the design/decision doc") — a supplementary source the user provided
2026-09-16 specifically to fill in this module, since the main overview
under-specifies it (previously the thinnest module in the whole roadmap;
see the git history of this file for that earlier state). The design/
decision doc's §20 ("Proposed Engineering Design Module") is now this
module's primary field-level spec, in the same role §5–47 play for the
other modules.

**Status:** Proposed. Not started. Grouped with Risk Management in overview
§46 Phase 5 (built after Requirements & Libraries). No longer the thinnest
module in the roadmap — Phase 0 is now much lighter than originally scoped,
since the design/decision doc resolves nearly every open question this
plan previously had to raise from scratch.

## The one real open question this module still carries: should Design be a separate module at all?

The design/decision doc devotes an entire section (§22, "The Important
Caveat") to a genuine architectural fork, the same category of question as
"should Governance and Traceability be one module" (raised and settled
earlier in this roadmap): keep Design as its own artefact, or fold
architectural detail back into Decision Management and skip this module
entirely. §25's closing line states it plainly: *"I would only keep
Engineering Design as a first-class module if the product is intended to
capture this latter engineering definition. If the goal remains primarily
requirements + rationale + traceability, then architectural Decisions may
be enough and the separate module could be unnecessary."*

**Recommendation: keep Design separate**, on the strength of the doc's own
§22 test (a design deserves separation when it has its own hierarchy,
revisions/baselines, substantial engineering attributes, interfaces,
multi-requirement satisfaction, design-to-design dependencies, independent
review/approval, and heavy change-impact participation) — §20's proposed
field list satisfies essentially all ten indicators at once, and Decision
Management's own plan (Module 4) already commits to keeping Decisions
lightweight (choice, rationale, consequences — no hierarchy, no revision
model, no engineering attributes), which would be directly undermined if
architectural definition got pushed back into it once real usage produced
more than a handful of decisions per project (§4's own worked example of
exactly this failure mode: "'Decision' is being used as a generic
container for engineering definition... probably not the right
abstraction"). This is **flagged for explicit user confirmation before
Phase 1**, same as the Governance/Traceability question — not assumed
silently — but the rest of this plan is written assuming that answer,
since building it out is the only way to make the trade-off concrete.

## Status / Resume Here

0 / 8 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: confirm separate-module decision + remaining specifics | [ ] Not started |
| 1 | Data model: Design record, Design Types, hierarchy, module RBAC | [ ] Not started |
| 2 | Design Options (alternatives) linked to Decision | [ ] Not started |
| 3 | Design revisions, reviews, approval, supersession, invalidation, baselines | [ ] Not started |
| 4 | Interfaces (first-class, initially within this module) | [ ] Not started |
| 5 | Engineering Attributes (custom-field reuse) | [ ] Not started |
| 6 | Relationships (Requirement, Decision, Risk, Compliance, Verification, Design) | [ ] Not started |
| 7 | Frontend UI | [ ] Not started |
| 8 | Docs website coverage | [ ] Not started — depends on Phase 7 shipping |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase is now much lighter than originally scoped:** the design/
decision doc resolves what used to be this plan's central problem (what is
"Engineering Design" even supposed to capture) with a specific,
field-level answer (§20, §23's "Recommended Boundary"). What remains is
confirming the separate-module decision above, and a handful of concrete
implementation choices the doc raises but doesn't fully pin down.

**Activities:**

1. **Get explicit user sign-off on keeping Design as its own module** (see
   above) before anything else — this is the one decision genuinely still
   open, and it changes this plan's existence, not just its details.
2. Resolve the open questions below.
3. Confirm scope boundary against CAD/ECAD/source control (§10 of the
   design/decision doc, already explicit and not really in question): this
   module captures *engineering definition and relationships*, never
   replaces specialist tools — `Design.external_artefact_references` points
   at those systems, it doesn't import their content.

**Exit criteria:** user confirms the separate-module decision and the
open-question resolutions below, before Phase 1.

### Open questions for Phase 0

1. **Design revision model: supersession chain, or temporal versioning?**
   §14 of the design/decision doc describes revisions as "Revision 1...
   Revision 2..." with a "superseded-by relationship," reading much closer
   to Decision Management's own supersession pattern (Module 4 Phase 2 —
   each revision is an immutable row, a new one supersedes the old, the
   original stays intact) than to `RequirementVersion`'s temporal
   `valid_from`/`valid_to` model (one identity, continuously revised
   in-place until archived). Recommend mirroring Decision's supersession
   pattern — Design and Decision are explicitly described as parallel
   concepts throughout the doc ("Decision = choice, Design = state," §9),
   so reusing the same revision mechanics for both is more consistent than
   introducing a third versioning shape alongside `RequirementVersion`'s.
2. **Baseline integration: extend the existing `Baseline`/`BaselineItem`,
   or a Design-specific baseline?** §20.8/§14 lists "baseline" as one of
   Design's own fields alongside "revision" and "supersession" — these are
   two distinct concepts (a Design's own revision history vs. a project
   stage baseline that happens to capture a specific Design revision).
   Recommend: extend `Baseline`/`BaselineItem` to reference a Design
   revision the same way it references a `RequirementVersion` today (per
   this plan's original recommendation, still holding) — a project stage's
   baseline should be able to capture "these requirement versions *and*
   these design revisions" as one coherent snapshot, not two separate
   baseline concepts a user has to reconcile.
3. **Interfaces: modelled as a distinct sub-type of Design, or a genuinely
   separate table from day one?** §20.5/§11.3 explicitly says interfaces
   "should initially be a first-class concept within Engineering Design"
   but "may eventually justify promotion to its own module." Recommend:
   `Design` rows with `design_type` = "Interface Design" (one of §20.2's
   configurable types) rather than a wholly separate `Interface` table —
   this is exactly the "don't over-build for a hypothetical future need"
   principle applied here: an interface is structurally just a Design with
   a specific field emphasis (source, destination, protocol, physical/data
   characteristics — all expressible via `engineering_attributes`, per
   Phase 5), so a separate promotion later (if interfaces turn out to need
   their own lifecycle or volume of use) is a normal schema migration, not
   a redesign.
4. **Engineering Attributes: literally the same `custom_fields` JSONB
   mechanism `RequirementVersion` already uses, or a Design-specific
   variant?** Confirmed by reading the code: `RequirementVersion` already
   has a `custom_fields: Mapped[dict[str, Any]]` JSONB column keyed by
   `CustomFieldDefinition` id (`backend/app/models/requirement.py`).
   Recommend reusing `CustomFieldDefinition` directly for Design's own
   engineering attributes (voltage ranges, operating temperature, mass,
   etc. — §20.6's examples) rather than a parallel attribute-definition
   table — the existing mechanism is already generic (definition table +
   JSONB value column), so this should be additive (Design becomes a
   second entity type `CustomFieldDefinition` can target), not a new
   system.
5. **Ownership/approval role.** Does Design need its own named Approve-role
   ("Design Approver"), or a generic configurable approver per the common
   permission model with no fixed name? Recommend a named "Design Approver"
   module-contributed role, consistent with Decision Management's "Decision
   Maker" and other modules' named approval roles — the pattern established
   across this roadmap is specific, named roles per artefact type, not one
   generic "Approver."
6. **Comments/attachments reuse.** Same pattern as every other module —
   confirm Design reuses `ReviewComment`/`CommentFile` via a new
   `ReviewTargetType` member, consistent with the "external artefact
   references" field (§20.1) being a distinct, lighter-weight pointer to
   things like a CAD repository URL, not the same as an uploaded file
   attachment.
7. **Design review question set.** §15 of the design/decision doc proposes
   a specific design-review checklist (are requirements addressed, are
   interfaces defined, are risks treated, are compliance obligations
   addressed, are decisions recorded, are verification methods possible,
   are external artefacts available, has the design been approved).
   Confirm whether this should be a structured checklist recorded per
   review (each item answered explicitly) or freeform review commentary
   with these as prompts/guidance only — the former is more auditable but
   heavier to build; recommend freeform-with-prompts initially, since
   Governance's own review-policy mechanism (Module 8 Phase 3) may
   eventually want to generalise structured review checklists across
   multiple artefact types rather than Design inventing its own.
8. **Invalidation: an overlay marker, or a new lifecycle status? — raised
   directly by the user 2026-09-16.** A Design can become wrong after the
   fact without anyone having revised it yet — a linked Requirement
   changes, the Decision that selected it gets superseded, a Risk newly
   threatens it, or someone simply notices "that won't work because of
   X." This needs to be representable *before* a replacement revision
   exists, which rules out treating it as just another value the normal
   lifecycle status can take (an `Invalidated` status would collide with
   "what stage of review/approval is this revision at," a different axis
   entirely). Recommend mirroring `Requirement.is_completed`'s existing
   overlay-marker pattern (`backend/app/models/requirement.py`) — a
   `Design` revision gets `is_invalidated`/`invalidated_at`/
   `invalidated_by` fields layered on top of its ordinary `status`, exactly
   as completion sits on top of `RequirementStatus.APPROVED` "rather than
   replacing it." This composes correctly with Phase 0 Q1's supersession
   model: an invalidated revision can still later be formally superseded
   by a corrected one (the normal path), or the invalidation can be
   reversed if the concern turns out not to apply (mirroring how a
   completed requirement's marker "may later be reversed... when a
   review/audit occurs") — both stay available, neither is foreclosed by
   the other. See Phase 3 and Phase 6 for the mechanism this drives; see
   also [Module 0's "Related, non-blocking" section](module-00-platform-foundations-plan.md)
   for why this is documented as a roadmap-wide convention, not invented
   fresh here — Risk Management (Module 3) already wants the same thing
   for its own mitigations.
9. **Who can invalidate, and does it need its own role?** Recommend no new
   named role — invalidating is a Manage-level action (Design Owner or
   whoever manages the artefact that triggered it, e.g. a Requirements
   Manager who just changed the requirement underneath a Design), not an
   Approve-level one; approval-level scrutiny belongs to *resolving* the
   invalidation (reviewing and re-approving a corrected revision), not to
   flagging the problem in the first place — flagging early and cheaply is
   the entire point, the same reasoning Pain Points' deliberately broad
   creation permission (Module 1 §6.5) already established for "don't
   gate the ability to raise a problem behind a manager role."

## Phase 1 — Data model: Design record, Design Types, hierarchy, module RBAC

**Scope** (§20.1–20.3, §12): `Design` — `unique_code` (project-scoped,
e.g. `DES-001`, matching the `Requirement`/`Decision`/`RequirementAction`
convention), title, `design_type_id` (FK to `DesignTypeDefinition`),
description, purpose, scope, owner, status, `parent_design_id`
(self-referential, nullable — design hierarchy, explicitly distinct from
project hierarchy per §12: "the two can be related but should not be
forced to be identical"), assumptions, constraints, `external_artefact_references`
(structured references to CAD/ECAD/source-control locations, per §10 —
plain text/URL fields, not a new attachment mechanism), creator/audit
columns, `is_archived` per the standard soft-delete convention.

`DesignTypeDefinition`: project- or org-scoped (per the roadmap's
recurring configurable-type-list pattern, Module 0's "Related, non-blocking"
note), seeded with §20.2's defaults (System/Hardware/Software Architecture,
Mechanical/Electrical/Communications/Network/Data/Interface/Deployment/
Operational/Component Design).

**Why:** §4 of the design/decision doc — without a first-class Design
record, engineering definition either gets crammed into Decision records
(which the doc shows breaks down once a project has more than a handful of
architectural choices) or lives only in external tools with no
representation in ReqTrackManager at all, leaving "what does the system
actually consist of" unanswerable from the product's own data.

**Roles:** Design Owner (Manage), Design Approver (Approve, per Q5), project
members (View + Propose), per the common permission model.

## Phase 2 — Design Options (alternatives) linked to Decision

**Scope** (§13, §20.4): a Design may record alternative approaches (e.g.
"Communications Design: Options A. Ethernet, B. Wi-Fi, C. CAN") before one
is selected; the Decision that makes the selection links to the option
chosen, and the resulting Design reflects only the selected approach
(§13's worked example: after the decision, `Communications Design └──
Ethernet`). This is a `DesignOption` sub-record scoped to one `Design`,
distinct from Decision Management's own simpler "options considered" text
field (Module 4 Phase 1) — per this doc's own framing, substantial
structured alternatives belong here, on the Design side, once a Design
exists; Decision's own options field stays lightweight text for decisions
that don't have an associated Design at all (§6 — "Decisions Can Exist
Without Designs").

**Why:** §13's own point — "the alternatives are inputs to the decision,
while the resulting Design represents the selected engineering solution."
Keeping alternatives structurally attached to the Design being decided
about (not buried inside the Decision record) is what lets a later change
("we're revisiting the communications choice") find the prior options
considered without archaeology through Decision text.

**Cross-reference:** this resolves Module 4 (Decision Management)'s Phase
0 Q4, previously an open question about whether "Options Considered"
needed to be a repeatable structured sub-record — now answered: Decision
keeps a simple text field; structured, evaluated alternatives live here,
on Design, once this module exists.

## Phase 3 — Design revisions, reviews, approval, supersession, invalidation, baselines

**Scope** (§14, §15, §20.8, per Phase 0 Q1/Q2/Q8/Q9's resolution): revision
history via a Decision-style supersession chain (immutable revisions, a
new one supersedes the prior, `superseded_by` relationship, original stays
intact per §14's explicit "the original remains intact" framing carried
over from Decision Management, and — per Q1 — directly, individually
queryable: every past revision of a Design remains a real, addressable row
with its own `unique_code`/revision number, not just an implicit "current
value" with a change log, so "what did this Design look like in March"
is a normal query, not archaeology); design review (structured or freeform
per Q7); approval workflow (Design Approver role from Phase 1); extension
of `Baseline`/`BaselineItem` to capture a specific Design revision
alongside `RequirementVersion` snapshots (per Q2); and **invalidation** —
per Q8/Q9's resolution, an `is_invalidated`/`invalidated_at`/
`invalidated_by` overlay on a specific Design revision, set by a Manage-
level action (no new role, per Q9), reversible, and orthogonal to both
`status` (still whatever it was — invalidation doesn't retroactively
un-approve something that really was approved) and to supersession (an
invalidated revision can still later be superseded by a corrected one,
the normal path to actually fixing the problem — invalidation only flags
that it's now known to be wrong, it doesn't by itself produce the fix).

**Why:** §14 — "the Decision does not need to be rewritten every time
implementation detail changes... the design revision captures the
engineering evolution." Without version history, every minor engineering
change (connector type, PHY, isolation device — §5's own examples) would
either force a spurious new Decision record, or leave no trace of the
design's evolution at all.

**Why invalidation specifically:** this is the concrete mechanism behind
the user's own scenario (2026-09-16) — "designs that are developed and
then someone says oh that won't work because of [x]." A Design can be
correct when approved and wrong later, purely because something it
depends on changed underneath it (a Requirement's threshold moved, the
Decision that selected this approach got superseded, a newly-identified
Risk makes it unworkable) — without this, that fact either lives only in
a comment thread (unstructured, easy to miss) or forces an immediate,
possibly premature new revision before anyone has actually worked out the
fix. An explicit, structured "this is now known to be invalid, here's why"
state — visible on the Design itself and feeding Traceability (Module 7)
as a real coverage gap and Reporting's Engineering Change Impact analysis
(Module 10 §47.6, which already talks about "baselines potentially
invalidated") — is what makes that visible and actionable rather than
buried.

## Phase 4 — Interfaces (first-class, initially within this module)

**Scope** (§20.5, §11.3, per Phase 0 Q3's resolution): interfaces modelled
as `Design` rows with an "Interface Design" `design_type`, carrying source,
destination, interface type, protocol, physical/data characteristics, and
constraints via the engineering-attributes mechanism (Phase 5). Explicitly
scoped as "initially" first-class within this module, not a separate
module — §20.5's own note that promotion to a dedicated module may be
justified later "if it becomes sufficiently substantial."

**Why:** §11.3's own reasoning — "interfaces... often become some of the
most valuable traceability objects in an engineering system." Interfaces
are frequently where requirement satisfaction, design dependency, and
verification all concentrate (e.g. an Ethernet interface satisfying a
communications requirement, depending on a PHY component design, and
carrying its own verification method) — modelling them as ordinary Design
rows means they get the same relationship/traceability/revision machinery
as everything else in this module for free, rather than needing a second
special-cased system this early.

## Phase 5 — Engineering Attributes (custom-field reuse)

**Scope** (§20.6, §11.4, per Phase 0 Q4's resolution): extend
`CustomFieldDefinition` (already used by `RequirementVersion.custom_fields`)
to also target `Design`, so a project can define structured engineering
properties (nominal voltage, input range, operating temperature, mass,
network speed, ingress protection — §20.6's own examples) the same way it
already defines custom fields for requirements, rather than inventing a
second, parallel attribute-definition mechanism.

**Why:** §11.4 — "these may be represented using the existing custom-field
mechanism rather than inventing a completely separate arbitrary attribute
system" is the design/decision doc's own explicit recommendation, and it
matches this codebase's existing precedent exactly (confirmed by reading
`backend/app/models/requirement.py`'s `RequirementVersion.custom_fields`
field and its accompanying `CustomFieldDefinition` model).

## Phase 6 — Relationships (Requirement, Decision, Risk, Compliance, Verification, Design)

**Scope** (§20.7, §16–19, §21), using Module 0's relationship
infrastructure:

- Design ↔ Requirement: `Implements`, `Satisfies`, `Derived from` (§16 —
  "Requirement → satisfied/implemented by → Design" is one of the doc's
  most heavily emphasised relationships, alongside Decision and
  Verification, in its four-artefact table: Requirement=what must be true,
  Decision=why this approach, Design=what solution, Verification=how
  proven).
- Design ↔ Decision: `Selected by`, `Constrained by` (§8, §9 — a Decision
  can select, constrain, or influence a Design; this is the "soft,
  frequently-used" relationship already anticipated in the index's
  dependency graph as `design-to-decision`).
- Design ↔ Risk: `Mitigates` (§17 — "Risk → mitigated by → Design"; this
  is in addition to Module 3's existing Risk → Requirement relationship,
  not a replacement for it — a risk can be mitigated at the requirement
  level, the design level, or both).
- Design ↔ Compliance: `Satisfies Compliance Requirement` (§18 — reserved
  until Module 9's Compliance Integration work, though Compliance itself
  already exists and could in principle be linked directly once this
  module's relationship types are declared).
- Design ↔ Design: `Refines`, `Depends on`, `Interfaces with`, `Supersedes`
  (§8, §19 — design-to-design relationships, including the supersession
  chain from Phase 3 and genuine cross-design dependencies, e.g. a
  Processor Design interfacing with a Power Design).
- Design ↔ Verification: `Verified by`, `Validated by` (§16, §21 — via the
  existing `RequirementAction`/`RequirementActionLink`, per the index's
  confirmed "Verification Action" finding, since §21's model diagram shows
  Verification hanging off Design directly, not just off Requirement).
  *Generalising `RequirementActionLink` to target `Design` at all is
  [Module 0](module-00-platform-foundations-plan.md)'s job — folded into
  its own relationship-model fork alongside `RequirementLink`'s — not
  something this phase resolves independently; this phase only consumes
  it once Module 0 has it.*
- Design ↔ (Requirement / Decision / Risk / Design): `Invalidated by` —
  the structured link behind Phase 3's invalidation mechanism (Phase 0
  Q8/Q9). Recorded pointing at whichever specific artefact actually caused
  the problem (the Requirement whose threshold changed, the Decision that
  got superseded, the Risk that newly applies, or another Design this one
  depended on) rather than only a free-text reason — "won't work because
  of X" should mean a real relationship to X, not prose that happens to
  mention it, consistent with this whole roadmap's preference for
  structured relationships over restating the same fact in text. Setting
  this relationship and setting `is_invalidated` (Phase 3) happen together,
  as one action.

**Detecting when this might apply** (informing, not gating, invalidation):
when something Design already links to changes — a linked Requirement
gets a new approved version, a linked Decision is superseded, a linked
Risk's rating changes — the owner of the Design should be notified that a
review may be warranted, using whatever generic "what links to this
artefact" query Module 0's relationship model already provides (per its
own Phase 1 scope) plus the existing, already-generic `Notification`
model (confirmed enum-extensible, no structural change needed). This is
deliberately a *notification*, not an automatic invalidation — the system
flags "something changed that this Design depends on," a human decides
whether that actually breaks it and marks it invalidated with a reason if
so, the same "detect and notify, human decides and acts" division of
labour `RequirementReview`'s own review-due mechanism already uses.

**Why:** §19's own point — a change-impact analysis that can traverse
"Processor Design → selected by Decision, satisfies Requirements,
interfaces with Power Design, interfaces with Software Architecture,
affects Compliance, mitigates Risk, verified by Verification" in one
connected graph "is much more useful than simply knowing that several
Decisions mention the processor" — this is the concrete payoff for having
built Design as its own artefact at all, and it's also exactly the kind of
traversal Module 10's Engineering Change Impact report (§47.6) needs.

**MCP tools.** The instruction to give every not-yet-built module plan this
same explicit MCP-tools and docs-website treatment is **Decided by: User**
(2026-09-21); which phase to amend and the specific candidate names below
are **Decided by: Agent** — Phase 6 is chosen because it's the last
backend-building phase in this plan's own sequence, by which point the full
Design CRUD/revision/relationship surface from Phases 1–6 exists (this plan
has no single consolidated "Backend API" phase the way Module 4's plan
does, so this addendum covers the module's REST surface as a whole rather
than only Phase 6's own relationship endpoints). Once these endpoints
exist, declare narrow, read-only-only `McpToolDefinition` entries per
[docs/modules.md](../modules.md) §6, following the Compliance and Decision
Management (`module-04-decision-management-plan.md`) precedent. Concrete
candidates: "list designs", "get design" (including its current revision
and hierarchy position), "list design relationships". Excluded,
deliberately: design approval (Phase 3's Design Approver role) and
invalidating a Design revision (Phase 3/Phase 6's "Invalidated by"
mechanism) — both are exactly the kind of accountable, finalizing/flagging
governance actions Compliance's own `module.py` has repeatedly kept off the
MCP tool surface, so both routes are marked
`openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA`
(`backend/app/modules/registry.py`) at build time, mechanically excluding
them from the manifest rather than relying on this list alone.

## Phase 7 — Frontend UI

List/detail/create UI with a real hierarchy tree view (per §12's explicit
hierarchy requirement), a design-options comparison view (Phase 2), a
revision/supersession history view mirroring Decision Management's own
approach, and relationship/traceability displays consistent with the
other modules. Enum/status/design-type values render through label maps
from day one. Playwright e2e + Storybook coverage per standing testing
requirements.

## Phase 8 — Docs website coverage

Adding this as its own explicit, tracked phase (rather than leaving it
implicit) is **Decided by: User** (2026-09-21, the same instruction as the
MCP-tools addition above, applied to every not-yet-built module plan); the
specific scope below is **Decided by: Agent**.

**Goal:** add Engineering Design's user-facing surface to `docs/website/`
(the published docs site, `docs/plans/docs-website-plan.md`) — modeled
closely on `module-04-decision-management-plan.md`'s own "Phase 6 — Docs
website coverage", adapted to this module's own content rather than
copied.

**Why this is its own tracked phase, not folded silently into Phase 7:**
`CLAUDE.md`'s "Docs Website Maintenance" rule already requires this check
on every change with a user-facing surface, in the same change rather than
deferred — so in the ordinary case this would just be part of Phase 7's
own work. It is broken out explicitly here, mirroring Decision
Management's own Phase 6 reasoning, because this module's user-facing
surface is unusually broad for one phase (design hierarchy, options,
revisions/supersession, invalidation, interfaces, engineering attributes,
and five relationship groups all land in the same Phase 7 UI at once) — a
dedicated, checklist-visible phase makes it harder for the docs-site update
to be under-scoped or missed.

**Scope:**

- A new docs-site page (or section, matching whatever grouping the site
  already uses for other project-scoped modules, e.g. Compliance and
  Decision Management) covering: what a Design record is and when to use
  one, including the explicit boundary that it references CAD/ECAD/source
  control rather than replacing them (§10); the design hierarchy
  (parent/child, distinct from project hierarchy per §12) as a validated
  Mermaid diagram; Design Options and how one is selected via a linked
  Decision (Phase 2, §13); the revision/supersession model (mirroring
  Decision Management's own, per Phase 0 Q1) as a validated Mermaid
  lifecycle diagram, including invalidation as an overlay marker
  independent of both status and supersession (Phase 3, Phase 0 Q8/Q9);
  Interfaces as an "Interface Design" type rather than a separate concept
  (Phase 4); Engineering Attributes via the shared custom-field mechanism
  (Phase 5); and the module's relationship groups to Requirement, Decision,
  Risk, Compliance, Verification, and other Designs (Phase 6), with a short
  Mermaid diagram showing how a Design sits relative to those other
  artefacts — reusing the doc's own four-artefact framing (Requirement =
  what must be true, Decision = why this approach, Design = what solution,
  Verification = how proven).
- Update the site's module/feature index or nav to include Engineering
  Design once it ships.
- Cross-link from the Decision Management documentation wherever it already
  discusses Design ↔ Decision relationships or Decision's own "options
  considered" field, since Phase 2 of this module directly resolves that
  plan's own Phase 0 Q4.
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
  screens for this module's own page — **Decided by: Agent**: the Design
  hierarchy/list view, a Design detail page showing its revision history
  and interfaces, and the Design Option selection UI tied to a Decision.

**Status:** not started. Depends on Phase 7 (frontend) actually shipping —
there is no real user-facing workflow to document accurately before then,
the same reasoning Decision Management's own Phase 6 and Compliance's
docs-site page both used.

## Acceptance criteria

Drafted from the design/decision doc's §20 spec (the overview's own §48
has no Engineering Design subsection at all — this list is this plan's
own synthesis, not lifted from an authoritative acceptance-criteria
section the way every other module's is, and should be confirmed with the
user during Phase 0 rather than treated as already agreed):

- Designs can be created with a configurable design type, hierarchy
  (parent/child), and the fields listed in Phase 1.
- Design hierarchy is distinct from, and does not have to mirror, project
  hierarchy.
- A Design can record alternative options, each linkable to the Decision
  that selects one.
- Designs are revision-controlled; an approved revision is never edited
  in place, only superseded by a new one; every past revision remains
  individually addressable, not just implied by a change log.
- A specific Design revision can be marked invalidated, with a required
  reason and a structured link to the Requirement, Decision, Risk, or
  other Design that caused it — independently of, and without requiring,
  a replacement revision existing yet.
- Designs can be reviewed and approved independently of Decisions or
  Requirements.
- A project stage baseline can capture specific Design revisions alongside
  requirement versions.
- Interfaces are representable as Designs without a separate subsystem.
- Designs support structured engineering attributes via the existing
  custom-field mechanism.
- Designs participate in the common relationship model: to Requirements,
  Decisions, Risks, Compliance, other Designs, and Verification.
- Engineering Design does not attempt to replace CAD/ECAD/source-control
  tools — it references them, it does not import their content.
