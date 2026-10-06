"""
Module: schemas.link_type

Request/response models for org-definable, bidirectional requirement link
types (`RequirementLinkTypeDefinition`). Shares the rename/delete/reassign
contract described in `services.definitions`' module docstring with
`schemas.project_status` and `schemas.action_type`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import LinkFlow


class LinkTypeCreate(BaseModel):
    """Payload to create a new link type in an organisation. Both directional
    names are required up front — a link type with only one name defined
    would render blank/wrong when read from the other direction."""

    forward_name: str
    reverse_name: str
    flow: LinkFlow = LinkFlow.NONE
    allowed_source_types: list[str] | None = None
    allowed_target_types: list[str] | None = None


class LinkTypeUpdate(BaseModel):
    """Renames both directional names at once — see
    `services.definitions`' module docstring: renaming never disturbs any
    existing link using this type, since every reference points at the
    row's id, never its names. `flow` left out keeps the current direction.
    `allowed_source_types`/`allowed_target_types` left out keep the current
    restriction; present, they replace it (`null` or empty = any artefact type)."""

    forward_name: str
    reverse_name: str
    flow: LinkFlow | None = None
    allowed_source_types: list[str] | None = None
    allowed_target_types: list[str] | None = None


class LinkTypeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    forward_name: str
    reverse_name: str
    sort_order: int
    flow: LinkFlow
    allowed_source_types: list[str] | None = None
    allowed_target_types: list[str] | None = None
    dedicated_endpoint: bool = False


class ArtefactTypeOut(BaseModel):
    """A registered artefact type and its display label."""

    type: str
    label: str


class ArtefactLinkRuleOut(BaseModel):
    """One artefact type's rule: the link types it may use, or `null` for any."""

    artefact_type: str
    label: str
    link_type_ids: list[UUID] | None = None


class ArtefactLinkRuleSet(BaseModel):
    """Payload replacing an artefact type's rule; must name at least one link type."""

    link_type_ids: list[UUID] = Field(min_length=1)


class LinkTypeCandidateOut(BaseModel):
    """A link type that might take over the links of one being deleted."""

    id: UUID
    forward_name: str
    reverse_name: str
    flow: LinkFlow
    compatible: bool
    reason: str | None = None
    flow_differs: bool


class LinkTypeUsageOut(BaseModel):
    """What depends on a link type, for the delete-in-use dialog."""

    link_count: int
    project_count: int | None = None
    pending_change_requests: int
    approved_requirement_links: int
    rule_artefact_types: list[ArtefactTypeOut]
    emptied_rule_artefact_types: list[ArtefactTypeOut]
    is_dedicated: bool
    is_last: bool
    candidates: list[LinkTypeCandidateOut]


class LinkTypeDeleteOutcomeOut(BaseModel):
    """What a mode-based delete did."""

    moved: int
    merged: int
    removed: int
