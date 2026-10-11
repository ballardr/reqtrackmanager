"""
Module: schemas.artefact_links

Request/response models for generic link authoring on any artefact:
which link types are usable from it, and creating/removing a link.
"""

from __future__ import annotations

import enum
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import LinkFlow, LinkNestingScope
from app.schemas.link_type import ArtefactTypeOut


class LinkOrientation(str, enum.Enum):
    """Which end of the link the page's artefact is: `outgoing` (the link's
    source, read with the link type's forward phrase) or `incoming` (its target,
    read with the reverse phrase)."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"


class ArtefactLinkTypeOption(BaseModel):
    """One way to use a link type from the artefact: its orientation, the phrase
    to show, and the artefact types that may sit at the other end."""

    link_type_id: UUID
    forward_name: str
    reverse_name: str
    flow: LinkFlow
    nesting_scope: LinkNestingScope = LinkNestingScope.ANCESTOR_EITHER_WAY
    direction: LinkOrientation
    phrase: str
    other_types: list[ArtefactTypeOut]


class ArtefactLinkCreate(BaseModel):
    """Payload to link the page's artefact to another record: of the project, or, with
    `other_project_id`, of one of its ancestor or descendant projects."""

    link_type_id: UUID
    direction: LinkOrientation = LinkOrientation.OUTGOING
    other_type: str
    other_id: UUID
    other_project_id: UUID | None = None


class ArtefactLinkOtherEnd(BaseModel):
    """The record at the far end of a created link."""

    type: str
    id: UUID
    type_label: str
    label: str
    status: str | None
    is_archived: bool
    project_id: UUID | None = None


class CandidateProjectOut(BaseModel):
    """A project a link may reach from the page's project: itself, an ancestor or a
    descendant the caller can open. `label` states the relationship (never relying on
    the name); `relation` is `same`, `ancestor` or `descendant`; `distance` is levels away."""

    id: UUID
    name: str
    relation: str
    distance: int
    label: str
    is_archived: bool


class CandidateProjectsOut(BaseModel):
    """The projects a link may reach, nearest first, and whether the cap cut the list short."""

    items: list[CandidateProjectOut]
    truncated: bool


class ArtefactLinkOut(BaseModel):
    """A created link, read from the page artefact's side."""

    id: UUID
    link_type_id: UUID
    phrase: str
    direction: LinkOrientation
    other: ArtefactLinkOtherEnd


class ArtefactLinkCandidate(BaseModel):
    """A record the page artefact could be linked to (the add row's target picker)."""

    type: str
    id: UUID
    type_label: str
    label: str
    status: str | None
    project_id: UUID | None = None


class ArtefactLinkCandidatesOut(BaseModel):
    """Link targets found by the finder (one type, or every linkable type), ordered by label;
    `truncated` when more matched than were returned."""

    items: list[ArtefactLinkCandidate]
    truncated: bool


class ArtefactLinkBrowseOption(BaseModel):
    """One choice at a browse level (a standard, a version, a status, a component)."""

    id: str
    label: str


class ArtefactLinkBrowseStepOut(BaseModel):
    """The next level of a type's scoped finder: its key and label, the options the earlier
    choices leave (capped; `truncated` when more matched), for the dialog to render generically."""

    key: str
    label: str
    options: list[ArtefactLinkBrowseOption]
    truncated: bool
