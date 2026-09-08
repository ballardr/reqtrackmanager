"""
Module: modules.compliance.schemas

Pydantic request/response models for the Compliance Module's Phase 6
Standards Management API (docs/compliance-module-plan.md Phase 6;
docs/Compliance_Module_Requirements.md §2-§6). Sits alongside `models.py`
(the Phase 5 ORM shape these schemas expose over HTTP) and `router.py`
(the endpoints that use them).

Design decisions, not left implicit:
- Every `*Out` schema sets `model_config = {"from_attributes": True}`, this
  codebase's standard convention for a schema built directly from an ORM
  instance (see `schemas/action_type.py`, `schemas/project.py`).
- `ComplianceStandardOut` is deliberately flat/summary-only — it does not
  nest `versions`, matching how other list-friendly `*Out` schemas in this
  codebase avoid embedding a full child collection by default (e.g.
  `ProjectOut` does not embed `Requirement` rows). A caller fetches a
  standard's versions via the separate `GET .../standards/{id}/versions`
  endpoint instead.
- `ComplianceRequirementCreate`/`Update` deliberately have no `sort_order`
  field — a new requirement is always appended to the end of its sibling
  group (mirroring `action_types.py::create_action_type`'s `count = len(...)`
  pattern), and reordering afterward goes through the dedicated `move`
  endpoint (`services.ordering.move_ordered`), never a direct field write.
  The same applies to `ComplianceRequiredActionCreate`/`Update`.
- `ComplianceRequirementUpdate` has no `parent_requirement_id` field —
  reparenting a requirement to a different parent is not requested by
  Phase 6's spec and would complicate the sibling-group semantics `move`
  relies on (a requirement's sibling group is its
  `(standard_version_id, parent_requirement_id)` pair); a future phase can
  add a dedicated reparent endpoint if this is ever needed.
- `ComplianceStandardUpdate` has no `reference` field — a standard's
  `reference` is its stable, organisation-unique identifier and is treated
  as immutable after creation, the same way this codebase never lets a
  project's own generated `unique_code` change; simply omitting the field
  from the update schema is what enforces this (there is no direct
  precedent for this specific field in this codebase, so this is a new,
  deliberate judgment call — see docs/compliance-module-plan.md's "Phase 6
  notes").
- Phase 8 (§13-§15, Evidence) adds its own schemas at the bottom of this
  file: `ComplianceEvidenceUpdate` deliberately excludes `expiry_date`
  (§15's revalidation-only rule — see that schema's own docstring), and
  `ComplianceEvidenceOut` is built explicitly by the router rather than
  `from_attributes` alone, for the same "computed field" reason as
  `ProjectComplianceRequirementOut`.
- Phase 9 (§12, §16, §27, Approval/Sign-off) adds `ComplianceApprovalDecisionRequest`
  (payload for both `approve` and `reject` — `decision_note` is required at
  the API layer, not the schema layer, exactly when rejecting, mirroring
  every other conditionally-mandatory-justification rule in this module)
  and `PendingApprovalOut` (mirrors `NonCompliantRequirementOut`'s exact
  shape/rationale for the same kind of cross-assignment drillable list, one
  section up).
- Phase 10 (§17, Scheduled Reviews) adds `ComplianceReviewCreate`/`Update`/
  `CompleteRequest`/`Out` and `ComplianceReviewEvidenceLinkCreate` at the
  bottom of this file. `ComplianceReviewOut.schedule_state` is a computed
  field (never stored — see `service.py::compute_review_schedule_state`),
  the same "built explicitly by the router" shape as `ComplianceEvidenceOut.
  validity_state`.
- Phase 11 (§19, §27, Cross-Standard Mapping + Version Impact) adds
  `ComplianceMappingRelationshipType*` (the org-scoped vocabulary,
  mirroring `ComplianceActionType*`'s exact shape one section up),
  `ComplianceRequirementMapping*`, the version-diff response shapes
  (`ComplianceRequirementSummaryOut` plus one `*Out` per §27 diff
  category), and the version-migration request/result shapes
  (`ProjectComplianceMigration*`) at the bottom of this file. Every diff/
  migration-result schema is built explicitly by the router/service layer
  from computed data (`service.py::diff_standard_versions`/`migrate_
  project_compliance`), never `from_attributes` alone, the same reason
  `ProjectComplianceRequirementOut`/`ComplianceEvidenceOut`/
  `ComplianceReviewOut` already are.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.compliance.enums import (
    ComplianceApplicability,
    ComplianceApplicabilitySource,
    ComplianceApprovalState,
    ComplianceEvidenceValidityState,
    ComplianceReviewOutcome,
    ComplianceReviewStatus,
    ComplianceStandardVersionStatus,
    ComplianceStatus,
)

# --- Standards ---------------------------------------------------------------


class ComplianceStandardCreate(BaseModel):
    """Payload for creating a `ComplianceStandard` (§2). `owner_id` defaults
    to the creating user when omitted — §2 lists "Owner" as an attribute
    without mandating it always differ from the creator.

    Also carries the fields for the standard's mandatory first
    `ComplianceStandardVersion` (version 1), created in the same request/
    transaction by `router.py::create_standard` — mirroring
    `ComplianceStandardVersionCreate`'s own `version_label`/`effective_date`/
    `change_note` fields (minus `clone_from_version_id`, which has nothing
    to clone from on a brand-new standard). A standard is never left with
    zero versions: previously, creating a standard and creating its first
    version were two separate API calls, which could leave a standard
    version-less if the second call was never made."""

    reference: str
    name: str
    description: str = ""
    issuing_organisation: str | None = None
    owner_id: UUID | None = None
    initial_version_label: str
    initial_version_effective_date: date | None = None
    initial_version_change_note: str = ""


class ComplianceStandardUpdate(BaseModel):
    """Update payload — deliberately excludes `reference` (immutable after
    creation, see this module's docstring)."""

    name: str
    description: str = ""
    issuing_organisation: str | None = None
    owner_id: UUID


class ComplianceStandardOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    reference: str
    name: str
    description: str
    issuing_organisation: str | None
    owner_id: UUID
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None
    created_at: datetime
    updated_at: datetime


# --- Standard versions --------------------------------------------------------


class ComplianceStandardVersionCreate(BaseModel):
    """Payload for creating a new `ComplianceStandardVersion` (§4).
    `version_number` is never supplied by the caller — the router always
    assigns the next sequential number for the owning standard.

    `clone_from_version_id`, when given, deep-copies that version's full
    requirement tree (and each requirement's required actions) into the
    new (always-draft) version — see `router.py::create_standard_version`'s
    docstring for why this exists and how it's implemented."""

    version_label: str
    effective_date: date | None = None
    change_note: str = ""
    clone_from_version_id: UUID | None = None


class ComplianceStandardVersionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    standard_id: UUID
    version_number: int
    version_label: str
    status: ComplianceStandardVersionStatus
    effective_date: date | None
    change_note: str
    created_by: UUID
    published_at: datetime | None
    published_by: UUID | None
    retired_at: datetime | None
    retired_by: UUID | None
    created_at: datetime
    updated_at: datetime


# --- Requirements --------------------------------------------------------------


class ComplianceRequirementCreate(BaseModel):
    """Payload for creating a `ComplianceRequirement` (§5). No `sort_order`
    (always appended) — see this module's docstring."""

    parent_requirement_id: UUID | None = None
    reference: str | None = None
    name: str
    description: str = ""
    reasoning: str = ""


class ComplianceRequirementUpdate(BaseModel):
    """Update payload — no `parent_requirement_id`/`sort_order` (see this
    module's docstring: reparenting isn't supported by this phase, and
    reordering is a separate `move` endpoint)."""

    reference: str | None = None
    name: str
    description: str = ""
    reasoning: str = ""


class ComplianceRequirementOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    standard_version_id: UUID
    parent_requirement_id: UUID | None
    reference: str | None
    name: str
    description: str
    reasoning: str
    sort_order: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime


# --- Required actions ----------------------------------------------------------


class ComplianceRequiredActionCreate(BaseModel):
    """Payload for creating a `ComplianceRequiredAction` (§6). No
    `sort_order` (always appended) — see this module's docstring."""

    action_type_id: UUID
    name: str
    description: str = ""
    is_mandatory: bool = True


class ComplianceRequiredActionUpdate(BaseModel):
    action_type_id: UUID
    name: str
    description: str = ""
    is_mandatory: bool = True


class ComplianceRequiredActionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    requirement_id: UUID
    action_type_id: UUID
    name: str
    description: str
    is_mandatory: bool
    sort_order: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime


# --- Action types (organisation-scoped vocabulary) ------------------------------


class ComplianceActionTypeCreate(BaseModel):
    name: str


class ComplianceActionTypeUpdate(BaseModel):
    """Rename payload — mirrors `schemas.action_type.ActionTypeUpdate`:
    every `ComplianceRequiredAction.action_type_id` reference points at
    this row's id, never its name, so renaming never disturbs any
    required action currently of this type."""

    name: str


class ComplianceActionTypeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    sort_order: int


# --- Phase 7: project-specific compliance assessment ----------------------------


class ProjectComplianceCreate(BaseModel):
    """Payload for assigning a standard version to a project (§7).
    `standard_id` is redundant with `standard_version_id` (a version
    already identifies its standard) but required anyway so the URL/path
    and the payload agree on which standard is being assigned — the router
    still verifies `standard_version_id` actually belongs to `standard_id`
    (`router.py::_get_version_or_404`), the same cross-check every other
    Phase 6 endpoint already performs."""

    standard_id: UUID
    standard_version_id: UUID
    target_compliance_date: date | None = None


class ProjectComplianceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    standard_version_id: UUID
    assigned_at: datetime
    assigned_by: UUID
    target_compliance_date: date | None
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectComplianceApplicabilityUpdate(BaseModel):
    """Payload for `PATCH .../requirements/{id}/applicability` (§9).
    `justification` is required by the router (400, not a schema-level
    validator) exactly when `applicability == NOT_APPLICABLE` — see
    `project_router.py::update_requirement_applicability`."""

    applicability: ComplianceApplicability
    justification: str = ""


class ProjectComplianceAssessmentUpdate(BaseModel):
    """Payload for `PATCH .../requirements/{id}/assessment` (§10, §16).
    `justification` is required by the router (400, not a schema-level
    validator) exactly when `compliance_status == NON_COMPLIANT` — see
    `project_router.py::update_requirement_assessment`."""

    compliance_status: ComplianceStatus
    justification: str = ""
    notes: str = ""


class ProjectComplianceRequirementOut(BaseModel):
    """Response shape for one `ProjectComplianceRequirement` row, plus its
    *computed* (never stored) effective applicability and source — see
    `service.py::resolve_applicability`. Built explicitly by the router
    (not `from_attributes` alone), since `effective_applicability`/
    `applicability_source` aren't ORM columns."""

    id: UUID
    project_compliance_id: UUID
    requirement_id: UUID
    explicit_applicability: ComplianceApplicability | None
    effective_applicability: ComplianceApplicability
    applicability_source: ComplianceApplicabilitySource
    justification: str
    notes: str
    compliance_status: ComplianceStatus
    assessed_at: datetime | None
    assessed_by: UUID | None
    applicability_set_at: datetime | None
    applicability_set_by: UUID | None
    approval_state: ComplianceApprovalState
    approval_decided_at: datetime | None
    approval_decided_by: UUID | None
    decision_note: str
    created_at: datetime
    updated_at: datetime


class ComplianceRequiredActionAssessmentUpdate(BaseModel):
    """Payload for `PATCH .../required-action-assessments/{id}` (§6) —
    assignee/due date/notes only. Completion is a separate `complete`/
    `uncomplete` action endpoint, mirroring `Requirement`'s own
    `complete_requirement`/`uncomplete_requirement` shape, not a field
    write here."""

    assignee_id: UUID | None = None
    due_date: date | None = None
    notes: str = ""


class ComplianceRequiredActionAssessmentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_compliance_requirement_id: UUID
    required_action_id: UUID
    assignee_id: UUID | None
    due_date: date | None
    is_completed: bool
    completed_at: datetime | None
    completed_by: UUID | None
    notes: str
    created_at: datetime
    updated_at: datetime


class ProjectComplianceStatusOut(BaseModel):
    """§20's overall status summary for one `ProjectCompliance` assignment
    — see `service.py::summarize_project_compliance` for the exact,
    documented calculation this schema exposes. Always includes the raw
    counts alongside the calculated percentage, per §20's explicit "the UI
    should always display the actual counts as well as any calculated
    percentage so that the percentage cannot be misleading.\"

    `project_name` was added in Phase 14: this schema was already the one
    exception to every other cross-assignment schema in this module in
    being shared, unmodified, between project scope (`GET .../status`) and
    org scope (`router.py::list_all_project_compliance`) since Phase 7 —
    `project_id` has sat here, redundant at project scope, from the start
    for exactly that reason. Phase 14's own org-wide "Standard | Projects |
    Compliant | Non-Compliant | In Progress" table (§22) needs a project's
    display name to group/label its rows, so it extends this schema's
    existing dual-use design rather than introducing a third pattern next
    to the `Org*Out` subclass approach used for the module's other,
    project-scope-first schemas (see this file's own Phase 14 section,
    below, for that approach and why it doesn't apply here)."""

    project_compliance_id: UUID
    project_id: UUID
    project_name: str
    standard_id: UUID
    standard_reference: str
    standard_name: str
    standard_version_id: UUID
    version_label: str
    target_compliance_date: date | None
    assigned_at: datetime
    total_requirements: int
    applicable_count: int
    not_applicable_count: int
    counts_by_status: dict[str, int]
    compliance_percentage: float
    has_non_compliant: bool
    overall_compliance_state: Literal["compliant", "non_compliant", "in_progress", "not_applicable"]
    overall_approval_state: ComplianceApprovalState


class NonCompliantRequirementOut(BaseModel):
    """One row of `GET .../non-compliant-requirements` (§20/§21 — "Non-
    Compliant requirements" as a distinct, drillable list, not just a
    count)."""

    project_compliance_id: UUID
    standard_reference: str
    standard_name: str
    version_label: str
    project_compliance_requirement_id: UUID
    requirement_id: UUID
    requirement_reference: str | None
    requirement_name: str
    justification: str
    notes: str
    assessed_at: datetime | None
    assessed_by: UUID | None


# --- Phase 8: Evidence ----------------------------------------------------------


class ComplianceEvidenceCreate(BaseModel):
    """Payload for creating a `ComplianceEvidence` row (§13). `provided_by`/
    `provided_at` are never caller-supplied — the router always sets them
    to the current user/now, mirroring `ProjectCompliance.assigned_at`/
    `assigned_by`'s own convention. `project_compliance_requirement_ids`/
    `required_action_assessment_ids` are optional initial links (§13's
    multi-linkage) — each is validated to belong to this project; further
    links can be added afterward via the dedicated link endpoints."""

    title: str
    description: str = ""
    issuing_organisation: str | None = None
    issued_date: date | None = None
    expiry_date: date | None = None
    notes: str = ""
    project_compliance_requirement_ids: list[UUID] = []
    required_action_assessment_ids: list[UUID] = []


class ComplianceEvidenceUpdate(BaseModel):
    """Update payload — deliberately excludes `expiry_date`: per §15,
    changing an evidence row's validity/expiry must always go through
    `POST .../revalidate` so the previous value is retained in
    `ComplianceEvidenceRevalidation`, never silently overwritten by a plain
    field edit."""

    title: str
    description: str = ""
    issuing_organisation: str | None = None
    issued_date: date | None = None
    notes: str = ""


class ComplianceEvidenceRevalidateRequest(BaseModel):
    """Payload for `POST .../evidence/{id}/revalidate` (§15). `new_expiry_date`
    may be `None` (e.g. revalidating evidence that has no expiry at all, to
    simply record a periodic re-confirmation) — see `router.py::revalidate_
    evidence`."""

    new_expiry_date: date | None = None
    justification: str = ""


class ComplianceEvidenceRevalidationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    evidence_id: UUID
    revalidated_by: UUID
    revalidated_at: datetime
    previous_expiry_date: date | None
    new_expiry_date: date | None
    justification: str
    created_at: datetime


class ComplianceEvidenceRequirementLinkCreate(BaseModel):
    project_compliance_requirement_id: UUID


class ComplianceEvidenceActionLinkCreate(BaseModel):
    required_action_assessment_id: UUID


class ComplianceEvidenceOut(BaseModel):
    """Response shape for one `ComplianceEvidence` row, plus its *computed*
    (never stored) `validity_state` (§14 — see `service.py::compute_
    evidence_validity_state`) and its current linked requirement/required-
    action-assessment ids (§13's multi-linkage) — built explicitly by the
    router (not `from_attributes` alone), the same reason
    `ProjectComplianceRequirementOut` is."""

    id: UUID
    project_id: UUID
    title: str
    description: str
    issuing_organisation: str | None
    issued_date: date | None
    expiry_date: date | None
    provided_by: UUID
    provided_at: datetime
    notes: str
    validity_state: ComplianceEvidenceValidityState
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None
    created_at: datetime
    updated_at: datetime
    linked_requirement_ids: list[UUID]
    linked_required_action_assessment_ids: list[UUID]


# --- Phase 9: Approval / sign-off workflow ---------------------------------------


class ComplianceApprovalDecisionRequest(BaseModel):
    """Payload for `POST .../requirements/{id}/approve` and `.../reject`
    (§12). `decision_note` is required by the router (400, not a schema-
    level validator) when rejecting — the same conditionally-mandatory
    pattern as `ProjectComplianceApplicabilityUpdate.justification`/
    `ProjectComplianceAssessmentUpdate.justification` — and optional when
    approving."""

    decision_note: str = ""


class PendingApprovalOut(BaseModel):
    """One row of `GET .../pending-approvals` (§12's "Pending Approval" as
    its own distinct, drillable list) — the `compliance_list_pending_
    approvals` MCP tool. Mirrors `NonCompliantRequirementOut`'s exact shape
    one section up, for the same kind of cross-assignment listing."""

    project_compliance_id: UUID
    standard_reference: str
    standard_name: str
    version_label: str
    project_compliance_requirement_id: UUID
    requirement_id: UUID
    requirement_reference: str | None
    requirement_name: str
    compliance_status: ComplianceStatus
    assessed_at: datetime | None
    assessed_by: UUID | None


class OutstandingRequiredActionOut(BaseModel):
    """One row of `GET .../outstanding-required-actions` (Phase 14,
    §22/§23's "outstanding Required Actions" — a flattened, cross-assignment
    listing of every incomplete `ComplianceRequiredActionAssessment` whose
    owning requirement is currently applicable, mirroring `NonCompliant
    RequirementOut`/`PendingApprovalOut`'s exact shape/rationale for the
    same kind of listing. This schema did not exist before Phase 14 — no
    prior phase needed a *flattened* required-action listing (only the
    per-requirement nested `.../required-action-assessments` endpoint,
    Phase 7) — so unlike the two schemas above (which predate this phase
    and already have passing Phase 12/13 consumers left untouched), this one
    carries `project_id`/`project_name` from the start: it is used
    unmodified by both `project_router.py`'s own new per-project endpoint
    and `router.py`'s org-wide aggregation, rather than needing a separate
    `Org*Out` subclass the way the two pre-existing schemas do (see
    `router.py`'s Phase 14 section for that distinction)."""

    project_id: UUID
    project_name: str
    project_compliance_id: UUID
    standard_reference: str
    standard_name: str
    version_label: str
    project_compliance_requirement_id: UUID
    requirement_id: UUID
    requirement_reference: str | None
    requirement_name: str
    required_action_assessment_id: UUID
    required_action_id: UUID
    required_action_name: str
    is_mandatory: bool
    assignee_id: UUID | None
    due_date: date | None
    notes: str


# --- Phase 10: Scheduled reviews --------------------------------------------------


class ComplianceReviewCreate(BaseModel):
    """Payload for scheduling a new `ComplianceReview` (§17). Exactly one of
    `standard_id`/`project_compliance_id` is supplied by the router itself
    (from the path, not this payload — mirrors how `ComplianceEvidenceCreate`
    never carries `project_id`), so this schema only needs the fields that
    are genuinely caller-supplied."""

    frequency_label: str
    recurrence_days: int | None = None
    next_due_date: date
    owner_id: UUID | None = None
    notes: str = ""


class ComplianceReviewUpdate(BaseModel):
    """Update payload — only while a review is still `SCHEDULED` (enforced
    by the router, 409 otherwise); a `COMPLETED` review is retained history
    (§17) and must not be edited in place."""

    frequency_label: str
    recurrence_days: int | None = None
    next_due_date: date
    owner_id: UUID | None = None
    notes: str = ""


class ComplianceReviewCompleteRequest(BaseModel):
    """Payload for `POST .../reviews/{id}/complete` (§17's "Review outcome").
    `notes` here replaces the review's own `notes` field (mirrors
    `ProjectComplianceAssessmentUpdate.notes`'s own "supply the current
    full value" convention), independent of any evidence linkage."""

    outcome: ComplianceReviewOutcome
    notes: str = ""


class ComplianceReviewEvidenceLinkCreate(BaseModel):
    evidence_id: UUID


class ComplianceReviewOut(BaseModel):
    """Response shape for one `ComplianceReview` row, plus its *computed*
    `schedule_state` (§17/§28's "identify upcoming and overdue compliance
    reviews" — see `service.py::compute_review_schedule_state`) and its
    current linked evidence ids (§17's "Notes/evidence associated with the
    review") — built explicitly by the router, the same reason
    `ComplianceEvidenceOut` is."""

    id: UUID
    standard_id: UUID | None
    project_compliance_id: UUID | None
    frequency_label: str
    recurrence_days: int | None
    next_due_date: date
    owner_id: UUID | None
    status: ComplianceReviewStatus
    schedule_state: Literal["upcoming", "due", "overdue"] | None
    notes: str
    outcome: ComplianceReviewOutcome | None
    completed_at: datetime | None
    completed_by: UUID | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    linked_evidence_ids: list[UUID]


# --- Phase 11: Cross-standard mapping + version impact ---------------------------


class ComplianceMappingRelationshipTypeCreate(BaseModel):
    name: str
    implies_equivalence: bool = False


class ComplianceMappingRelationshipTypeUpdate(BaseModel):
    """Update payload — mirrors `ComplianceActionTypeUpdate`'s rename
    shape, extended with `implies_equivalence` (Phase 11's carry-forward-
    across-a-replaced-mapping gate, see `models.py`'s own notes). Every
    `ComplianceRequirementMapping.relationship_type_id` reference points at
    this row's id, never its name, so renaming never disturbs an existing
    mapping; toggling `implies_equivalence` likewise never touches any
    existing mapping row — it only changes whether *future* migrations may
    offer carry-forward for a `replaced` pair linked by this type."""

    name: str
    implies_equivalence: bool = False


class ComplianceMappingRelationshipTypeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
    implies_equivalence: bool


class ComplianceRequirementMappingCreate(BaseModel):
    """Payload for `POST .../requirement-mappings` (§19). `from_requirement_id`/
    `to_requirement_id` may belong to any standard/version in this
    organisation (including two versions of the *same* standard — see
    `models.py`'s own Phase 11 notes on why this table also serves §27's
    "replaced" category) — the router verifies both, and `relationship_type_id`,
    belong to this same organisation (404 on a mismatch, this module's usual
    convention)."""

    from_requirement_id: UUID
    to_requirement_id: UUID
    relationship_type_id: UUID
    notes: str = ""


class ComplianceRequirementMappingOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    from_requirement_id: UUID
    to_requirement_id: UUID
    relationship_type_id: UUID
    notes: str
    created_by: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ComplianceRequirementSummaryOut(BaseModel):
    """Minimal identifying summary of a `ComplianceRequirement` row, used by
    the version-diff schemas below so a caller can show a reference/name
    next to a diff category without a second round-trip to `GET .../
    requirements/{id}`."""

    model_config = {"from_attributes": True}

    id: UUID
    standard_version_id: UUID
    reference: str | None
    name: str


class AddedRequirementOut(BaseModel):
    """One row of `StandardVersionDiffOut.added` (§27) — a new-version
    requirement with no clone lineage back to the old version at all (see
    `service.py::diff_standard_versions`)."""

    requirement: ComplianceRequirementSummaryOut


class RemovedRequirementOut(BaseModel):
    """One row of `StandardVersionDiffOut.removed` (§27) — an old-version
    requirement with nothing in the new version tracing lineage back to it,
    and no explicit "replaced by" mapping either."""

    requirement: ComplianceRequirementSummaryOut


class ModifiedRequirementOut(BaseModel):
    """One row of `StandardVersionDiffOut.modified` (§27) — a lineage-
    matched pair (same underlying requirement, cloned forward) whose
    content differs. `changed_fields` names exactly which of `reference`/
    `name`/`description`/`reasoning` differ, per `service.py::
    diff_standard_versions`'s own content-equality rule."""

    old_requirement: ComplianceRequirementSummaryOut
    new_requirement: ComplianceRequirementSummaryOut
    changed_fields: list[str]


class ReplacedRequirementOut(BaseModel):
    """One row of `StandardVersionDiffOut.replaced` (§27) — an old-version
    requirement with no clone lineage into the new version, but explicitly
    linked (via a `ComplianceRequirementMapping`) to a new-version
    requirement that itself has no clone lineage back — see `models.py`'s
    own Phase 11 notes for why this reuses the cross-standard mapping table
    rather than a second mechanism.

    `implies_equivalence` mirrors the mapping's own relationship type's
    `ComplianceMappingRelationshipTypeDefinition.implies_equivalence` at
    read time (denormalised onto this row so a caller deciding what to pass
    as `ProjectComplianceMigrationRequest.confirmed_replacement_requirement_
    ids` doesn't need a second lookup against the relationship-types list)
    — whether this specific pair is even eligible to be offered for
    migration carry-forward. `False` means the migration endpoint will 400
    if this pair's new-requirement id is submitted as confirmed."""

    old_requirement: ComplianceRequirementSummaryOut
    new_requirement: ComplianceRequirementSummaryOut
    mapping_id: UUID
    relationship_type_id: UUID
    implies_equivalence: bool
    """Mirrors the mapping's own `ComplianceMappingRelationshipTypeDefinition.
    implies_equivalence` at read time (denormalised onto this row so a
    caller deciding what to pass as `ProjectComplianceMigrationRequest.
    confirmed_replacement_requirement_ids` doesn't need a second lookup
    against the relationship-types list) — whether this specific `replaced`
    pair is even eligible to be offered for migration carry-forward. `False`
    here means the migration endpoint will 400 if this pair's new-
    requirement id is submitted as confirmed."""


class RemappedRequirementOut(BaseModel):
    """One row of `StandardVersionDiffOut.re_mapped` (§27) — a lineage-
    matched pair where the old requirement had one or more cross-standard/
    cross-version mapping links that the new requirement does not fully
    carry forward (mapping links are never auto-cloned — see `service.py::
    diff_standard_versions`'s own docstring for why that is itself the
    useful signal here, not a bug to fix)."""

    old_requirement: ComplianceRequirementSummaryOut
    new_requirement: ComplianceRequirementSummaryOut
    old_mapping_target_requirement_ids: list[UUID]
    new_mapping_target_requirement_ids: list[UUID]


class StandardVersionDiffOut(BaseModel):
    """Full response for `GET .../versions/{version_id}/diff/{other_version_id}`
    (§27's "users should be able to see what changed between standard
    versions" plus its own five named categories). `old_version_id`/
    `new_version_id` are always the lower/higher `version_number` of the
    two requested, regardless of which order they appeared in the URL —
    see `router.py::get_standard_version_diff`'s own docstring."""

    old_version_id: UUID
    new_version_id: UUID
    added: list[AddedRequirementOut]
    removed: list[RemovedRequirementOut]
    modified: list[ModifiedRequirementOut]
    replaced: list[ReplacedRequirementOut]
    re_mapped: list[RemappedRequirementOut]


class ProjectComplianceMigrationRequest(BaseModel):
    """Payload for `POST .../project-compliance/{id}/migrate-version`
    (§27's "projects should be able to migrate/adopt a newer version
    through an explicit action").

    `confirmed_replacement_requirement_ids` is the compliance officer's own,
    per-migration, per-requirement opt-in to carry an assessment forward
    across a `replaced` version-diff pair (see `models.py`'s own Phase 11
    notes on `ComplianceMappingRelationshipTypeDefinition.implies_equivalence`
    for the full two-gate design) — each id names a *new*-version
    requirement (matching `ReplacedRequirementOut.new_requirement.id` from a
    prior `GET .../diff/...` call, the natural "preview, then confirm" order
    this is meant to be used in). The endpoint 400s if an id here isn't
    actually part of this migration's `replaced` set, or is but its
    mapping's relationship type has `implies_equivalence=False` — a stale
    or invalid confirmation is rejected outright, never silently ignored.
    Defaults to empty: an officer who does nothing gets this phase's
    original behaviour (every `replaced` requirement lands at defaults)."""

    new_standard_version_id: UUID
    confirmed_replacement_requirement_ids: list[UUID] = []


class ProjectComplianceMigrationRequirementImpact(BaseModel):
    """One requirement's outcome of a version migration — §27's "identify
    whether reassessment/reapproval is required," per requirement, not
    just as an aggregate count. `"replaced"` covers every `replaced`-diff
    requirement regardless of whether it was actually carried forward —
    `carried_forward` (not `change`) is what distinguishes a confirmed,
    eligible carry-forward from one left at defaults."""

    project_compliance_requirement_id: UUID
    requirement_id: UUID
    requirement_reference: str | None
    requirement_name: str
    change: Literal["unchanged", "modified", "added", "replaced"]
    carried_forward: bool
    requires_reassessment: bool


class ProjectComplianceMigrationResultOut(BaseModel):
    """Response for the version-migration action — the new (post-migration)
    `ProjectCompliance` assignment plus a full per-requirement breakdown of
    what was carried forward vs. left to reassess. Does not repeat
    `removed` requirements from the underlying diff (an old-version
    requirement with no successor in the new version has no row on the
    *new* assignment at all to report an impact against). `replaced`
    requirements *are* included — their new-version requirement is part of
    the new assignment and gets a materialised row like any other, whether
    or not it was actually carried forward (corrected from this schema's
    original docstring, which mistakenly grouped `replaced` with `removed`
    — see `change`'s own docstring for the fix, made while adding the
    `replaced` category itself). A caller wanting the full diff context
    (including `removed`) calls `GET .../diff/...` first, the natural
    "preview, then commit" order this action is meant to be used in."""

    new_project_compliance: ProjectComplianceOut
    previous_project_compliance_id: UUID
    previous_standard_version_id: UUID
    new_standard_version_id: UUID
    total_requirements: int
    carried_forward_count: int
    requires_reassessment_count: int
    added_count: int
    modified_count: int
    replaced_count: int
    requirement_impacts: list[ProjectComplianceMigrationRequirementImpact]


# --- Phase 14: Org Compliance View + Dashboard (§22, §23) ------------------------
#
# Org-wide aggregations across every project in an organisation, mirroring
# `router.py::list_all_project_compliance`'s existing "join ProjectCompliance
# to Project on organization_id" pattern (§26 — Compliance Manager's "View
# compliance across projects"). Each of `NonCompliantRequirementOut`/
# `PendingApprovalOut`/`ComplianceEvidenceOut` already existed before this
# phase with passing Phase 12/13 consumers at project scope; rather than
# retrofit `project_id`/`project_name` onto those (a response-shape change
# every existing caller would silently start receiving), each gets its own
# `Org*Out` subclass here that adds exactly those two fields — the org
# endpoints build these from the exact same per-project computation
# (`service.py`'s newly-extracted `list_non_compliant_requirements_for_
# project`/etc., shared with `project_router.py`'s own endpoints) with
# `project_id`/`project_name` stamped on afterward, so the underlying
# business logic is never duplicated between scopes. `ComplianceReviewOut`
# gets a nested wrapper instead of a flat subclass (`OrgReviewDueOut`)
# because a single review has genuine multiplicity across projects — a
# standard-level review can be "due" simultaneously for every project
# assigned to that standard, so it cannot honestly carry one `project_id`
# field the way a `ProjectComplianceRequirement`-derived row can.


class OrgNonCompliantRequirementOut(NonCompliantRequirementOut):
    project_id: UUID
    project_name: str


class OrgPendingApprovalOut(PendingApprovalOut):
    project_id: UUID
    project_name: str


class OrgExpiringEvidenceOut(ComplianceEvidenceOut):
    project_name: str


class OrgReviewDueOut(BaseModel):
    """One review "due" for one project — see this section's own docstring
    for why this wraps `ComplianceReviewOut` rather than subclassing it
    flat: the same standard-level review can legitimately appear more than
    once here, once per project it's currently due for."""

    project_id: UUID
    project_name: str
    review: ComplianceReviewOut


class ComplianceRecentActivityOut(BaseModel):
    """One row of `GET .../recent-activity` (§23's "Recently changed
    compliance assessments") — the most recent `project_compliance_
    requirement` audit events across every project in the organisation
    (assessed / applicability_changed / submitted_for_approval / approved /
    rejected / approval_invalidated — every action `project_router.py`
    logs against a `ProjectComplianceRequirement`), resolved to a
    human-readable project/standard/requirement label rather than raw
    entity ids. Built by `service.py::list_recent_compliance_activity`."""

    id: UUID
    project_id: UUID
    project_name: str
    standard_reference: str
    standard_name: str
    version_label: str
    requirement_reference: str | None
    requirement_name: str
    action: str
    actor_id: UUID | None
    created_at: datetime


# --- Phase 18: cross-org, global (no org/project id in the path) endpoints --


class ComplianceNavVisibilityOut(BaseModel):
    """Response of `GET /api/v1/compliance/nav-visibility` (`global_router.
    py`) — whether the caller should see the top-level "Compliance
    Standards" nav-rail tab at all (compliance-module-plan.md Phase 18).
    Deliberately a single boolean, not a per-org breakdown: the frontend
    hook this feeds gates one nav item, not a list, and a per-org
    breakdown would leak which specific orgs have compliance-relevant data
    to a caller who may not otherwise be able to see into all of them."""

    model_config = {"from_attributes": True}

    visible: bool
