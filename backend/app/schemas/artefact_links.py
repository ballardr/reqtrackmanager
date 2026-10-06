"""
Module: schemas.artefact_links

Request/response models for generic link authoring on any artefact:
which link types are usable from it, and creating/removing a link.
"""

from __future__ import annotations

import enum
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import LinkFlow
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
    direction: LinkOrientation
    phrase: str
    other_types: list[ArtefactTypeOut]


class ArtefactLinkCreate(BaseModel):
    """Payload to link the page's artefact to another record of the project."""

    link_type_id: UUID
    direction: LinkOrientation = LinkOrientation.OUTGOING
    other_type: str
    other_id: UUID


class ArtefactLinkOtherEnd(BaseModel):
    """The record at the far end of a created link."""

    type: str
    id: UUID
    type_label: str
    label: str
    status: str | None
    is_archived: bool


class ArtefactLinkOut(BaseModel):
    """A created link, read from the page artefact's side."""

    id: UUID
    link_type_id: UUID
    phrase: str
    direction: LinkOrientation
    other: ArtefactLinkOtherEnd
