"""
Module: modules.architecture.schemas

Request and response bodies of the module's APIs: the vocabularies (an element type
and a connection type share the name, domain and colour fields; each adds its own
`shape`, or `line_style` and `directional`) and the records (elements with their
ports, and connections).

A save of an element or a connection quotes the `version` it was based on; the API
answers 409 when the record has moved on. A nullable field the body may clear
(`parent_id`, `owner`, a port's connection type) is told apart from one it did not
mention by `model_fields_set`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.architecture.enums import Domain, ElementShape, LineStyle, PortDirection, RecordStatus
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.schemas.project_scope import ProjectScopedRow

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


# --- Elements, ports and connections ---------------------------------------


class PortCreate(BaseModel):
    """Create payload for a port (also the entries of an element's initial `ports`)."""

    name: str = Field(min_length=1, max_length=100)
    direction: PortDirection = PortDirection.BOTH
    connection_type_id: UUID | None = None


class PortUpdate(BaseModel):
    """Partial update of a port; `connection_type_id: null` clears the type."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    direction: PortDirection | None = None
    connection_type_id: UUID | None = None


class PortOut(BaseModel):
    """A port with its connection type's name."""

    id: UUID
    element_id: UUID
    name: str
    direction: str
    connection_type_id: UUID | None
    connection_type_name: str | None
    sort_order: int


class ElementCreate(BaseModel):
    """Create payload for an element.

    Attributes:
        activate: Create the element `active` instead of `draft` (Save and activate). Needs nothing beyond the
            permission to create, since an element has no approval gate.
        ports: Ports created with the element.
    """

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    element_type_id: UUID
    parent_id: UUID | None = None
    owner: PrincipalRef | None = None
    activate: bool = False
    ports: list[PortCreate] = Field(default_factory=list, max_length=200)


class ElementUpdate(BaseModel):
    """Edit of an element. `version` is required (the optimistic lock); a field left out is kept, and
    `parent_id` / `owner` set to `null` clear the field."""

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    element_type_id: UUID | None = None
    parent_id: UUID | None = None
    owner: PrincipalRef | None = None


class StatusChange(BaseModel):
    """A move to another status (`version` is the optimistic lock)."""

    version: int
    status: RecordStatus


class ElementOut(ProjectScopedRow):
    """An element with its type name, resolved owner, ports and tree counts."""

    id: UUID
    project_id: UUID
    unique_code: str
    name: str
    description: str
    element_type_id: UUID
    element_type_name: str
    parent_id: UUID | None
    owner: PrincipalOut | None
    status: str
    version: int
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    child_count: int
    connection_count: int
    ports: list[PortOut]


class ConnectionCreate(BaseModel):
    """Create payload for a connection between two elements (a port on each end is optional)."""

    name: str = Field(default="", max_length=200)
    connection_type_id: UUID
    source_element_id: UUID
    source_port_id: UUID | None = None
    target_element_id: UUID
    target_port_id: UUID | None = None
    protocol: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=20000)
    activate: bool = False


class ConnectionUpdate(BaseModel):
    """Edit of a connection. `version` is required; a field left out is kept, and a port set to `null` clears it."""

    version: int
    name: str | None = Field(default=None, max_length=200)
    connection_type_id: UUID | None = None
    source_element_id: UUID | None = None
    source_port_id: UUID | None = None
    target_element_id: UUID | None = None
    target_port_id: UUID | None = None
    protocol: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=20000)


class ConnectionOut(ProjectScopedRow):
    """A connection with its type and end names."""

    id: UUID
    project_id: UUID
    unique_code: str
    name: str
    connection_type_id: UUID
    connection_type_name: str
    directional: bool
    source_element_id: UUID
    source_element_code: str
    source_element_name: str
    source_port_id: UUID | None
    source_port_name: str | None
    target_element_id: UUID
    target_element_code: str
    target_element_name: str
    target_port_id: UUID | None
    target_port_name: str | None
    protocol: str
    description: str
    status: str
    version: int
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
