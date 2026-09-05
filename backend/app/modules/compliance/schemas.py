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
from uuid import UUID

from pydantic import BaseModel

from app.modules.compliance.enums import ComplianceStandardVersionStatus

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
