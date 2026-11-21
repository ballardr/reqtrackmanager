"""
Module: schemas.requirement_alias

Request and response models for requirement aliases (`routers.requirement_aliases`): a requirement placed in
further components and categories, each with a code of its own, and the setting that allows them.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.requirement import RequirementAliasIn

AliasMode = Literal["allowed", "disabled"]


class AliasSettingsOut(BaseModel):
    """The effective alias setting of a project and where it came from.

    Attributes:
        mode: The effective value.
        source: The tier that set it: `project`, `parent_project` or `organization`.
        own_mode: The project's own value (`None` follows the nearest ancestor project, else the organisation).
        organization_mode: The organisation's value.
        has_parent: Whether the project has a parent project.
        alias_count: Active aliases the project holds (they keep resolving whatever the setting).
    """

    mode: str
    source: str
    own_mode: str | None = None
    organization_mode: str
    has_parent: bool = False
    alias_count: int = 0


class OrgAliasSettingsOut(BaseModel):
    """The organisation's alias setting (the default for its projects)."""

    mode: str


class AliasModeSet(BaseModel):
    """Sets the setting; `None` on a project follows the nearest ancestor project, else the organisation."""

    mode: AliasMode | None = None


class AliasPlacesSet(BaseModel):
    """Makes a requirement sit in exactly its own place plus these."""

    places: list[RequirementAliasIn] = Field(max_length=49)


class MakeIndependentIn(BaseModel):
    """Options for making an alias independent."""

    related_link_type_id: UUID | None = Field(
        None, description="The link type joining the new requirement to the original; the organisation's Related to when omitted."
    )


class MakeIndependentBulkIn(MakeIndependentIn):
    """Makes several aliases independent in one request: the listed ones, or the next batch of the project's own."""

    alias_ids: list[UUID] = Field(default=[], max_length=200)
    all_aliases: bool = Field(
        False, description="Take the project's next aliases (up to 100 in tree order) instead of listing them; repeat until none remain."
    )


class SkippedItemOut(BaseModel):
    """Something not carried over to an independent copy, and why."""

    kind: Literal["link", "comment", "attachment"]
    label: str
    reason: str


class IndependentOut(BaseModel):
    """What making one alias independent did."""

    requirement_id: UUID
    unique_code: str
    original_id: UUID
    links_copied: int
    comments_copied: int
    attachments_copied: int
    tags_copied: int
    related_link_made: bool
    skipped: list[SkippedItemOut]


class IndependentFailureOut(BaseModel):
    """An alias a bulk request could not make independent."""

    alias_id: UUID
    unique_code: str
    reason: str


class MakeIndependentBulkOut(BaseModel):
    """The outcome of a bulk make independent: each alias made, and each refused."""

    made: list[IndependentOut]
    failed: list[IndependentFailureOut]
