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
    ComplianceStandardVersionStatus,
    ComplianceStatus,
)

# --- Standards ---------------------------------------------------------------


class ComplianceStandardCreate(BaseModel):
    """Payload for creating a `ComplianceStandard` (§2). `owner_id` defaults
    to the creating user when omitted — §2 lists "Owner" as an attribute
    without mandating it always differ from the creator."""

    reference: str
    name: str
    description: str = ""
    issuing_organisation: str | None = None
    owner_id: UUID | None = None


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
    percentage so that the percentage cannot be misleading.\""""

    project_compliance_id: UUID
    project_id: UUID
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
