"""
Module: modules.compliance.models

The Compliance Module's data model. Phase 5 (docs/Compliance_Module_
Requirements.md §2, §5, §6, §25, §31) built the organisation-level, reusable
compliance standard definitions. Phase 7 (§7-§11, §16, §20, §25, §26) adds
the project-specific assessment layer on top of them: per §31's "A
Compliance Requirement must not contain the compliance state of a project,"
that state was deliberately kept off `ComplianceRequirement`/
`ComplianceRequiredAction` and lives in the three models at the bottom of
this file instead.

Shape, per §25's conceptual data model:

    ComplianceStandard (org-level identity row)
        `-- ComplianceStandardVersion (versioned content, §4)
                `-- ComplianceRequirement (hierarchical, self-referential, §5)
                        `-- ComplianceRequiredAction (§6)

    ComplianceActionTypeDefinition (org-level, extensible vocabulary, §6)

    Project
        `-- ProjectCompliance (a project's assignment to one standard version, §7)
                `-- ProjectComplianceRequirement (per-requirement assessment, §8-§10)
                        `-- ComplianceRequiredActionAssessment (per-required-action assessment, §6/§25)

Design decisions:
- `ComplianceStandard`/`ComplianceStandardVersion` follow the `Requirement`/
  `RequirementVersion` identity-row + versioned-child-row shape the plan's
  Phase 5 spec calls for, but *not* that pair's valid_from/valid_to temporal
  semantics: a `RequirementVersion` superseded by a newer one is history,
  while every `ComplianceStandardVersion` remains independently live and
  addressable indefinitely, since different projects may deliberately stay
  pinned to different past versions forever (§4's worked example — Project A
  on v1.1, Project B on v1.0). Versions are instead ordered and made
  immutable by `version_number` + `status` (draft -> published -> retired),
  not superseded by a newer row.
- `ComplianceRequirement`'s self-referential `parent_requirement_id` is a
  plain foreign key with no ORM `relationship()`, matching `Project.
  parent_project_id`'s own precedent (hierarchy traversal is a service-layer
  concern, not something the ORM needs to model directly) rather than
  `Requirement`/`RequirementVersion`'s `relationship()`-backed pattern, which
  exists there to walk a *single* linear version history rather than an
  arbitrary-depth tree.
- `ComplianceRequiredAction` belongs to exactly one `ComplianceRequirement`
  (a plain one-to-many foreign key), unlike `RequirementAction`, which is
  many-to-many with requirements via `RequirementActionLink`. §25's data
  model diagram places "Required Actions" as a direct child of "Compliance
  Requirements" with no separate mapping table, and nothing in §6 asks for
  one required action to be reused verbatim across multiple compliance
  requirements the way a `RequirementAction` can be reused across
  requirements within a project.
- §6 also lists "Status," "Assignee," "Due date," "Completion information,"
  and "Evidence" as things a Required Action "should support" — those are
  the *project-specific assessment* of a required action (§25's "Required
  Action Assessments," nested under "Project Compliance Requirements," not
  under "Required Actions"), and so belong to Phase 7's per-project
  assessment model, not to this reusable definition — the same §31
  principle that keeps compliance state off `ComplianceRequirement` applies
  identically one level down.
- "Review schedule" (§2, one of a standard's listed attributes) is
  satisfied by Phase 10's dedicated `ComplianceReview` entity (§17: "
  Compliance Standards and Project Compliance records must support
  scheduled reviews"), not a scalar field here — §25's diagram places
  "Compliance Reviews" as its own entity, not a column.
- "Appropriate audit/history information" (§2) is satisfied by
  `TimestampMixin`'s `created_at`/`updated_at` plus Phase 6's
  `services.audit.log_event` integration on every mutating endpoint, not a
  bespoke history column here.
- `ComplianceStandard`'s "Status" attribute (§2) is satisfied by the
  existing `is_archived`/`archived_at`/`archived_by` soft-delete convention
  already used by `Requirement`/`RequirementAction`, not a separate status
  enum — a standard's own active/archived lifecycle is independent of its
  versions' draft/published/retired lifecycle (`ComplianceStandardVersion.
  status`), which is what actually needs a dedicated enum (§4).
- `ComplianceActionTypeDefinition` mirrors `ActionTypeDefinition`'s existing
  extensible-vocabulary pattern (§6: "Action types should preferably be
  configurable/extensible rather than hard-coded"), but is organisation-
  scoped rather than project-scoped: a required action's type is chosen
  within a Compliance Standard, which is itself an organisation-level,
  cross-project resource (§2's "must be capable of being assigned to
  multiple projects"), so the vocabulary it draws from is scoped the same
  way. No rows are seeded by this phase — Phase 5 is data model only; seed
  data (including §6's "potential initial action types") lands in Phase 15,
  per this plan's own precedent of shipping empty, extensible tables ahead
  of any seed step (see module system Phase 1's notes on
  `organization_module_entitlements`/`organization_modules`).

Phase 7 design decisions:
- `ProjectCompliance.standard_version_id` may only ever be set to a
  `PUBLISHED` version (enforced at the API layer, `router.py::
  create_project_compliance`) — a `DRAFT` version's requirements aren't
  fixed yet, and `ComplianceStandardVersionStatus.RETIRED`'s own docstring
  already states a retired version is "no longer assignable to **new**
  projects." An existing assignment stays on its version regardless of
  that version's later lifecycle changes (§4, §27) — nothing here ever
  moves `standard_version_id` to a different row.
- "Compliance Officer(s)" (§7's own field list for `ProjectCompliance`) is
  **not** a column on this model — it's already fully answered by
  `UserModuleRole` rows for `(module_key="compliance", role_key=
  "compliance_officer", project_id=...)` (module system Phase 2), which
  the existing `GET/POST /projects/{project_id}/members/{user_id}/
  module-roles` endpoints already expose. Duplicating that as a second
  field here would create two sources of truth for the same fact.
- "Review schedule" (§7's field list) is, like §2's identical field on
  `ComplianceStandard`, satisfied by Phase 10's dedicated `ComplianceReview`
  entity, not a column here — see this file's Phase 5 notes above for the
  identical reasoning applied to the standard-level case.
- `ProjectComplianceRequirement.explicit_applicability` is nullable —
  `None` means "never explicitly decided," distinct from an explicit
  `APPLICABLE` decision, even though both currently *resolve* to the same
  effective value absent an ancestor override. This is what lets
  `service.py::resolve_applicability` distinguish "the ordinary, untouched
  default" from "a user actively confirmed this is applicable" if a future
  phase ever needs to (today both render as the same `EXPLICIT` source —
  see `ComplianceApplicabilitySource`'s own docstring).
- A single `justification` column serves both §9's "Not Applicable
  justification" and §16's "rationale... required for Non-Compliant
  decisions" — §8 itself lists this as one field ("Justification/
  rationale"), and the two are never needed simultaneously in practice (a
  row is either Not Applicable *or* Applicable-and-assessed, never both at
  once). Enforced as mandatory, at the API layer, exactly when
  `explicit_applicability` is being set to `NOT_APPLICABLE` or
  `compliance_status` is being set to `NON_COMPLIANT` — never a NOT NULL
  constraint, since it is conditionally required depending on which other
  field is changing.
- `ProjectComplianceRequirement.approval_state` exists now (default
  `NOT_ASSESSED`) but no endpoint in this phase changes it — see this
  file's enums module docstring for why the column can't wait for Phase 9
  without splitting one coherent piece of the data model across two
  phases, mirroring the same reasoning Phase 5's own notes already recorded
  for `ComplianceStandardVersionStatus`.

Phase 9 design decisions:
- `approval_decided_at`/`approval_decided_by`/`decision_note` are added to
  `ProjectComplianceRequirement` (§12's "Date/time of approval"/"Who
  approved/signed off the assessment") — one column pair serves *both* an
  approval and a rejection decision (mirroring `justification`'s own
  Phase-7-established "one field, meaning depends on which transition is
  happening" precedent) rather than separate `approved_*`/`rejected_*`
  pairs, since a row is never both at once and `approval_state` itself
  already distinguishes which decision `decision_note` belongs to.
  "Who performed the assessment"/"date/time of assessment" (§12) reuse the
  existing `assessed_at`/`assessed_by` columns — no new columns needed
  there.
- No new "submitted for approval" timestamp/actor columns: §12's own
  minimum field list names only assessment and approval timestamps, not a
  submission event, and `services.audit.log_event`'s existing history
  (surfaced by `project_router.py::get_requirement_history`) already
  records who/when moved a row into `PENDING_APPROVAL` — adding a redundant
  pair of columns for a fact the audit trail already carries would be a
  second source of truth for the same thing, the same call this file's own
  Phase 5/7 notes already made about not duplicating audit-log facts as
  columns.
- No bespoke "approval history" table: §12's "Approval/sign-off history"
  is satisfied by the same `AuditEvent` rows/`get_requirement_history`
  endpoint that already carry Phase 7's assessment/applicability history —
  `service.py`'s new `advance_approval_state_on_assessment`/`invalidate_
  approval_if_in_flight` transitions are logged through `log_event` by
  their callers exactly like every other mutation in this module, not a
  second, parallel history mechanism.
- The state-machine transitions themselves (§12's "Not Assessed -> Assessed
  -> Pending Approval -> Approved/Rejected -> Requires Re-assessment") are
  business logic, not something this file enforces structurally — see
  `service.py`'s own docstring and `project_router.py`'s new `submit-for-
  approval`/`approve`/`reject` endpoints.
- Every `ComplianceRequirement` in an assigned version — section/parent
  rows and leaf rows alike — gets its own `ProjectComplianceRequirement`
  row, materialised once, in full, at `ProjectCompliance` creation time
  (`router.py::create_project_compliance`), not lazily on first access.
  This deliberately does not special-case "does this requirement have
  children" — the tree structure only matters for applicability
  inheritance (§9) and requirement-count totals (§20), not for which rows
  exist. Same materialisation for `ComplianceRequiredActionAssessment` —
  one row per `ComplianceRequiredAction` under the version, created at the
  same time. A version's requirement/required-action set is immutable
  once published (Phase 6's own enforcement), so there is nothing to
  reconcile later: the set materialised at assignment time is permanently
  complete for that assignment.
- `ComplianceRequiredActionAssessment` mirrors `Requirement`'s own
  "completion overlay" shape (`is_completed`/`completed_at`/`completed_by`,
  see `Requirement.completed_at`'s own docstring) rather than reusing the
  `ComplianceStatus` enum — a required action is closer to a task than to
  something needing degrees of compliance, and §6's own field list
  ("Status, Assignee, Due date, Completion information") reads as a task's
  fields, not a re-assessment's.
- Evidence linkage is deliberately absent from every model in this file —
  Phase 8 owns it, following `services/files.py::upload_file`'s existing
  join-table-per-owner-type convention; adding a placeholder column now
  would just need reconciling away later, the same call Phase 5 already
  made about its own standard-level fields.

Phase 11 design decisions:
- `ComplianceRequirement.cloned_from_requirement_id` (nullable,
  self-referential, `ondelete="SET NULL"`) is a new column recording which
  requirement (if any) a given requirement was cloned from by `router.py::
  _clone_requirement_tree` when a new standard version is created from an
  existing one. Before this phase, cloning remapped old-id -> new-id only
  in memory, for the duration of one clone operation, and persisted
  nothing — §27's "identify requirements that are added/removed/modified/
  replaced/re-mapped" between two versions cannot be answered precisely
  without a durable lineage link: without it, a version diff could only
  guess "same name/reference -> probably the same requirement," which
  breaks the moment a requirement is renamed *and* content-edited in the
  same version (indistinguishable from one being removed and an unrelated
  one being added). `ondelete="SET NULL"`, not `CASCADE`, deliberately
  mirrors `Project.parent_project_id`'s "detach, don't cascade" precedent
  rather than this same file's own `parent_requirement_id` `CASCADE`
  precedent one column up: `parent_requirement_id`'s `CASCADE` exists
  because a compliance requirement has no "stand alone once detached"
  concept *within its own tree* — deleting a section requirement should
  take its subsections with it. Deleting the *source* requirement a later
  version's requirement was cloned from is a different situation entirely:
  the cloned requirement is a fully independent row in a different,
  already-published version that must keep existing and keep its own
  identity regardless of what later happens to the version it was cloned
  from (a draft version can still have its unpublished requirements
  deleted before publishing) — `SET NULL` simply means "the lineage record
  is gone," which `service.py::diff_standard_versions` already treats
  identically to "never had a lineage record" (i.e. `added`), the correct
  fallback. See `service.py::diff_standard_versions`'s own docstring for
  exactly how this column is walked (including the multi-hop case: diffing
  two versions that are not directly adjacent, e.g. v1 vs. v3 when v3 was
  cloned from v2, not v1).
- `ComplianceMappingRelationshipTypeDefinition` is a new, organisation-
  scoped, extensible vocabulary table for §19's "relationship types...
  configurable or extensible where practical" (Equivalent, Satisfies,
  Derived From, Related To, Overlaps, Conflicts With are examples, not a
  fixed enum) — mirrors `ComplianceActionTypeDefinition`'s exact shape
  (`organization_id`, unique `name`, `sort_order`), which this plan's own
  Phase 5 notes already established as this module's precedent for "a
  vocabulary chosen from within an org-level resource is itself org-
  scoped." No rows are seeded by this phase, consistent with every other
  vocabulary table in this module (`ComplianceActionTypeDefinition`'s own
  Phase 5 notes) — seed data is Phase 15's job.
  `__tablename__` is `compliance_mapping_relationship_types`, not
  `..._type_definitions` (which every column name elsewhere in this class
  would otherwise suggest, matching `ComplianceActionTypeDefinition`'s own
  `compliance_action_type_definitions`): the longer name's auto-generated
  `organization_id` index name (`ix_compliance_mapping_relationship_
  type_definitions_organization_id`, 67 characters) exceeds Postgres's
  63-byte identifier limit — the exact class of problem `Compliance
  RequiredActionAssessment`'s own comment already documents for a
  different table, solved there with an explicit shortened index name and
  solved here instead by shortening the table name itself, which reads
  more naturally than an oddly-abbreviated index alongside a normal-length
  table name.
- `ComplianceRequirementMapping` is a new table recording one directed
  relationship between two `ComplianceRequirement` rows (`from_requirement_id`
  -> `to_requirement_id`, typed by `relationship_type_id`) — the cross-
  standard mapping §19 asks for. Deliberately **not** restricted to rows in
  *different* standards: nothing about the mapping's own shape needs that
  restriction, and §27's "re-mapped" version-diff category and this same
  phase's "replaced" category (see `service.py::diff_standard_versions`'s
  own docstring) both deliberately reuse this exact same table for a
  same-standard, cross-*version* link — a Compliance Manager marking "the
  new v2.0 clause 5.3 replaces the old v1.0 clause 4.9, which was removed
  outright rather than cloned forward" is structurally the same fact
  (\"these two requirement rows are related, and here's how\") as marking
  an ISO 27001 clause equivalent to a corporate standard's clause, so one
  mechanism serves both rather than inventing a second, parallel
  "supersedes" table. Directed (not a symmetric/unordered pair) because
  several of §19's own named relationship types are inherently directional
  (\"B Derived From A\", \"B Satisfies A\") — a symmetric relationship
  (Equivalent, Overlaps, Related To, Conflicts With) is simply stored with
  an arbitrary but stable from/to order, since nothing about this table's
  own semantics depends on treating one direction as more authoritative.
  `organization_id` is stored directly (denormalised from the mapped
  requirements' own standards) rather than derived through two joins on
  every request, mirroring `ComplianceStandard.organization_id` itself
  being the scoping anchor for every other org-scoped lookup in this
  module — both endpoints creating/reading mappings need one flat,
  indexed column to enforce cross-org isolation the same "404, not 403"
  way as every other resource in this module (`router.py`'s own
  docstring). A `CHECK (from_requirement_id != to_requirement_id)`
  constraint rules out a self-referential mapping, which could never mean
  anything (a requirement cannot be Equivalent To/Satisfies/etc. itself).
  `is_archived`/`archived_at`/`archived_by` mirror every other entity in
  this module's soft-delete convention — a mapping is auditable history
  (§19: "must be... auditable") once created, so removing one is a
  lifecycle transition, not a hard delete, exactly like `ComplianceStandard`/
  `ComplianceEvidence`. A `UNIQUE (from_requirement_id, to_requirement_id,
  relationship_type_id)` constraint prevents the exact same relationship
  being recorded twice between the same pair, while still allowing more
  than one relationship type to exist between the same pair (e.g. both
  "Overlaps" and "Related To" recorded separately, if a Compliance Manager
  judges both apply) — nothing in §19 suggests a pair of requirements can
  only ever have one relationship between them.
  Per §19's explicit "must not imply that satisfying one requirement
  automatically satisfies another unless the relationship explicitly
  supports that behaviour": this table and every endpoint that reads or
  writes it are pure metadata for every purpose *except* one narrow,
  deliberate exception — see `ComplianceMappingRelationshipTypeDefinition.
  implies_equivalence` and the "carry-forward across a `replaced` mapping"
  addition below. Outside that one path, no code anywhere in this module
  reads a `ComplianceRequirementMapping` row to alter a
  `ProjectComplianceRequirement.compliance_status`/`approval_state` value
  on the other side of a mapping — mapping rows are otherwise only ever
  read to *report* structure (the diff/re-mapped logic in `service.py`),
  never to *write* an assessment value.
- **Carrying an assessment forward across a `replaced` mapping is possible,
  but only when both an org-level and a per-migration human decision agree
  — never automatic, and never a general property of the mapping
  mechanism.** Added after this phase's initial implementation, in
  response to direct feedback that always forcing a `replaced` requirement
  (e.g. an old "IPX6 water ingress" requirement explicitly linked to a new
  "IP67 water ingress" requirement) back to blank defaults on migration
  was too blunt when a Compliance Manager has already judged the two
  genuinely equivalent. The mechanism has two independent gates, both of
  which must be satisfied, so this never becomes the kind of automatic
  cross-requirement inference §19 explicitly rules out:
  (1) `ComplianceMappingRelationshipTypeDefinition.implies_equivalence`
  must be `True` on the specific mapping's relationship type — an org-
  level, Compliance-Manager-only decision about which relationship types
  are strong enough to ever be used this way (defaults `False`; "Related
  To"/"Overlaps"/"Conflicts With" are never expected to be marked `True`,
  though nothing stops an org from choosing to — this table's vocabulary
  is deliberately theirs to define, per §19's own "configurable or
  extensible" instruction, so this module doesn't hardcode a fixed allow-
  list of type *names*).
  (2) The compliance officer performing the *specific* migration must
  separately, explicitly list that specific new-version requirement's id
  in `ProjectComplianceMigrationRequest.confirmed_replacement_requirement_id
  s` — a mapping existing and being of a strong-enough type only ever
  makes carry-forward *possible*, never automatic; nothing carries forward
  a project's own assessment without a human confirming it for that
  project's own migration, exactly like every other consequential
  decision in this module (assessment, applicability, approval). See
  `service.py::migrate_project_compliance`'s own docstring for exactly
  what is/isn't copied when both gates are satisfied, and why a
  `replaced`-carried row's `requires_reassessment` is always `True`
  regardless of its carried-forward `approval_state` (unlike an
  `unchanged`-carried row, where it depends on whether `approval_state`
  actually needed downgrading) — the underlying wording did change, even
  if a human has judged the change immaterial.

Phase 8 design decisions:
- `ComplianceEvidence` is project-scoped (`project_id`), not standard- or
  requirement-scoped: evidence (a certificate, a test report) is a real
  artefact supplied for one project's own assessment, even though a
  single row may support several of that project's requirements and/or
  required actions at once (§13's own "a single piece of evidence should
  be capable of supporting multiple compliance requirements"). That
  multi-linkage is a genuine many-to-many, not a foreign key on either
  side — see `ComplianceEvidenceRequirementLink`/`ComplianceEvidenceActionLink`
  below, which deliberately point at the project-specific assessment rows
  (`ProjectComplianceRequirement`/`ComplianceRequiredActionAssessment`),
  not the reusable `ComplianceRequirement`/`ComplianceRequiredAction`
  definitions — the same §31 "state belongs to the project-specific
  assessment layer, not the reusable definition" principle this file's
  own Phase 7 notes already apply to `ComplianceStatus`/
  `ComplianceApplicability`, extended one concept further to evidence.
- `ComplianceEvidence.expiry_date` is this row's *current* effective
  expiry — revalidating (§15) updates it in place. `ComplianceEvidenceRevalidation`
  is a separate, append-only table recording what it previously was: §15's
  own worked example ("Issued/Expires/Revalidated/By/New expiry") requires
  the *previous* expiry to remain visible after a revalidation, which a
  plain in-place update (even with `updated_at` tracking) cannot provide,
  since a second revalidation would overwrite the first's own "previous"
  value along with the row's `expiry_date` itself.
- `ComplianceEvidenceFile` mirrors `app.models.file.RequirementFile`'s
  exact shape (UUID PK, `evidence_id`/`file_id`/`linked_by`/`created_at`,
  no `updated_at`) rather than reusing that table directly — it lives in
  this module (not `app.models.file`) since it is Compliance-owned, not a
  core concept, per §13's "reuse ReqTrackManager's existing attachment/
  file mechanisms" (i.e. `services.files.upload_file`), not its existing
  *tables*, which are all owned by specific core entities.
- `is_archived`/`archived_at`/`archived_by` on `ComplianceEvidence` mirrors
  every other compliance entity's soft-delete convention exactly, and is
  this model's answer to §13's own listed attribute "Whether it remains
  applicable" — deliberately not a hard delete, since that would silently
  sever `ComplianceEvidenceRequirementLink`/`ComplianceEvidenceActionLink`
  rows that other assessments' own audit trail (§16) may still depend on.

Phase 10 design decisions:
- `ComplianceReview` has exactly one of `standard_id`/`project_compliance_id`
  set (a `CheckConstraint`, not left to convention) — §17's "Compliance
  Standards and Project Compliance records must support scheduled reviews"
  names two distinct owners, not a shared "reviewable thing" abstraction;
  a standard-level review (e.g. "annual audit of this standard itself") and
  a project-level review (e.g. "review this project's compliance before
  release") are different concerns that happen to share every other field.
- `frequency_label` (free text, e.g. "Annual," "Before product release")
  plus an optional `recurrence_days` (nullable — `None` means "one-off,
  does not auto-recur") were chosen over a fixed calendar-frequency enum:
  §17's own examples include event-triggered reviews with no calendar
  cadence at all ("Review before product release," "Review after a
  significant standard change"), which a rigid Annual/Six-Monthly/... enum
  can't represent without an awkward "Other" escape hatch.
- "Review history" (§17) is satisfied by *retaining* each completed
  `ComplianceReview` row (never deleted, `status` moves to `COMPLETED`)
  and, when `recurrence_days` is set, creating a **new** `SCHEDULED` row
  for the next cycle rather than reopening/reusing the completed one — see
  `service.py::complete_review`. Querying every `ComplianceReview` row for
  one owner, ordered by `created_at`, *is* that owner's review history;
  no separate history table, mirroring Phase 7/9's own "the audit trail
  already carries this" reasoning applied to a different mechanism (chained
  rows instead of `AuditEvent`, since a review's own recurrence naturally
  produces one row per cycle already).
- `ComplianceReviewEvidenceLink` (§17's "Notes/evidence associated with the
  review") is a many-to-many, mirroring `ComplianceEvidenceRequirementLink`'s
  exact shape (§13's own established evidence-linkage convention) rather
  than a single nullable FK — the same "a piece of evidence may support
  more than one thing at once" reasoning Phase 8 already applied to
  requirements/required actions, extended to reviews. Enforced at the API
  layer only (not a DB constraint) that a link's evidence and review share
  the same project — a standard-level review (no `project_id` of its own)
  cannot be linked to project-scoped evidence at all, since it has no
  project to share.
- Evidence-expiry/required-action-due/target-date reminder "already sent"
  bookkeeping (`*_reminder_sent_at`/`*_notified_at` pairs on `ComplianceEvidence`/
  `ComplianceRequiredActionAssessment`/`ProjectCompliance`) lives on each
  owning row rather than a separate notification-log table, mirroring
  `RequirementVersion.review_reminder_sent_at`'s own established Massif
  (v3) precedent for exactly this "don't re-notify every sweep run" need.

Phase 20 design decisions (Standard Applicability Defaults, Exceptions, and
Project-Manager Assignment — second human-review round):
- `ComplianceStandard.applicability_default` is a plain column on the
  standard itself, not a separate "applicability policy" entity — §3/§26
  already treat this as a property of the standard a Compliance Manager
  curates, and there is exactly one such setting per standard, never a
  history of past settings worth modelling separately (unlike, say,
  `ComplianceStandardVersion.status`, which genuinely has a lifecycle).
- `ComplianceStandardDefaultExclusion` is a real join table
  (`standard_id`, `project_id`) with a mandatory `reason`, mirroring the
  Phase 7/9 mandatory-justification convention exactly (Not Applicable,
  Non-Compliant, Rejection) — enforced at the API layer, same as those,
  not a DB `CHECK` (an empty-string reason is a payload-validation
  question, not a schema-shape one). `ON DELETE CASCADE` on both foreign
  keys: an exclusion row has no independent meaning once either its
  standard or its project is gone.
- Reconciliation never creates a *second*, duplicate `ProjectCompliance`
  row for a project that already tracks the standard via any of its
  versions (whether that existing row came from a Project-Manager
  self-service assignment, a Compliance-Manager manual assignment, or a
  prior reconciliation pass) — it only fills the gap for a project with
  none. This is a deliberate, narrower reading of the spec's "materialise
  a real row for every ... project" than "always assign the very latest
  published version regardless of what's already tracked": the latter
  would either violate `ProjectCompliance`'s own `(project_id,
  standard_version_id)` uniqueness constraint when a still-archived row
  already occupies that exact pair, or silently create a second, confusing
  concurrent assignment to a different version of the same standard when
  it doesn't. See `service.py::reconcile_standard_applicability`'s own
  docstring for the exact rule and why un-excluding a project reuses (by
  unarchiving) an exclusion-time-archived row for the same version rather
  than creating a fresh one.
- Reconciliation always targets the standard's *current latest `PUBLISHED`
  version* at the moment it runs (standard flipped to "applies to all," a
  new project created, or a project un-excluded) — not a version pinned at
  the moment `applicability_default` was first set. A standard with zero
  published versions simply reconciles nothing (not an error): switching a
  standard to `APPLIES_TO_ALL_PROJECTS` before it has anything publishable
  is allowed (a Compliance Manager may set the policy ahead of publishing
  the standard's content), it just has no projects to materialise against
  until a version is published.
- Switching a standard *back* to `OPT_IN` never retroactively archives
  `ProjectCompliance` rows a prior `APPLIES_TO_ALL_PROJECTS` reconciliation
  created — once a real assignment row exists, it is exactly as permanent
  and independently manageable (archivable, one at a time) as a manually
  created one, per this module's existing "a real row carries a real
  assessment/audit trail" principle (§8, §16). `applicability_default`
  only ever governs *future* reconciliation events, never past ones.

External dependencies: none beyond this project's own ORM/config modules.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.modules.compliance.enums import (
    ComplianceApplicability,
    ComplianceApprovalState,
    ComplianceReviewOutcome,
    ComplianceReviewStatus,
    ComplianceStandardApplicabilityDefault,
    ComplianceStandardVersionStatus,
    ComplianceStatus,
)


class ComplianceStandard(UUIDPKMixin, TimestampMixin, Base):
    """An organisation-level, reusable compliance standard (§2) — e.g.
    "Corporate Security Standard." Not a project: per §31, "A Compliance
    Standard is not a Project" and "Compliance Standards are organisation-
    level reusable definitions."

    Attributes:
        organization_id: The owning organisation. A standard is defined
            once and assignable to any number of that organisation's
            projects (§2, §7) — never duplicated per project (§2's "A
            project must not need to duplicate the underlying compliance
            requirements simply because multiple projects use the same
            standard").
        reference: Human-readable identifier/reference code (§2), e.g.
            "ISO-27001", unique within the organisation.
        name: Display name, e.g. "Corporate Security Standard."
        description: Free-text description.
        issuing_organisation: The external body that issues/owns this
            standard, where applicable (§2) — e.g. "ISO." `None` for an
            internally-authored standard.
        owner_id: The user accountable for this standard (§2's "Owner"),
            distinct from `creator_id` — mirrors `RequirementVersion.
            owner_id` being distinct from `created_by`, since ownership may
            be reassigned after creation while authorship never changes.
        creator_id: The user who created this standard (audit fact, never
            reassigned).
        is_archived / archived_at / archived_by: Soft-delete / lifecycle
            state, mirroring `Requirement.is_archived`'s convention exactly
            — this satisfies §2's "Status" attribute; see this module's own
            docstring for why a separate status enum wasn't introduced.
        applicability_default: Phase 20's own addition — whether this
            standard's default project-assignment mode is the ordinary
            per-project opt-in (`OPT_IN`, every standard's behaviour before
            this phase, unchanged) or an org-wide "applies to all projects
            by default, except..." mandate (`APPLIES_TO_ALL_PROJECTS`) —
            see `ComplianceStandardApplicabilityDefault`'s own docstring
            and this module's own Phase 20 design-decisions section below
            for the reconciliation mechanism this drives.
        versions: This standard's versions, ordered by `version_number` —
            mirrors `Requirement.versions`'s identical shape (the precedent
            this model explicitly follows), unlike `ComplianceRequirement`'s
            self-referential hierarchy below, which deliberately has no
            ORM `relationship()` (see this module's own docstring).
    """

    __tablename__ = "compliance_standards"
    __table_args__ = (UniqueConstraint("organization_id", "reference"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    reference: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    issuing_organisation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    applicability_default: Mapped[ComplianceStandardApplicabilityDefault] = mapped_column(
        str_enum(ComplianceStandardApplicabilityDefault, 30), default=ComplianceStandardApplicabilityDefault.OPT_IN
    )

    versions: Mapped[list[ComplianceStandardVersion]] = relationship(
        back_populates="standard", order_by="ComplianceStandardVersion.version_number"
    )


class ComplianceStandardVersion(UUIDPKMixin, TimestampMixin, Base):
    """A single version of a `ComplianceStandard` (§4) — e.g. "v1.1." Every
    version, published or retired, remains independently addressable
    indefinitely (see this module's own docstring for why this isn't a
    valid_from/valid_to temporal model): a `ProjectCompliance` assignment
    (Phase 7) references one specific version and must keep doing so even
    after newer versions are published (§4, §27, §31).

    Attributes:
        standard_id: The owning `ComplianceStandard`.
        version_number: Sequential ordering among this standard's versions
            (1, 2, 3, ...), used for `versions` ordering and to detect "is
            this the latest version" without string-parsing `version_label`.
        version_label: The human-facing version string (§4's examples:
            "1.0", "1.1", "2.0") — independent of `version_number` since a
            standard's own versioning scheme (semantic, date-based, ...) is
            display metadata, not this table's ordering key.
        status: Draft/published/retired lifecycle (§4) — see
            `ComplianceStandardVersionStatus`. A published version's
            requirements become immutable (enforced at the API layer,
            Phase 6); this table only records the state, not the
            enforcement.
        effective_date: When this version takes effect, where applicable
            (§2).
        change_note: Free-text summary of what changed relative to the
            previous version — supports §27's "users should be able to see
            what changed between standard versions" (full structured
            diffing is Phase 11; this is the author's own summary,
            mirroring `RequirementVersion.change_note`).
        created_by: The user who created this version.
        published_at / published_by / retired_at / retired_by: Lifecycle
            transition stamps, mirroring `Requirement.archived_at/
            archived_by`'s convention of a timestamp+actor pair per
            transition rather than overloading `updated_at`.
    """

    __tablename__ = "compliance_standard_versions"
    __table_args__ = (UniqueConstraint("standard_id", "version_number"),)

    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standards.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    version_label: Mapped[str] = mapped_column(String(50))
    status: Mapped[ComplianceStandardVersionStatus] = mapped_column(
        str_enum(ComplianceStandardVersionStatus, 20), default=ComplianceStandardVersionStatus.DRAFT
    )
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    standard: Mapped[ComplianceStandard] = relationship(back_populates="versions")


class ComplianceRequirement(UUIDPKMixin, TimestampMixin, Base):
    """A single compliance requirement within a standard version (§5) — e.g.
    "Equipment shall meet IPX9 water ingress requirements." Purely
    definitional: per §31, "A Compliance Requirement must not contain the
    compliance state of a project."

    Attributes:
        standard_version_id: The owning `ComplianceStandardVersion`.
        parent_requirement_id: Optional parent for section/subsection
            hierarchy (§5's "support hierarchy/parent-child relationships
            so that standards can be structured into sections and
            subsections"). A plain foreign key with no ORM `relationship()`
            — see this module's own docstring for why this mirrors
            `Project.parent_project_id` rather than `RequirementVersion`'s
            pattern. `ondelete="CASCADE"`: deleting a section requirement
            removes its subsections with it, unlike `Project`'s `SET NULL`
            (a compliance requirement has no "stand alone once detached"
            concept the way a project does).
        cloned_from_requirement_id: The requirement (in an earlier version
            of the same standard) this row was cloned from, if any — set by
            `router.py::_clone_requirement_tree` when a new draft version
            is created from an existing one; `None` for a requirement
            authored directly (never cloned) or whose lineage record has
            since been detached (see this module's own Phase 11 notes).
            `ondelete="SET NULL"`, deliberately *not* `CASCADE` (unlike
            `parent_requirement_id` above) — see this module's own Phase 11
            notes for the full reasoning. Consumed by `service.py::
            diff_standard_versions` (§27) to distinguish an unchanged/
            modified requirement (has lineage) from an added one (doesn't).
        reference: Optional section/clause numbering (e.g. "3.2.1"),
            distinct from the row's own UUID `id`.
        name: The requirement's own text/title.
        description: Free-text elaboration.
        reasoning: Why this requirement exists — mirrors `RequirementVersion.
            reasoning` (§5's "should support the information and metadata
            appropriate to existing ReqTrackManager requirements where
            practical").
        sort_order: Display/ordering position among sibling requirements.
        created_by: The user who created this requirement.
    """

    __tablename__ = "compliance_requirements"

    standard_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standard_versions.id", ondelete="CASCADE"), index=True
    )
    parent_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="CASCADE"), nullable=True, index=True
    )
    cloned_from_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ComplianceRequiredAction(UUIDPKMixin, TimestampMixin, Base):
    """A required action definition needed to demonstrate a compliance
    requirement is met (§6) — e.g. "Perform IPX9 water ingress test."
    "Required Action" rather than "Test," since demonstrating compliance may
    involve activities other than testing (§6).

    Purely definitional, like `ComplianceRequirement` — the per-project
    assessment of a required action (status, assignee, due date, completion
    information, evidence) is Phase 7's "Required Action Assessment" (§25),
    not this row; see this module's own docstring.

    Attributes:
        requirement_id: The owning `ComplianceRequirement`. A plain
            one-to-many foreign key, not a many-to-many link table — see
            this module's own docstring for why this differs from
            `RequirementAction`/`RequirementActionLink`.
        action_type_id: Which `ComplianceActionTypeDefinition` this action
            is. No `ondelete` (implicit RESTRICT), mirroring
            `RequirementAction.action_type_id` exactly — an in-use action
            type must not be deletable out from under it.
        name: The action's own name/description (§6).
        description: Free-text elaboration.
        is_mandatory: Whether this action is mandatory for the requirement
            to be considered met (§6).
        sort_order: Display/ordering position among sibling required
            actions.
        created_by: The user who created this required action.
    """

    __tablename__ = "compliance_required_actions"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="CASCADE"), index=True
    )
    action_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_action_type_definitions.id")
    )
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ComplianceActionTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """An organisation-defined required-action type (e.g. "Test,"
    "Inspection," "Document Review") — mirrors `ActionTypeDefinition`'s
    existing extensible-vocabulary pattern (§6), but organisation-scoped
    rather than project-scoped; see this module's own docstring for why.

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique within the organisation.
        sort_order: Display/picker order among the organisation's action
            types.
    """

    __tablename__ = "compliance_action_type_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# --- Phase 7: project-specific compliance assessment ----------------------------


class ProjectCompliance(UUIDPKMixin, TimestampMixin, Base):
    """A project's assignment to one specific `ComplianceStandardVersion`
    (§7) — e.g. "Project A is assigned to Corporate Security Standard
    v3.1." The same standard may be assigned to many projects, and the
    same project may be assigned many standards (§7's own worked example);
    each `(project_id, standard_version_id)` pair is exactly one row.

    Attributes:
        project_id: The assigned project.
        standard_version_id: The specific standard version assigned — must
            be `PUBLISHED` at assignment time (enforced at the API layer,
            never a `DRAFT` or already-`RETIRED` version — see this
            module's own docstring). Stays pointed at this exact version
            row forever, even after that version is later retired or a
            newer version is published (§4, §27) — migrating to a newer
            version is a distinct, explicit, user-triggered action (Phase
            11), never an implicit effect of this row's own lifecycle.
        assigned_at / assigned_by: When/who made this assignment (§7's
            "Date assigned").
        target_compliance_date: Optional target date for the project to
            reach full compliance (§7) — distinct from any individual
            required action's own due date.
        target_date_reminder_sent_at / target_date_overdue_notified_at:
            Phase 10 (§18/§28) sweep bookkeeping — stamped the first time
            the "target date approaching"/"target date exceeded"
            notification has been sent for the *current*
            `target_compliance_date`, so the daily sweep
            (`scheduler.py::send_target_date_notifications`) never repeats
            either notification. Mirrors `RequirementVersion.review_
            reminder_sent_at`'s own single-stamp convention, split into two
            columns since "approaching" and "exceeded" are two independent
            notifications here (§18 lists them separately), not one.
        is_archived / archived_at / archived_by: Soft-delete, mirroring
            `ComplianceStandard`'s own convention — used when a project no
            longer needs to track compliance against this standard.
            Deliberately never a hard delete: the `ProjectComplianceRequirement`
            rows underneath carry real assessment/audit history (§16) that
            must survive a project deciding to stop tracking a standard.
    """

    __tablename__ = "project_compliances"
    __table_args__ = (UniqueConstraint("project_id", "standard_version_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    standard_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standard_versions.id"), index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    target_compliance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_date_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_date_overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ComplianceStandardDefaultExclusion(UUIDPKMixin, TimestampMixin, Base):
    """Records that a specific project is excepted out of a standard's
    `APPLIES_TO_ALL_PROJECTS` default (Phase 20) — the "...except" half of
    "applies to all projects by default, except...". A project on this list
    is never touched by `service.py::reconcile_standard_applicability`
    while the exclusion row exists; removing it (not deleting a
    `ComplianceStandard`/`Project` row) restores the project to the
    standard's default reconciliation the next time it runs, per this
    module's own `on_project_created`-style "reconciled at the moment of
    the triggering event" convention.

    Attributes:
        standard_id: The `ComplianceStandard` this exclusion applies to.
        project_id: The excluded project — must belong to the same
            organisation as `standard_id` (enforced at the API layer, this
            table carries no cross-table `CHECK`).
        excluded_by: The user (a Compliance Manager, or org/server admin)
            who added this exclusion.
        excluded_at: When the exclusion was added.
        reason: Mandatory justification (§16's established convention,
            mirroring the Not-Applicable/Non-Compliant/Rejection
            mandatory-rationale rule already enforced elsewhere in this
            module) — enforced at the API layer, not a DB constraint, same
            as every other mandatory-justification field in this module.
    """

    __tablename__ = "compliance_standard_default_exclusions"
    __table_args__ = (UniqueConstraint("standard_id", "project_id"),)

    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standards.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    excluded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    excluded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, default="")


class ProjectComplianceRequirement(UUIDPKMixin, TimestampMixin, Base):
    """One project's assessment of one `ComplianceRequirement` (§8) —
    "Requirement 1 -> Compliant" in §8's own worked example. Deliberately
    separate from `ComplianceRequirement` itself: the same requirement has
    a different `ProjectComplianceRequirement` row per project that's
    assigned the standard it belongs to (§8: "This allows the same
    requirement to have different compliance states for different
    projects").

    One row exists per `(project_compliance_id, requirement_id)` pair,
    materialised in full when the owning `ProjectCompliance` is created —
    see this module's own docstring.

    Attributes:
        project_compliance_id: The owning `ProjectCompliance` assignment.
        requirement_id: The `ComplianceRequirement` this row assesses.
        explicit_applicability: This row's own, directly-set applicability
            decision, or `None` if never explicitly set (§9). See this
            module's own docstring for why `None` is distinct from an
            explicit `APPLICABLE`. The *effective* applicability (after
            hierarchical inheritance, §9's "Hierarchical Applicability") is
            never stored — it's computed by `service.py::
            resolve_applicability`.
        justification: Mandatory (enforced at the API layer, not a NOT NULL
            constraint) when `explicit_applicability` is being set to
            `NOT_APPLICABLE` (§9) or `compliance_status` is being set to
            `NON_COMPLIANT` (§16) — see this module's own docstring for why
            one field serves both.
        notes: Free-text notes (§8), independent of `justification`.
        compliance_status: This project's assessed compliance state
            against this requirement (§10), independent of applicability
            (§10: "Applicability should remain separate from compliance
            status").
        assessed_at / assessed_by: When/who last changed `compliance_status`
            (§8's "Assessment date"/"Assessed by") — set automatically by
            the assessment endpoint, never caller-supplied.
        applicability_set_at / applicability_set_by: When/who last changed
            `explicit_applicability` — set automatically by the
            applicability endpoint, never caller-supplied. `None` until
            `explicit_applicability` is set for the first time.
        approval_state: The row's current position in §12's approval/
            sign-off state machine — see this module's own Phase 9 notes
            and `service.py` for the transition rules.
        approval_decided_at / approval_decided_by: When/who last decided
            this row's `approval_state` at the `approve`/`reject` step
            (§12's "Date/time of approval"/"Who approved/signed off") —
            `None` until the first such decision. Not set by `submit-for-
            approval` (that's a request, not a decision) or by the
            automatic transitions in `service.py` (those are system-
            derived, not a human decision).
        decision_note: Free-text rationale attached to the last `approve`/
            `reject` decision — mandatory (enforced at the API layer) for
            a rejection, optional for an approval. Independent of
            `justification`/`notes` (Phase 7's own assessment/applicability
            fields), which this column never overwrites or reads from.
    """

    __tablename__ = "project_compliance_requirements"
    __table_args__ = (UniqueConstraint("project_compliance_id", "requirement_id"),)

    project_compliance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_compliances.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id"), index=True
    )
    explicit_applicability: Mapped[ComplianceApplicability | None] = mapped_column(
        str_enum(ComplianceApplicability, 20), nullable=True
    )
    justification: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    compliance_status: Mapped[ComplianceStatus] = mapped_column(
        str_enum(ComplianceStatus, 20), default=ComplianceStatus.NOT_STARTED
    )
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assessed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    applicability_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applicability_set_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approval_state: Mapped[ComplianceApprovalState] = mapped_column(
        str_enum(ComplianceApprovalState, 24), default=ComplianceApprovalState.NOT_ASSESSED
    )
    approval_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decision_note: Mapped[str] = mapped_column(Text, default="")


class ComplianceRequiredActionAssessment(UUIDPKMixin, TimestampMixin, Base):
    """One project's assessment of one `ComplianceRequiredAction` (§6's
    "Status, Assignee, Due date, Completion information," §25's "Required
    Action Assessments" nested under "Project Compliance Requirements").

    One row exists per `(project_compliance_requirement_id,
    required_action_id)` pair, materialised in full alongside its owning
    `ProjectComplianceRequirement` — see this module's own docstring.

    Attributes:
        project_compliance_requirement_id: The owning per-project
            requirement assessment.
        required_action_id: The `ComplianceRequiredAction` this row
            assesses.
        assignee_id: Who is responsible for this required action, or
            `None` if unassigned (§6's "Assignee").
        due_date: Optional due date (§6).
        due_reminder_sent_at / overdue_notified_at: Phase 10 (§18/§28) sweep
            bookkeeping — stamped the first time the "approaching due
            date"/"overdue" notification has been sent for the *current*
            `due_date`, so `scheduler.py::send_required_action_due_
            notifications`'s daily sweep never repeats either notification.
            Reset to `None` (by the same PATCH that changes `due_date`) so a
            rescheduled due date gets its own fresh reminder cycle rather
            than silently inheriting the old date's "already reminded"
            state.
        is_completed / completed_at / completed_by: Completion overlay,
            mirroring `Requirement.completed_at`'s own shape — see this
            module's own docstring for why this shape rather than reusing
            `ComplianceStatus`.
        notes: Free-text notes.
    """

    __tablename__ = "compliance_required_action_assessments"
    __table_args__ = (
        UniqueConstraint("project_compliance_requirement_id", "required_action_id"),
        # Explicit, shortened index name: `index=True`'s auto-generated
        # `ix_compliance_required_action_assessments_project_compliance_
        # requirement_id` is 75 characters, over Postgres's 63-byte
        # identifier limit — Postgres silently truncates it at DDL time,
        # which then never matches SQLAlchemy's own (untruncated) computed
        # name and permanently fails `test_schema_migrations_match_models.py`
        # regardless of what the migration itself names it. No other
        # table/column combination in this codebase is long enough to hit
        # this limit (confirmed by inspecting every table's own indexes).
        Index(
            "ix_required_action_assessments_pcr_id", "project_compliance_requirement_id"
        ),
    )

    project_compliance_requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_compliance_requirements.id", ondelete="CASCADE")
    )
    required_action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_required_actions.id"), index=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


# --- Phase 8: Evidence -----------------------------------------------------------


class ComplianceEvidence(UUIDPKMixin, TimestampMixin, Base):
    """A piece of supporting evidence for one or more of a project's
    compliance assessments (§13) — e.g. "IPX9 Test Certificate." Project-
    scoped, not standard/requirement-scoped: see this module's own
    docstring for why.

    Attributes:
        project_id: The owning project.
        title: Short display name (§13's own worked example: "IPX9 Test
            Certificate").
        description: Free-text elaboration.
        issuing_organisation: The external body/person that issued this
            evidence, where applicable (§14) — e.g. a test lab's name.
        issued_date: When this evidence was issued (§13/§14's "Issue
            date"), distinct from `provided_at` (when it was uploaded into
            this system).
        expiry_date: This evidence's *current* effective expiry (§14),
            nullable — not every piece of evidence expires. Updated in
            place by a revalidation; see this module's own docstring for
            why the *previous* value is never lost.
        provided_by / provided_at: Who supplied this evidence and when
            (§13) — set automatically at creation, never caller-supplied,
            mirroring `ProjectCompliance.assigned_at`/`assigned_by`'s own
            convention.
        notes: Free-text notes, independent of `description`.
        expiry_reminder_sent_at / expiry_notified_at: Phase 10 (§18/§28)
            sweep bookkeeping — mirrors `ComplianceRequiredActionAssessment.
            due_reminder_sent_at`/`overdue_notified_at`'s own shape,
            stamped by `scheduler.py::send_evidence_expiry_notifications`
            so its daily sweep never repeats the "approaching expiry"/
            "expired" notification for the same `expiry_date`. Reset to
            `None` by `revalidate_evidence` (the only endpoint that changes
            `expiry_date`), so a revalidated expiry gets its own fresh
            reminder cycle.
        is_archived / archived_at / archived_by: Whether this evidence
            "remains applicable" (§13) — see this module's own docstring
            for why this is a soft-delete, not a hard one.
    """

    __tablename__ = "compliance_evidence"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    issuing_organisation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    provided_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    provided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")
    expiry_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ComplianceEvidenceRevalidation(UUIDPKMixin, Base):
    """One revalidation event for a `ComplianceEvidence` row (§15) —
    append-only, never updated: mirrors `app.models.file.RequirementFile`'s
    own "no `updated_at`, insert-only" shape (a plain `created_at` column
    rather than `TimestampMixin`), for the same reason — this row is never
    mutated after creation.

    Attributes:
        evidence_id: The `ComplianceEvidence` this revalidation applies to.
        revalidated_by / revalidated_at: Who revalidated and when (§15).
        previous_expiry_date: `ComplianceEvidence.expiry_date`'s value
            immediately before this revalidation (`None` if it had none) —
            this is what makes the history genuinely retained rather than
            reconstructible only from timestamps.
        new_expiry_date: The new validity/expiry date this revalidation
            sets (§15) — mirrors `ComplianceEvidence.expiry_date`'s value
            immediately after this event is applied.
        justification: Optional free-text justification (§15).
    """

    __tablename__ = "compliance_evidence_revalidations"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_evidence.id", ondelete="CASCADE"), index=True
    )
    revalidated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    revalidated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    justification: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ComplianceEvidenceFile(UUIDPKMixin, Base):
    """Links a file (direct upload, or an organisation shared resource) to
    a `ComplianceEvidence` row — the exact shape of `app.models.file.
    RequirementFile`; see this module's own docstring for why this lives
    here rather than reusing that table directly. No `index=True` on
    either foreign key, mirroring `RequirementFile`'s own
    unindexed-beyond-primary-key convention for this exact join-table
    shape."""

    __tablename__ = "compliance_evidence_files"
    __table_args__ = (UniqueConstraint("evidence_id", "file_id"),)

    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_evidence.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ComplianceEvidenceRequirementLink(UUIDPKMixin, Base):
    """Links one `ComplianceEvidence` row to one
    `ProjectComplianceRequirement` row (§13's "a requirement... should be
    able to reference supporting evidence" / "a single piece of evidence
    should be capable of supporting multiple compliance requirements").
    Deliberately points at the project-specific assessment row, not the
    reusable `ComplianceRequirement` definition — see this module's own
    docstring. No `index=True` on either foreign key, mirroring
    `RequirementFile`'s own convention for this exact join-table shape
    (and avoiding this exact table/column combination's auto-generated
    index name exceeding Postgres's 63-byte identifier limit, the same
    class of problem `ComplianceRequiredActionAssessment`'s own comment
    already documents for a different table)."""

    __tablename__ = "compliance_evidence_requirement_links"
    __table_args__ = (UniqueConstraint("evidence_id", "project_compliance_requirement_id"),)

    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_evidence.id", ondelete="CASCADE"))
    project_compliance_requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_compliance_requirements.id", ondelete="CASCADE")
    )
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ComplianceEvidenceActionLink(UUIDPKMixin, Base):
    """Links one `ComplianceEvidence` row to one
    `ComplianceRequiredActionAssessment` row (§13's "...or Required Action
    should be able to reference supporting evidence") — the required-
    action-assessment equivalent of `ComplianceEvidenceRequirementLink`
    above; see that model's own docstring for why this points at the
    project-specific assessment layer, not the reusable definition, and
    for why neither foreign key here is indexed."""

    __tablename__ = "compliance_evidence_action_links"
    __table_args__ = (UniqueConstraint("evidence_id", "required_action_assessment_id"),)

    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_evidence.id", ondelete="CASCADE"))
    required_action_assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_required_action_assessments.id", ondelete="CASCADE")
    )
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Phase 10: Scheduled reviews --------------------------------------------------


class ComplianceReview(UUIDPKMixin, TimestampMixin, Base):
    """A scheduled compliance review (§17) — either of a `ComplianceStandard`
    itself, or of one project's compliance assignment (`ProjectCompliance`).
    Exactly one of `standard_id`/`project_compliance_id` is set; see this
    module's own docstring for why these are separate owners rather than a
    shared "reviewable" abstraction.

    Attributes:
        standard_id: The `ComplianceStandard` this review is scheduled
            against, or `None` if this is a project-level review.
        project_compliance_id: The `ProjectCompliance` assignment this
            review is scheduled against, or `None` if this is a
            standard-level review.
        frequency_label: Free-text display of the review's cadence (§17's
            "Review frequency"), e.g. "Annual," "Six-monthly," "Before
            product release" — display metadata, not itself the scheduling
            mechanism (`recurrence_days` is).
        recurrence_days: Days between cycles, or `None` for a one-off
            review that doesn't automatically recur once completed (see
            `service.py::complete_review`).
        next_due_date: This cycle's due date (§17's "Next review date").
            Never itself computed as "upcoming/due/overdue" — see
            `service.py::compute_review_schedule_state`.
        owner_id: Who is responsible for performing this review (§17's
            "Review owner"), or `None` if not yet assigned.
        status: `SCHEDULED` or `COMPLETED` — see `ComplianceReviewStatus`'s
            own docstring for why there's no separate overdue/cancelled
            member.
        notes: Free-text notes (§17), independent of the evidence linkage
            below.
        outcome: Set only on completion (§17's "Review outcome") — `None`
            while `SCHEDULED`.
        completed_at / completed_by: When/who completed this review — set
            automatically by `service.py::complete_review`, `None` while
            `SCHEDULED`.
        created_by: The user who scheduled this review.
        due_reminder_sent_at / overdue_notified_at: Sweep bookkeeping,
            mirroring `ComplianceRequiredActionAssessment`'s own pair —
            see `scheduler.py::send_review_due_notifications`.
    """

    __tablename__ = "compliance_reviews"
    __table_args__ = (
        CheckConstraint(
            "(standard_id IS NOT NULL) != (project_compliance_id IS NOT NULL)",
            name="ck_compliance_reviews_exactly_one_owner",
        ),
    )

    standard_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standards.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_compliance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_compliances.id", ondelete="CASCADE"), nullable=True, index=True
    )
    frequency_label: Mapped[str] = mapped_column(String(100))
    recurrence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_due_date: Mapped[date] = mapped_column(Date)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[ComplianceReviewStatus] = mapped_column(
        str_enum(ComplianceReviewStatus, 20), default=ComplianceReviewStatus.SCHEDULED
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[ComplianceReviewOutcome | None] = mapped_column(str_enum(ComplianceReviewOutcome, 20), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    due_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplianceReviewEvidenceLink(UUIDPKMixin, Base):
    """Links one `ComplianceEvidence` row to one `ComplianceReview` (§17's
    "Notes/evidence associated with the review") — the review equivalent of
    `ComplianceEvidenceRequirementLink`; see that model's own docstring for
    why neither foreign key here is indexed. Only ever created for a
    project-scoped review (`ComplianceReview.project_compliance_id` set) —
    enforced at the API layer, since evidence is inherently project-scoped
    and a standard-level review has no project to share with it."""

    __tablename__ = "compliance_review_evidence_links"
    __table_args__ = (UniqueConstraint("evidence_id", "review_id"),)

    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_evidence.id", ondelete="CASCADE"))
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_reviews.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Phase 11: Cross-standard mapping + version impact -----------------------------


class ComplianceMappingRelationshipTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """An organisation-defined cross-standard-mapping relationship type
    (e.g. "Equivalent," "Satisfies," "Derived From," "Related To,"
    "Overlaps," "Conflicts With") — mirrors `ComplianceActionTypeDefinition`'s
    existing extensible-vocabulary pattern (§19: "exact relationship types
    should be configurable or extensible where practical"); see this
    module's own Phase 11 notes for why this uses a *shorter* table name
    than its column names would otherwise suggest.

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique within the organisation.
        sort_order: Display/picker order among the organisation's
            relationship types.
        implies_equivalence: Whether this relationship type is strong
            enough that a `replaced` version-diff pair linked by it (§27)
            may have its project-specific assessment carried forward during
            migration (`service.py::migrate_project_compliance`), subject
            to the compliance officer's own explicit, per-requirement
            confirmation at migration time — never automatic. Defaults
            `False`: an org must deliberately mark a type (e.g. "Equivalent")
            as strong enough for this before it can ever be offered, so a
            weaker type (e.g. "Related To," "Overlaps") can never be used
            this way by default. See this module's own Phase 11 notes
            (below) for the full reasoning and why this doesn't reopen
            §19's "must not imply... satisfying" guarantee.
    """

    __tablename__ = "compliance_mapping_relationship_types"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    implies_equivalence: Mapped[bool] = mapped_column(Boolean, default=False)


class ComplianceRequirementMapping(UUIDPKMixin, TimestampMixin, Base):
    """A directed relationship between two `ComplianceRequirement` rows
    (§19's cross-standard mapping) — e.g. "ISO 27001 A.5.15 Equivalent
    Corporate Security Standard 3.0 SEC-12." See this module's own Phase 11
    notes for why this single table also serves §27's "replaced"/
    "re-mapped" version-diff categories (a same-standard, cross-*version*
    link), why the relationship is directed, and why the org scope is
    denormalised onto this row directly.

    Attributes:
        organization_id: The organisation both mapped requirements belong
            to (denormalised from their own standards) — the scoping
            anchor for this module's usual "404, not 403" cross-org
            isolation check.
        from_requirement_id / to_requirement_id: The two mapped
            `ComplianceRequirement` rows. `CheckConstraint` below rules out
            `from_requirement_id == to_requirement_id`. `ondelete="CASCADE"`
            on both — a mapping referencing a requirement that no longer
            exists (only possible for a still-`DRAFT` version's
            requirements, since a published version's requirements are
            immutable and never deleted) has nothing left to mean.
        relationship_type_id: Which `ComplianceMappingRelationshipTypeDefinition`
            this mapping is. No `ondelete` (implicit RESTRICT), mirroring
            `ComplianceRequiredAction.action_type_id` — an in-use
            relationship type must not be deletable out from under it.
        notes: Free-text notes (§19 names no specific field list beyond the
            relationship type itself, but every other definitional entity
            in this module carries a notes/description field for the same
            "why this link exists" context).
        created_by: The user who created this mapping (§19: "must be...
            auditable" — this plus `TimestampMixin.created_at`/
            `services.audit.log_event` on the creating endpoint satisfy
            that, mirroring every other entity in this module rather than
            a bespoke mapping-history mechanism).
        is_archived / archived_at / archived_by: Soft-delete, mirroring
            every other entity in this module — a mapping is retained
            audit history once created, not hard-deleted.
    """

    __tablename__ = "compliance_requirement_mappings"
    __table_args__ = (
        UniqueConstraint("from_requirement_id", "to_requirement_id", "relationship_type_id"),
        CheckConstraint(
            "from_requirement_id != to_requirement_id", name="ck_compliance_requirement_mappings_no_self_link"
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    from_requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="CASCADE"), index=True
    )
    to_requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="CASCADE"), index=True
    )
    relationship_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_mapping_relationship_types.id")
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
