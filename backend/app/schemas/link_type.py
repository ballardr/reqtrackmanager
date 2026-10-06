"""
Module: schemas.link_type

Request/response models for org-definable, bidirectional requirement link
types (`RequirementLinkTypeDefinition`). Shares the rename/delete/reassign
contract described in `services.definitions`' module docstring with
`schemas.project_status` and `schemas.action_type`.
"""

from __future__ import annotations

from typing import Literal
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
    project_id: UUID | None = None
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
    moved_link_count: int
    keep_available: bool = False
    keep_project_count: int | None = None
    unmanageable_project_count: int = 0


class LinkTypeDeleteOutcomeOut(BaseModel):
    """What a mode-based delete did, including copies kept for other projects
    (`copies_renamed` lists the names of those that had to be renamed)."""

    moved: int
    merged: int
    removed: int
    copies_created: int = 0
    copies_renamed: list[str] = []


LinkTypeScope = Literal["organization", "project", "inherited"]


class ProjectLinkTypeOut(BaseModel):
    """A link type as one project sees it.

    `scope` says where it comes from: `organization` (shared), `project` (this
    project's own, editable) or `inherited` (an ancestor's local type). `owner_project_name`
    is only given when the viewer can see that project. `hidden` is the effective state;
    `hidden_here` is this project's own choice (`null` = none). A `shadowed_by_scope` type
    is not offered because a same-named type takes precedence.
    """

    id: UUID
    organization_id: UUID
    project_id: UUID | None = None
    forward_name: str
    reverse_name: str
    sort_order: int
    flow: LinkFlow
    allowed_source_types: list[str] | None = None
    allowed_target_types: list[str] | None = None
    dedicated_endpoint: bool = False
    scope: LinkTypeScope
    owner_project_id: UUID | None = None
    owner_project_name: str | None = None
    hidden: bool
    hidden_here: bool | None = None
    hidden_by_inherited: bool = False
    shadowed_by_scope: LinkTypeScope | None = None
    shadowed_by_name: str | None = None
    editable: bool


class ProjectLinkTypesOut(BaseModel):
    """A project's link-type panel: the types it can reach, and whether the
    organisation has locked customisation (then project-level types are dormant)."""

    locked: bool
    items: list[ProjectLinkTypeOut]


class LinkTypeVisibilitySet(BaseModel):
    """Hide (`true`), show (`false`), or clear this project's own choice (`null`)."""

    hidden: bool | None


class ProjectArtefactLinkRuleOut(ArtefactLinkRuleOut):
    """An artefact type's rule as a project resolves it. `source` says which scope it
    comes from (`null` when there is none, so any link type is allowed); `own` is true
    when this project holds it (so it can be cleared to use the inherited one)."""

    source: LinkTypeScope | None = None
    source_project_name: str | None = None
    own: bool = False


class ProjectCustomisationOut(BaseModel):
    """The organisation's project-customisation locks and what locking affects."""

    locks: list[str]
    local_link_type_count: int
    local_link_type_project_count: int


class ProjectCustomisationSet(BaseModel):
    """Payload replacing the organisation's project-customisation locks."""

    locks: list[str]
