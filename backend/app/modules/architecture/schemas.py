"""
Module: modules.architecture.schemas

Request and response bodies of the vocabulary APIs. An element type and a
connection type share the name, domain and colour fields; each adds its own
(`shape`, or `line_style` and `directional`).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.architecture.enums import Domain, ElementShape, LineStyle

#: `#RRGGBB`.
_HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class _VocabularyCreate(BaseModel):
    """Fields every vocabulary row is created with."""

    name: str = Field(min_length=1, max_length=100)
    domain: Domain = Domain.ANY
    color_light: str | None = Field(default=None, pattern=_HEX_COLOR)
    color_dark: str | None = Field(default=None, pattern=_HEX_COLOR)


class _VocabularyUpdate(BaseModel):
    """Fields every vocabulary row may change; `None` leaves a field as it is."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    domain: Domain | None = None
    color_light: str | None = Field(default=None, pattern=_HEX_COLOR)
    color_dark: str | None = Field(default=None, pattern=_HEX_COLOR)


class ElementTypeCreate(_VocabularyCreate):
    """Create payload for an element type."""

    shape: ElementShape = ElementShape.RECTANGLE


class ElementTypeUpdate(_VocabularyUpdate):
    """Partial update of an element type."""

    shape: ElementShape | None = None


class ConnectionTypeCreate(_VocabularyCreate):
    """Create payload for a connection type."""

    line_style: LineStyle = LineStyle.SOLID
    directional: bool = True


class ConnectionTypeUpdate(_VocabularyUpdate):
    """Partial update of a connection type."""

    line_style: LineStyle | None = None
    directional: bool | None = None


class _VocabularyOut(BaseModel):
    """A vocabulary row. Exactly one of `project_id` and `organization_id` is set (the owner)."""

    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID | None
    organization_id: UUID | None
    name: str
    domain: str
    color_light: str | None
    color_dark: str | None
    sort_order: int


class ElementTypeOut(_VocabularyOut):
    """An element type."""

    shape: str


class ConnectionTypeOut(_VocabularyOut):
    """A connection type."""

    line_style: str
    directional: bool
