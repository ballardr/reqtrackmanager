# Module 6 — Engineering Design — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout. This module hard-depends
on [Module 0](completed/module-00-platform-foundations-plan.md) for its relationship
infrastructure (built). Soft dependencies: Decision Management (Module 4) and
[Risk Management](completed/module-03-risk-management-plan.md), both shipped;
[Module 18](module-18-system-architecture-plan.md) (a Design *describes* an element or
connection, and its polymorphic baseline is the storage Phase 3 uses);
[Module 2](module-02-stakeholders-and-personas-plan.md) Phase 3d (the generic custom-field
kinds Phase 5 reuses); [Module 7](module-07-traceability-and-governance-plan.md) (review
policies and baseline check providers).

**Source:** [future-modules-2026-09-overview.md](completed/future-modules-2026-09-overview.md)
§3's six-line Module 6 entry, now substantially superseded by
[engineering-design-vs-decisions.md](engineering-design-vs-decisions.md)
("the design/decision doc") — a supplementary source the user provided
2026-09-16 specifically to fill in this module, since the main overview
under-specifies it (previously the thinnest module in the whole roadmap;
see the git history of this file for that earlier state). The design/
decision doc's §20 ("Proposed Engineering Design Module") is now this
module's primary field-level spec, in the same role §5–47 play for the
other modules.

**Status:** Proposed. Not started. Every hard dependency is built, Decision Management and Risk Management have shipped, and the only soft dependency still open is Module 18's baseline storage (Phase 3, Q2); nothing requires this module to follow Requirements & Libraries. Phase 0 is lighter than originally scoped, since the design/decision doc resolves nearly every open question, but Q1 to Q6 and Q10 to Q13 are recommendations that need the User's sign-off before Phase 1.

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

0 / 13 phases complete. Phase 0 is next.

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
| 9 | Analysis widgets for Reporting: Executive Gap Analysis and Engineering Change Impact (moved here from Module 10 Phase 11b, 2026-11-04) | [ ] Not started — depends on Phases 3 and 6 |
| 10 | System Architecture integration: Designs that describe elements and connections, in both directions | [ ] Not started — depends on Phases 4 and 6 and on Module 18's records |
| 11 | Security review: access, approval gate, visibility and import (identify, verify, remediate) | [ ] Not started — depends on Phases 3 to 7 and 10 |
| 12 | Seeds, Storybook and Playwright completeness, performance re-run, close-out | [ ] Not started — last; Phase 8 (docs website) is built after Phase 10 so it documents the integration |

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
3. Confirm the scope boundary against CAD/ECAD/source control (§10 of the
   design/decision doc): this module captures *engineering definition and
   relationships*, never replaces specialist tools. How files and external
   artefacts attach to a Design is Q13.

**Exit criteria:** user confirms the separate-module decision and the
open-question resolutions below, before Phase 1.

### Open questions for Phase 0

1. **Design identity and revisions: one row per revision, or one Design with revision rows?** §14 describes "Revision 1... Revision 2..." with a superseded-by relationship, which reads like Decision Management's pattern: two separate rows, a `dedicated_endpoint` `Supersedes` link, and the old row flipping to Superseded when the new one is approved. That suits a Decision, a point-in-time event. A Design is a persistent thing other records point at, so a row per revision would give every revision a new `unique_code` and force the hierarchy parent, tags, placements, links (a requirement's "satisfied by", a Module 18 `Describes`), comments and search entry to be re-created or re-pointed on each one. Recommend **one Design with a stable `DES-nnn` code, hierarchy position, links, tags, placements and comments, whose content lives in immutable `DesignRevision` rows** (revision number, addressed `DES-001 r2`), each individually addressable and approved as a unit. An approved revision is never edited; a change starts a new draft revision copied from it. This is the identity-plus-version-rows shape `Requirement` already uses, with explicit approval per revision instead of continuous revision, so it is not a third shape. The Decision-style `Supersedes` link stays for one Design replacing a different Design. The first draft of this plan recommended mirroring Decision; this changes that recommendation.
2. **Baseline integration: Design-specific baseline, or the shared `Baseline`/`BaselineItem`?** §20.8/§14 lists "baseline" beside "revision" and "supersession": a Design's own revision history and a project stage baseline that captures a specific revision are different things. Recommend the shared baseline, so a stage baseline is one coherent snapshot of requirement versions, design revisions and architecture. [Module 18](module-18-system-architecture-plan.md) Phases 12 and 13 make `BaselineItem` polymorphic (`item_type` validated against the artefact-type registry, `item_id`, a JSON `snapshot`, nullable requirement columns), add `Baseline.kind` (stage or manual) and a generic `ModuleDefinition` snapshot provider called when a stage is locked and from a manual action (**Decided by: User**, Module 18 Phase 0). The generalisation is core and does not depend on Module 18 being enabled for any organisation or project, so Design baselines work with System Architecture off. This module therefore makes **no core baseline change of its own**: it registers a snapshot provider that serialises the stage's approved Design revisions (the revision id and content, never a Restricted-classified column). If this module is built first, the core part of Module 18's Phase 12 is built then, once.
3. **Interfaces: a Design Type, a separate table, or a description of a Module 18 Connection?** Module 18 now has first-class Connections (`CON-nnn`: type, protocol, direction, ports, requirement links), and the User decided that a Design *describes* a connection rather than restating source, destination and protocol (**Decided by: User**, Module 18 Q2). Recommend Interface Design stays a seeded Design Type (no separate table, since an interface Design has the same revisions, review and approval as any other), linked to its Connection with the `Describes` link (Phase 4). Its attributes carry only what a Connection does not (signal levels, data rate, connector, tolerances). With System Architecture disabled the Design still works: its endpoints are written in the description and in `Interfaces with` links to the two Designs it joins. Promotion to its own module later stays a normal migration.
4. **Engineering Attributes: reuse the custom-field mechanism, given that its kind is a closed enum.** `CustomFieldDefinition.entity_kind` is a closed core enum (`requirement`, `change_request`) and definitions are project-scoped only (`backend/app/models/custom_field.py`). Adding `design` to the enum is the per-module hand-edit of a core file the module boundary forbids. [Module 2](module-02-stakeholders-and-personas-plan.md) Phase 3d already plans the correct generalisation: `entity_kind` as a plain value validated against a registry-merged set, an organisation tier for definitions, and values in a `custom_fields` JSONB column on the record's version row. Recommend this module consumes that work and registers the kind `design`, and builds the generalisation itself, once, if it lands first. Values live on `DesignRevision.custom_fields`, so an attribute change is part of the revision's history (Q1). Whether project additions fall back to the nearest ancestor's is recorded in `docs/decisions.md` by whichever module lands first (Module 2's design states the Action Types rule).
5. **Ownership and approval.** Approval authority is a fine-grained permission atom, not a fixed role: Decision Management binds `(decision, approve_baseline, subtype=<decision type>)` so each Decision Type names its approvers, with a module-contributed role (`ModuleRoleDefinition.permissions`) as the default holder. Recommend the same for Design: a named "Design Approver" role as the default holder of `(design, approve_baseline, subtype=<design type>)`, bindable per Design Type, with "Design Owner" (Manage) and project members (View + Propose) as before. Owner and approver are principals, so a user or a group can hold either, with effective group membership as `services/rbac.py` resolves it. Approval and invalidation use the generalised AI-approval gate (Phase 6), and [Module 11](module-11-acting-on-behalf-of-plan.md) names Design approval as an action it extends to.
6. **Comments.** The `ReviewComment`/`ReviewTargetType` route this question first assumed is not the pattern in use. Two mechanisms exist: the module-local `AttachmentKit` (`services/module_attachments.py`: comments with files, as Decision Management uses) and the generic `ModuleDefinition.record_comments` provider (central tables, comments and optional canvas pins, no files; Module 18's comment layer). Recommend `AttachmentKit`, because design review routinely needs evidence files on comments and Designs have no canvas to pin to. Record-level files and external artefacts are Q13. Confirm in Phase 0.
7. **Design review question set.** §15 of the design/decision doc proposes
   a specific design-review checklist (are requirements addressed, are
   interfaces defined, are risks treated, are compliance obligations
   addressed, are decisions recorded, are verification methods possible,
   are external artefacts available, has the design been approved).
   Confirm whether this should be a structured checklist recorded per
   review (each item answered explicitly) or freeform review commentary
   with these as prompts/guidance only — the former is more auditable but
   heavier to build; recommend freeform-with-prompts initially, since
   Governance's own review-policy mechanism ([Traceability & Governance](module-07-traceability-and-governance-plan.md) Phase 4) may
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
   also [Module 0's "Related, non-blocking" section](completed/module-00-platform-foundations-plan.md)
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

10. **Can the organisation own a Design?** A reusable design (a standard power supply) shared across projects is plausible. Recommend project-owned only to begin, with the reason recorded in `docs/decisions.md`: reuse across projects is served today by Module 18's organisation elements and cross-project links, while an organisation-owned Design needs the sharing and visibility machinery Module 18 spent a whole phase on (collections, grants, the visibility resolver). That mechanism can be extended to Designs later, so this is a deferral with a stated reason, not a closed door. Confirm in Phase 0.
11. **Should Executive Gap Analysis be split?** It needs Design: requirements §47.5 lists "design maturity gaps" among its dimensions, beside requirement coverage, compliance, risk and open Decisions, and Module 10 deferred it until Engineering Design, Verification/Validation and Baselines exist (**Decided by: User**, 2026-10-28). Only its Context & Strategy dimensions (current against Future State, Pain Points, Strategies) read nothing from Design. Recommend keeping it here as decided; building those dimensions first and adding the design ones in this module is an option only if the User wants an early version. Confirm in Phase 0.
12. **Are Design Options link targets?** Recommend inline child records of the Design (Phase 2), not an artefact type: the Decision links to the Design and the Design records the selected option. The alternative gives each option a `DOP-nnn` code and every registration in the standing checklist. The original acceptance criterion ("each linkable to the Decision") is read as "selected through the Decision". Confirm in Phase 0.

13. **Files and external artefacts: what is stored, what is pointed at, and what is pulled in?** Existing file handling: a `FileAsset` is an immutable blob (no versions, no content hash) in the pluggable storage backend, bound by the 50 MB `max_upload_bytes` limit, the organisation's storage quota and the uploads switch, held in memory while it uploads, and carried in bundles through `export_file_links`/`import_file_links`; `FileAsset.confidential` keeps a file out of reports. CAD, ECAD and simulation files are often larger than that, change constantly, and are authoritative in their own tool, so storing every one here would make a stale second copy. Recommend three tiers, all on the **revision** (so a revision pins what it was designed against):
    1. **Attached files** (`AttachmentKit` record-level files): exported renderings and evidence, such as a PDF or PNG of a schematic, a STEP or Gerber snapshot, a datasheet or a simulation report. A content hash is stored on the attachment row when it is attached, so an approved revision's evidence is verifiable. Files of an approved revision are frozen (no add or remove), because an approved revision is never edited; files on comments are not part of the revision and stay open.
    2. **External references** (`DesignExternalReference` child rows, replacing the single `external_artefact_references` field on the identity): each names an **external system**, an **identifier** in it, an optional **location**, a label and the **pinned version** in that system (a commit, tag, release or revision letter). The identifier is the primary key of the reference and a location is optional, so a PLM item or part number, an ALM issue, a drawing number or a document number is a complete reference even when the system has no URL a browser can open. The external systems are a `TypeVocabulary` (`services/type_vocabulary.py`: organisation list, per-project add, hide and restore, nested fallback) with a kind (CAD, ECAD, PLM, ALM, source control, simulation, document) and an optional **URL template** (`https://plm.example.com/item/{id}`) that turns an identifier into a link, so someone linking to PLM enters the part number once and the link is built. A free location (a pasted URL) is also allowed. Locations and templates are `http` or `https` only, with no embedded credentials, validated on write; a template is edited by organisation and project administrators only. All of this is plain data: never fetched by the server, rendered as links that open without the referrer, and exported, bundled and reported as data. The pin is what makes "this revision matches schematic rev C" checkable by a person.
    3. **Pulled in from the tool** (a connector that reads a repository or a CAD vault, resolves a reference, checks the pin is current, or imports a rendering): **not built in the first version**. The reason is a stated one, not a size choice: a server that fetches a user-supplied location needs an allow-list against server-side request forgery, stored credentials in the secrets mechanism, and an entry in the vendor management register, each of which the SOC 2 policies govern. The reference model leaves room for it: a resolver would be a generic extension point on `ModuleDefinition`, keyed by the external system's kind, reading the system and identifier already stored, so adding a PLM, Git or a CAD vault connector later needs no migration of existing references and touches no core file.
    Confirm in Phase 0, in particular whether tier 3 should come earlier and for which tool first.

## Phase 1 — Data model: Design record, Design Types, hierarchy, module RBAC

**Scope** (§20.1–20.3, §12, Phase 0 Q1): `Design`, the stable identity — `unique_code` (`DES-nnn`, below), `design_type_id`, `parent_design_id` (self-referential, nullable — design hierarchy, explicitly distinct from project hierarchy per §12: "the two can be related but should not be forced to be identical"), owner (a principal: user or group), creator and audit columns, `is_archived` per the soft-delete convention. `DesignRevision` holds the content (Phase 3 owns its lifecycle): title, description, purpose, scope, assumptions, constraints, status, revision number and `custom_fields` (Phase 5). Both carry the optimistic version counter other modules' records carry.

**Files and external references** (Phase 0 Q13, §10): a revision has `DesignExternalReference` child rows (external system from the organisation's vocabulary with its optional URL template, identifier, optional location, label, pinned version; `http`/`https` only, no embedded credentials) and record-level files through `AttachmentKit` (uploads through `services.files.upload_file`, so the uploads switch, size limit and storage quota apply, with a content hash recorded on the attachment row). Both are in the revision's bundle rows (files through `export_file_links`/`import_file_links`), in the report fields, and in the list export as data (a location cell is spreadsheet-safe). A reference's system, identifier and label are searchable and filterable on the list, so a Design is found from its PLM item or part number; a location is not searchable. The vocabulary is defined once and is available to any other module that later wants external references, which would reuse it, not copy it.

**Design Types** are a `TypeVocabulary` (`services/type_vocabulary.py`, as Persona, Stakeholder and Risk types): an organisation base list plus per-project rename, reorder and add, with **hide and restore of an organisation default** (`ProjectDefinitionSuppression`; hidden defaults travel in the project bundle). Seeded with §20.2's defaults (System/Hardware/Software Architecture, Mechanical/Electrical/Communications/Network/Data/Interface/Deployment/Operational/Component Design). For nested projects, Design Types opt in to ancestor fallback (`inherit_from_ancestors=True`; **Decided by: Agent**, the Action Types and Decision Types rule, to be recorded in `docs/decisions.md` during implementation), and any automatic seeding runs for a root project only.

**Code.** `DES-nnn` from `services.sequences.generate_unique_code(db, project, "design", "DES")` on the Design identity, so every revision shares it and is addressed `DES-001 r2`; the summary label is `"DES-001 title"`.

**Registrations in this phase** (a registry test fails otherwise): the artefact type `design`, which is the string Module 2's reserved "Uses Design" relationship and Module 4's reserved Decision-to-Design links already name, so those go live when the summary provider registers (verify each, and update the docs-website rows that call them reserved); `artefact_summary_providers`, `artefact_type_labels`, `search_providers`, the `RecordTableProvider` with `count`, project and organisation bundle hooks (`no_org_bundle` with its reason while Designs are project-owned, Q10) with template classification, the scaling probe and perf generator, `activity_kinds`, and the frontend registrations in the standing checklist.

**Lifecycle.** A revision follows a server-defined transition map (the pattern Module 18's `transitions.py` set) with an approval gate, so **Save and activate does not apply**; add the row to the review table in `docs/decisions.md`'s "Phase 16: one People page and Save and activate" entry.

**Why:** §4 of the design/decision doc — without a first-class Design record, engineering definition either gets crammed into Decision records (which the doc shows breaks down once a project has more than a handful of architectural choices) or lives only in external tools with no representation in ReqTrackManager at all, leaving "what does the system actually consist of" unanswerable from the product's own data.

**Roles:** Design Owner (Manage), Design Approver (Approve, per Q5) and project members (View + Propose), with owner and approver open to groups.

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

**Options are inline child records of the Design.** A `DesignOption` belongs to the Design identity, not to a revision, so the alternatives survive revisions. It records its evaluation and outcome and is not an artefact type of its own: the Decision links to the Design, and the Design records which option was selected. Making each option a link target would make it an artefact type needing a `DOP-nnn` code and every registration in the standing checklist, so that is a Phase 0 confirmation (Q12).

**Cross-reference:** this resolves Module 4 (Decision Management)'s Phase
0 Q4, previously an open question about whether "Options Considered"
needed to be a repeatable structured sub-record — now answered: Decision
keeps a simple text field; structured, evaluated alternatives live here,
on Design, once this module exists.

## Phase 3 — Design revisions, reviews, approval, supersession, invalidation, baselines

**Scope** (§14, §15, §20.8, per Phase 0 Q1/Q2/Q8/Q9's resolution): **revisions** — a `DesignRevision` is immutable once approved; a change starts a new draft revision copied from the current one, and approving it marks its predecessor superseded (the old revision stays intact, per §14's "the original remains intact"). Every revision is a real, individually addressable row (`DES-001 r2`, with its own page and link target), so "what did this Design look like in March" is a normal query, not archaeology. **Design review** (structured or freeform per Q7, through Module 7's review policies once built); **approval** (Design Approver role, Phase 1); **baselines** through Module 18's snapshot provider (Q2), so a stage baseline captures the approved revision of each Design alongside requirement versions; and **invalidation** — an `is_invalidated`/`invalidated_at`/`invalidated_by` overlay on a specific revision, set by a Manage-level action (no new role, per Q9), reversible, and orthogonal to both `status` (still whatever it was — invalidation doesn't retroactively un-approve something that really was approved) and to supersession (an invalidated revision can still later be superseded by a corrected one, the normal path to fixing the problem — invalidation only flags that it's now known to be wrong, it doesn't by itself produce the fix). `invalidated_at` is a past instant, stored in UTC. Once a revision is approved its attached files and external references are frozen with the rest of its content (comments and their files stay open), and the baseline snapshot records each file's id and content hash and each reference's pinned version, so a baseline shows what the design rested on.

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

## Phase 4 — Interfaces (a Design Type that describes a Connection)

**Scope** (§20.5, §11.3, per Phase 0 Q3's resolution): "Interface Design" is a seeded Design Type, not a separate table. It links to the System Architecture Connection it describes with the `Describes` link, and to the Designs it joins with `Interfaces with` (Phase 6). Its engineering attributes (Phase 5) hold what a Connection does not: signal levels, data rate, connector, tolerances. Source, destination and protocol are not restated: they are read from the described Connection when System Architecture is enabled, and written in the description when it is not. Scoped as "initially" part of this module, per §20.5's note that promotion to a dedicated module may be justified later "if it becomes sufficiently substantial."

**Why:** §11.3's own reasoning — "interfaces... often become some of the most valuable traceability objects in an engineering system." Interfaces are where requirement satisfaction, design dependency and verification concentrate (an Ethernet interface satisfying a communications requirement, depending on a PHY component design, carrying its own verification method), so modelling them as ordinary Designs gives them the same relationship, traceability and revision machinery as everything else here. Describing the Connection, not copying it, keeps one source of truth for the endpoints and protocol.

## Phase 5 — Engineering Attributes (custom-field reuse)

**Scope** (§20.6, §11.4, per Phase 0 Q4's resolution): register the kind `design` with the generic custom-field mechanism (registry-validated `entity_kind`, organisation and project definitions), with values in `DesignRevision.custom_fields`. A project defines structured engineering properties (nominal voltage, input range, operating temperature, mass, network speed, ingress protection — §20.6's examples) the way it defines custom fields for requirements, shown, sortable and filterable on the list, and carried by the list export and import (`RecordTableProvider`), the bundle and the report fields through the same generic paths that mechanism already provides.

**Why:** §11.4 — "these may be represented using the existing custom-field mechanism rather than inventing a completely separate arbitrary attribute system" is the design/decision doc's own recommendation. It also matches the codebase's precedent (`RequirementVersion.custom_fields` with `CustomFieldDefinition`), provided the closed `entity_kind` enum is generalised first rather than extended with a Design value (Phase 0 Q4).

## Phase 6 — Relationships (Requirement, Decision, Risk, Compliance, Verification, Design, Architecture)

**Scope** (§20.7, §16–19, §21): any two registered artefact types already link through `ArtefactLink` (`services.relationships.create_link`), so this phase declares **link type seeds** (`ModuleDefinition.link_type_seeds`, `docs/modules.md` §4f-bis) with `allowed_source_types` and `allowed_target_types`, making the vocabulary meaningful from the first day. Seeds sharing a forward name merge across modules, so a seed another plan also names (Decision to Design in Module 4 Phase 7, Compliance in Module 9 Phase 3) is declared once by whichever module lands first and is harmless if repeated. `Describes` is the exception: Module 18 declares it, and this module does not, so it exists only for an organisation that has System Architecture enabled and this module never needs it to be present. Links attach to the Design identity (Phase 0 Q1), never to a revision, except `Invalidated by` below.

- Design ↔ Requirement: `Implements`, `Satisfies`, `Derived from` (§16 — "Requirement → satisfied/implemented by → Design" is one of the doc's most heavily emphasised relationships, in its four-artefact table: Requirement = what must be true, Decision = why this approach, Design = what solution, Verification = how proven).
- Design ↔ Decision: `Selected by`, `Constrained by` (§8, §9 — the "soft, frequently-used" relationship). Module 4 Phase 7 wires the Decision side; verify both directions appear in the Links panel and the trace.
- Design ↔ Risk: `Mitigates` (§17), in addition to Risk Management's existing Risk → Requirement relationship: a risk can be mitigated at the requirement level, the design level, or both.
- Design ↔ Compliance: `Satisfies Compliance Requirement` (§18). Compliance has shipped, so the link works as soon as the seed exists; Module 9 Phase 3 owns the Compliance-side screens and reports.
- Design ↔ Design: `Refines`, `Depends on`, `Interfaces with`, and `Supersedes` for one Design replacing a *different* Design (a `dedicated_endpoint` seed as Decision's, because it changes a status). Revision-to-revision supersession within one Design is Phase 3's and is not a link.
- Design ↔ Verification: `Verified by`, `Validated by`. A verification record is the registered artefact type `requirement_action`, and `RequirementActionLink` no longer exists (its links folded into `ArtefactLink`), so this is an ordinary link type from `design` to `requirement_action`; nothing is left for Module 0 to generalise.
- Design → Architecture: `Describes` an element or connection (declared by Module 18; Phase 4 and Phase 10 for the use). Offered only where System Architecture is enabled for the organisation and project.
- Design ↔ (Requirement / Decision / Risk / Design): `Invalidated by` — the structured link behind Phase 3's invalidation (Phase 0 Q8/Q9), recorded against the specific revision and pointing at whichever artefact caused the problem (the Requirement whose threshold changed, the Decision that got superseded, the Risk that newly applies, or another Design this one depended on) rather than only a free-text reason. Setting the link and setting `is_invalidated` (Phase 3) happen together, as one action.

**Detecting when this might apply** (informing, not gating, invalidation): when something a Design links to changes — a linked Requirement gets a new approved version, a linked Decision is superseded, a linked Risk's rating changes — the owner is notified that a review may be warranted. The mechanism is `ModuleDefinition.on_artefact_changed` with `services.artefact_changes.notify_artefact_changed` and the module's own `notification_types` (the Risk Management pattern), reading "what links to this record" from the link graph. At the start of the phase, check which sources already call `notify_artefact_changed` (a new approved requirement version does) and add any that do not, such as Decision supersession. The owner is a principal, so a group owner notifies its members, and the notification carries the qualified code. This is deliberately a notification, not an automatic invalidation: the system flags "something changed that this Design depends on", and a human decides whether that breaks it, the same "detect and notify, human decides and acts" split `RequirementReview`'s review-due mechanism uses.

**Why:** §19's own point — a change-impact analysis that can traverse "Processor Design → selected by Decision, satisfies Requirements, interfaces with Power Design, interfaces with Software Architecture, affects Compliance, mitigates Risk, verified by Verification" in one connected graph "is much more useful than simply knowing that several Decisions mention the processor" — is the concrete payoff of building Design as its own artefact, and the traversal Phase 9's Engineering Change Impact report needs.

**MCP tools.** Declare `McpToolDefinition` entries (`mcp_tools`, [docs/modules.md](../modules.md) §6) once the endpoints exist: list designs, get design (current revision and hierarchy position), create and update a design and its revisions, list and create design links. The tools are write-enabled, gated by `MCP_WRITES_ENABLED` and the calling account's own RBAC (**Decided by: User**, 2026-09-22, across modules). Approving a revision and invalidating one are approval-type actions and use the generalised organisation and project `allow_ai_approvals` gate (`services.rbac.require_ai_approvals_enabled`) instead of staying human-only (**Decided by: Agent** on which option). The module sets `ModuleDefinition.mcp_guidance` (`mcp_guidance.md`) and runs `python scripts/generate_mcp_module_tools_reference.py` in `backend/`; `backend/tests/test_mcp_skill_reference.py` fails otherwise. The Phase 9 reports become tools without touching `mcp-server/`.

## Phase 7 — Frontend UI

Follows [docs/ux-style-guide.md](../ux-style-guide.md) and the standing checklist above. The points particular to this module:

- **Hierarchy tree.** Reuse the shared `TreeView` and `TreeSelect` components. If a screen needs a tree that is module-local today (Module 18's element tree), extract it and update the existing call sites rather than adding a second implementation.
- **List, create and edit.** `ListPageLayout` with `TagFilterField`, `ProjectScopeFilter`, sortable columns and the list Export and Import. Create and edit share one field group for a revision's fields; the create form includes `QuickLinkField` and `TagField`, and the owner is a principal picker (users and groups). No Save and activate (approval gate).
- **Detail page.** `RecordHeader` with `back` ("Designs") and `RecordTags`; the status menu from the server transition map; the revision history and compare view (an approved revision is read-only, "New revision" starts a draft); invalidation with its reason and `Invalidated by` link; the Links panel, comments and files.
- **Design options.** A comparison view (Phase 2) and the selection action tied to a Decision.
- **Registrations.** `artefactPaths`, `artefactStatusLabels`, `artefactInactiveStatuses` (superseded, retired, rejected, archived), and `entityAccentColor` on the module's own definition (never a core map or stylesheet). Every enum, status and Design Type value renders through a label map from day one.
- **Tests.** Playwright e2e and Storybook coverage per the standing requirements, with `requiredCaptions` in the story tests.
requirements.

## Phase 8 — Docs website coverage

Adding this as its own explicit, tracked phase (rather than leaving it
implicit) is **Decided by: User** (2026-09-21, the same instruction as the
MCP-tools addition above, applied to every not-yet-built module plan); the
specific scope below is **Decided by: Agent**.

**Goal:** add Engineering Design's user-facing surface to `docs/website/`
(the published docs site, `docs/plans/completed/docs-website-plan.md`) — modeled
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

- A new module section under `docs/website/docs/modules/engineering-design-module/` (the shape of `decision-management-module/`: overview, relationships, known limitations) covering: what a Design is and when to use one, including the explicit boundary that it references CAD/ECAD/source control rather than replacing them (§10); the design hierarchy (parent/child, distinct from project hierarchy per §12) as a validated Mermaid diagram; Design Options and how the selecting Decision relates (Phase 2, §13); the revision model (one Design with immutable approved revisions, per Phase 0 Q1) as a validated Mermaid lifecycle diagram, including invalidation as an overlay marker independent of both status and supersession (Phase 3, Phase 0 Q8/Q9); Interfaces as an "Interface Design" type that describes a System Architecture Connection (Phase 4); Engineering Attributes via the shared custom-field mechanism (Phase 5); and the relationship groups to Requirement, Decision, Risk, Compliance, Verification, Architecture and other Designs (Phase 6), with a short Mermaid diagram showing how a Design sits relative to those artefacts, reusing the doc's four-artefact framing (Requirement = what must be true, Decision = why this approach, Design = what solution, Verification = how proven).
- Update the module index and roadmap (`modules/overview.md`, `modules/roadmap.md`) and add the new terms to `reference/glossary.md`, reusing the term already there where one exists.
- Remove Design from the reserved-relationship rows that name it (`decision-management-module/relationships-and-templates.md`, its `known-limitations.md`, and the Stakeholders page's "Uses Design" row), and cross-link Decision Management's "options considered" field to Phase 2's Design Options.
- **Screenshots.** — **Decided by: User** (2026-09-22, made explicit across
  every not-yet-built module plan's own "Docs website coverage" phase,
  alongside [Module 4](module-04-decision-management-plan.md)'s Phase 6
  addendum of the same date). Follow `docs/plans/completed/docs-website-plan.md`'s
  "Screenshots" standard (1440×900 viewport, captured against the seeded
  demo dataset, stored under `docs/website/static/img/screenshots/`, real
  alt text plus a one-line caption, no surrounding "what this shows/why it
  matters" prose) and its "every Concepts, Core Features, Workflows, and
  Modules page needs at least one screenshot or diagram" bar — not forced
  onto a page whose content is genuinely diagram/table-only. Candidate
  screens for this module's own page — **Decided by: Agent**: the Design
  hierarchy/list view, a Design detail page showing its revision history
  and interfaces, and the Design Option selection UI tied to a Decision.

**Status:** not started. Built after Phase 10 so it covers the integration, and depends on Phase 7 (frontend) actually shipping —
there is no real user-facing workflow to document accurately before then,
the same reasoning Decision Management's own Phase 6 and Compliance's
docs-site page both used.

## Phase 9 — Analysis widgets for Reporting (moved from Module 10 Phase 11b)

**Moved here by the User on 2026-11-04** (**Decided by: User**), so Module 10's plan could close. Module 10 deferred these on 2026-10-28 until Engineering Design, Verification and Baselines existed, so they are built once against real data; this module is where the missing piece (Design, its relationships and its invalidation state) is built. Everything below the first paragraph is **Decided by: Agent** and can be revisited.

**Goal:** two computed analyses, each a collector exposed as a **report widget** (the generic extension point Module 10 shipped: `ModuleDefinition` report widgets and `ReportDefinition`, so a layout or starter embeds them and no core file is edited):
- **Executive Gap Analysis** (requirements §47.5): compares the defined current state with the defined future state (Context & Strategy Future States, Pain Points, Strategies) and adds the dimensions that need this module and the others built since: **design maturity gaps** (a requirement with no approved Design revision, a Design whose current revision is invalidated or still a draft, a Design with no verification), requirement coverage, compliance gaps, high and residual risks, and open Decisions. Each finding traces to the artefacts it came from. A gap is listed, never inferred without a source.
- **Engineering Change Impact** (requirements §47.6): from an existing Change Request or a changed/invalidated Design, lists **direct**, **transitive** and **inferred** impacts over the link graph (Requirement, Decision, Risk, Compliance, Verification Action, Design, baselines possibly invalidated by Phase 3), and keeps the three kinds distinguishable in the output.

**Why:** the Module 10 acceptance criteria "Executive Gap Analyses compare defined current and future states, each finding tracing to artefacts" and "Engineering Change Impact reports identify direct and transitive impacts of an existing change" cannot be met honestly until Design and its relationships exist; building them earlier would have meant rewriting them against real data.

**Risk addressed:** an analysis that guesses (a gap or an impact with no traceable source) reads as fact and becomes a second source of truth; an impact walk that ignores the runner's access leaks records they cannot read.

**Outcome:** both are listed in the Report picker and the designer's Widgets tab under this module, run as the person running them (a record they cannot read is omitted and counted), and are embedded by the Business Requirements Document and Engineering Specification starters where those already name them.

**Work (a checklist, not a design):**
1. Collectors with a `ReportDefinition` each, `record_types` set for the artefact types they name, codes through `ReportContext.code`, perf probe unaffected (no new record type).
2. Impact traversal reuses the Phase 6 relationship set and `link_nesting.can_open_project` for a related project; "inferred" is a stated rule with its source link kind, not a score. When System Architecture is enabled for the project (and omitted entirely when it is not) it also follows `Describes` links into elements and connections and lists them as impacts; baselines possibly invalidated are read from the shared baseline items (Phase 0 Q2).
3. MCP: both appear as report tools without touching `mcp-server/`; update this module's `mcp_guidance.md` and run `python scripts/generate_mcp_module_tools_reference.py` in `backend/`.
4. Docs website: add them to this module's page and to the Custom reports widget list; screenshots from the seeded demo data.
5. Seeds: demo data has a Future State gap and a changed Design so both reports have content.

**Tests:** a collector test per finding kind with its source trace; an access test (a runner who cannot read a linked record sees it omitted and counted); transitive-depth and cycle tests; a starter-embedding test; `test_report_record_codes.py` and the MCP reference tests pass.

## Phase 10 — System Architecture integration

**Scope:** System Architecture is optional. A project or organisation that has not enabled it (server entitlement, organisation enabled, project state: the three levels in `docs/modules.md`) gets every other phase of this module unchanged. Module 18 and this module do not import each other, so everything here goes through generic extension points (links, summary providers, `on_artefact_changed`, the baseline snapshot provider) and works in each direction with the other module off.
- **Independence rules.** This module's registration lists System Architecture as no dependency, hard or soft. No Design screen, report, MCP tool, export column or validation calls an architecture endpoint or names an architecture type unless the owner is enabled for that project; the `Describes` link type is not offered and the architecture card, create-from-connection action and architecture reports are omitted. A Design's own content never depends on the Connection: endpoints are written in the description, and `Interfaces with` links join the two Designs (Phase 0 Q3). If System Architecture is disabled after links exist, the links stay stored, the architecture end reads as not found (the summary provider returns nothing for a disabled owner), and re-enabling restores them; nothing is deleted.
- **Enabling it later.** Turning System Architecture on for an organisation or project that already has Designs changes nothing automatically: no link is invented and no Design is edited. The `Describes` link type is created for the organisation the first time its link types are read after the module is on (a type from an earlier period of being enabled is simply reused), and links stored earlier reappear. Existing Interface Designs, whose endpoints were written in the description, appear in "Interface Designs with no Connection", so a person links each to a Connection as the architecture is entered, from the Design's Links panel. Baselines taken earlier hold Designs only, and later ones hold both. Change notifications start for a Design when it is linked.
- **Design side.** A Design that `Describes` an element or connection shows a read-only card of it (code, type, endpoints, protocol) through Module 18's summary provider, so an Interface Design never restates them. A person can create an Interface Design from a Connection's Links panel (create-and-link, `docs/modules.md` §4l2), pre-linked with `Describes`.
- **Architecture side.** An element's or connection's Links panel lists the Designs that describe it with no Module 18 edit; verify it does, and if a generic gap appears, fix it as a generic extension point.
- **Change in both directions.** An edit to a described element or connection notifies the owners of the Designs that describe it (a review may be warranted, Phase 6's detect-and-notify), and a Design revision being invalidated is visible from the element. If Module 18's records do not yet call `notify_artefact_changed`, that is added in Module 18's own plan, not here.
- **Coverage reports.** `ReportDefinition` entries for "elements and connections with no Design" and "Interface Designs with no Connection", complementing Module 18's allocation coverage (requirements to elements); both appear in Phase 9's impact traversal.
- **Baselines.** A stage baseline holds the approved Design revisions and the architecture snapshot together; check that Module 18's snapshot compare screen can list the Design items beside them through the generic item list.
- **Stakeholders.** Module 2's reserved "Uses Design / System Element" relationship goes live for both types once each registers its provider.

**Why:** a Design records *why and how* and an element records *which part*; without the link-up each gets re-typed or goes stale when the other changes. **Risk addressed:** a Design reading an element it cannot see (an organisation-owned element shared through collections, or one in a related project), and drift between a Design and the Connection it describes. **Outcome:** both modules work alone and together; the cross-visibility rule is Module 18's visibility resolver, never a second copy.

**Tests:** enabling System Architecture later on a project with existing Interface Designs (nothing changes until a link is made, the report lists them, linking works); the whole Design suite runs with System Architecture not enabled (organisation off, project off, and not entitled) and passes with no architecture type registered in the test's module set; both modules enabled and each disabled; disabling after links exist and re-enabling; a Design describing a shared organisation element read by someone with and without access (omitted, never leaked); change notifications both ways; the baseline lists both; Playwright for create-from-connection.

## Phase 11 — Security review

Identify, verify, remediate, recorded in `docs/decisions.md`, against the access-control, system-operations and change-management policies in `docs/soc2/policies/`. Cover: the approval gate and segregation of duties (who may approve their own revision, as Decision's rule); the permission atoms per Design Type and the module-enablement 404 gate on every check; the AI-approval gate on approve and invalidate; visibility of described elements and cross-project links (Phase 10); an imported bundle or CSV never carrying an approved status past the gate; group owners and approvers from another organisation rejected; Restricted-classified and personal-data columns absent from search, export and snapshots; external reference locations validated (scheme allow-list, no credentials, never fetched by the server) and rendered without script or referrer exposure, uploaded design files subject to the data classification policy (the `confidential` flag, reports never printing them); audit events carrying ids and counts only. Anything found is fixed in this phase.

## Phase 12 — Seeds, completeness and close-out

`seed_demo_data.py` and `seed_e2e_dataset.py` demonstrate a hierarchy, Design Options with a selected one, several revisions, an invalidated revision with its cause, and, where Module 18's seeds are loaded, an Interface Design describing a Connection (the Design seeds also load and the e2e suite also runs with System Architecture off); Storybook and Playwright gaps closed; the performance probe and generator re-run at two sizes with any finding added to the register and guarded; `docs/modules.md`, `docs/solution-architecture.md`, README, the index row and Module 18's Phase 13 hand-off line updated; the Status table reads N/N and the plan moves to `docs/plans/completed/` per the plan lifecycle.

## Standing checklist per phase

Each phase ships everything its tables and screens need in the same change; the registry and guard tests named below fail otherwise. Decisions are tagged `Decided by: User` or `Decided by: Agent` in `docs/decisions.md`.

| Concern | What this module does |
|---|---|
| Module boundary | All code in `backend/app/modules/design/` and `frontend/src/modules/design/`, registered through `ModuleDefinition` and `TierAModuleDefinition`. No core file imports it, and no core enum, column or stylesheet gets a Design value: a need from core (a custom-field kind, a baseline snapshot provider) is a generic extension point. |
| Migrations | A module migration directory; the number is the maximum across the core and module directories at build time, never a number copied from a plan. |
| Identity and discovery | `DES-nnn` code (`generate_unique_code`), summary provider with browse levels, type label, `search_providers` (comments declared if searchable), `artefactPaths`. |
| Lists | `RecordTableProvider` (export and import, `count`), `project_scope: ProjectScope = Depends()` with `ProjectScopedRow`, `TagFilter`, `ListPageLayout`, sortable columns with the sort in the URL, list position kept. |
| Forms | Shared field components with `help` or `helpNotNeeded`, `required` markers, `QuickLinkField`, `TagField`, one field group for create and edit, the form header, growing text areas, `LabeledSelect` and label maps for every enum. |
| Records shared across types | Tags, links, placements (in the bundle rows), `activity_kinds` for the History page, `notification_types` where the module notifies. |
| Bundles | Project (and organisation, or a stated reason) bundle hooks, template-project classification of every key, a round-trip test, hidden organisation defaults carried. |
| Performance | `scaling_probes` and `perf_generators` with a ratio in `perf/datasets/profiles.yaml` (bump `version`); every list, export and link read takes versions, owners, tags and links in bulk, so the statements stay flat as rows grow. |
| Access and audit | Permission atoms bound per Design Type, a module-enablement 404 gate on every permission check, three-level availability, audit through `services/audit.py` carrying ids and counts and never free text. Consult the access-control, system-operations and change-management policies in `docs/soc2/policies/` and record an identify, verify, remediate review in `docs/decisions.md`. |
| Optional modules | Everything that touches another module (System Architecture, Compliance, Risk, Decisions) is gated on that module being enabled for the project and degrades to nothing, never an error; tests run with each optional module off. |
| Users and groups | Owner, approver and any reviewer are principals; group membership is effective membership. |
| Nested projects | Design Types fall back to the nearest ancestor (Phase 1), seeded for a root project only. |
| Time | State which shape each time field is (past instant in UTC, scheduled wall-clock time with IANA zone, or calendar date) and test the boundary hours. |
| Reports and MCP | `ReportDefinition` entries list `record_types`; report fields and starters; MCP tools, `mcp_guidance.md` and the generated reference (Phase 6). |
| Seeds and documentation | `seed_demo_data.py` and `seed_e2e_dataset.py` demonstrate Designs; `docs/modules.md`, `docs/solution-architecture.md` and `docs/decisions.md` updated; the docs website reviewed (Phase 8) including the two performance pages; README if the module list changes. |
| Quality | `scripts/check_mypy.py` at zero findings; Playwright specs and pytest tests independent of order; one `pytest` run at a time. |

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
- A Design can record alternative options and which one was selected, through the Decision that selects it (Q12).
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
- Interfaces are representable as Designs without a separate subsystem, and an Interface Design can describe a System Architecture Connection instead of restating its endpoints.
- Designs support structured engineering attributes via the existing
  custom-field mechanism.
- Designs participate in the common relationship model: to Requirements,
  Decisions, Risks, Compliance, other Designs, and Verification.
- Engineering Design does not attempt to replace CAD/ECAD/source-control
  tools: a revision records files (exported renderings and evidence, with a content hash) and external references (a system and identifier such as a PLM item, an optional location, a pinned version), and an approved revision's files and references are frozen. Pulling content from those tools is not built in the first version (Q13).
- Every Design has a project-scoped `DES-nnn` code shared by all its revisions (addressed `DES-001 r2`), is findable by the global search, is placeable in the component tree, lists with Export and Import, and travels in the project bundle.
- Design Types are a two-tier vocabulary: an organisation default can be hidden and restored in a project, and a child project with none of its own falls back to the nearest ancestor's.
- An owner or approver can be a user or a group.
- Approving and invalidating a revision are approval-type actions covered by the AI-approval gate; the MCP tools and agent skill are updated with the module.
