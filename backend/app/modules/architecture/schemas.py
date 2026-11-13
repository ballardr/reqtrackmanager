"""
Module: modules.architecture.schemas

Request and response bodies of the module's APIs: the vocabularies (an element type
and a connection type share the name, domain and colour fields; each adds its own
`shape` and `symbol_id`, or `line_style` and `directional`), the symbol library, and the
records (elements with their ports, connections, and diagrams with their placements, notes, toggles and the resolved
view a diagram draws).

A save of an element or a connection quotes the `version` it was based on; the API
answers 409 when the record has moved on. A nullable field the body may clear
(`parent_id`, `owner`, a port's connection type) is told apart from one it did not
mention by `model_fields_set`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.architecture.enums import (
    DISPLAY_NOTE_MAX,
    AttachPoint,
    Domain,
    ElementShape,
    FolderKind,
    LineStyle,
    PortDirection,
    RecordStatus,
)
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.schemas.project_scope import ProjectScopedRow

#: `#RRGGBB`.
_HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class CapabilitiesOut(BaseModel):
    """What the caller may do in a project beyond reading, so a screen offers only the actions that will be accepted.

    Attributes:
        manage_types: May change the project's element and connection types and symbols (`architecture_admin`).
    """

    manage_types: bool


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
    """Create payload for an element type. `symbol_id` is a symbol the owner may use; `suggested_connection_type_ids` are
    the connection types a connection picker lists first for it (guidance only)."""

    shape: ElementShape = ElementShape.RECTANGLE
    symbol_id: UUID | None = None
    suggested_connection_type_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ElementTypeUpdate(_VocabularyUpdate):
    """Partial update of an element type. `symbol_id: null` clears the symbol (the shape is drawn);
    `suggested_connection_type_ids` replaces the suggestions (an empty list clears them)."""

    shape: ElementShape | None = None
    symbol_id: UUID | None = None
    suggested_connection_type_ids: list[UUID] | None = Field(default=None, max_length=50)


class ConnectionTypeCreate(_VocabularyCreate):
    """Create payload for a connection type. `parent_ids` are the types it sits under (see `connection_tree`)."""

    line_style: LineStyle = LineStyle.SOLID
    directional: bool = True
    parent_ids: list[UUID] = Field(default_factory=list, max_length=20)


class ConnectionTypeUpdate(_VocabularyUpdate):
    """Partial update of a connection type. `parent_ids` replaces the parents (an empty list makes it a root)."""

    line_style: LineStyle | None = None
    directional: bool | None = None
    parent_ids: list[UUID] | None = Field(default=None, max_length=20)


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
    symbol_id: UUID | None
    suggested_connection_type_ids: list[UUID]


class ConnectionTypeOut(_VocabularyOut):
    """A connection type."""

    line_style: str
    directional: bool
    parent_ids: list[UUID]


# --- Symbols -----------------------------------------------------------------


class SymbolUpdate(BaseModel):
    """Rename of a symbol (a built-in cannot be renamed, and the drawing of an upload is replaced by uploading anew)."""

    name: str | None = Field(default=None, min_length=1, max_length=100)


class SymbolOut(BaseModel):
    """A symbol library entry. Exactly one of `project_id` and `organization_id` is set (the owner); `builtin_key` is
    set for a built-in drawing. Its SVG is read from `.../symbols/{id}/content`."""

    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID | None
    organization_id: UUID | None
    name: str
    builtin_key: str | None
    is_builtin: bool
    sort_order: int


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
        symbol_id: A symbol drawn instead of the type's, from the owner's library.
        ports: Ports created with the element.
    """

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    display_note: str = Field(default="", max_length=DISPLAY_NOTE_MAX)
    element_type_id: UUID
    parent_id: UUID | None = None
    owner: PrincipalRef | None = None
    symbol_id: UUID | None = None
    folder_id: UUID | None = None
    activate: bool = False
    ports: list[PortCreate] = Field(default_factory=list, max_length=200)


class ElementUpdate(BaseModel):
    """Edit of an element. `version` is required (the optimistic lock); a field left out is kept, and
    `parent_id` / `owner` / `symbol_id` / `folder_id` set to `null` clear the field."""

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    display_note: str | None = Field(default=None, max_length=DISPLAY_NOTE_MAX)
    element_type_id: UUID | None = None
    parent_id: UUID | None = None
    owner: PrincipalRef | None = None
    symbol_id: UUID | None = None
    folder_id: UUID | None = None


class StatusChange(BaseModel):
    """A move to another status (`version` is the optimistic lock)."""

    version: int
    status: RecordStatus


class ElementOut(ProjectScopedRow):
    """An element with its type name, resolved owner, ports and tree counts. `symbol_id` is the element's own symbol and
    `effective_symbol_id` the one drawn (its own, else its type's, else `None` for the type's shape).

    `project_id` / `organization_id` say who owns it (exactly one is set); `shared` is true when it is shown in a
    project that does not own it, in which case its connection count covers only that project's connections."""

    id: UUID
    project_id: UUID | None
    organization_id: UUID | None = None
    shared: bool = False
    unique_code: str
    name: str
    description: str
    display_note: str
    element_type_id: UUID
    element_type_name: str
    symbol_id: UUID | None
    effective_symbol_id: UUID | None
    parent_id: UUID | None
    folder_id: UUID | None = None
    folder_path: str | None = None
    owner: PrincipalOut | None
    status: str
    allowed_status_moves: list[str]
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
    folder_id: UUID | None = None
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
    folder_id: UUID | None = None


class RealisationsSet(BaseModel):
    """Sets the outer connections an inner connection realises (`version` is the connection's optimistic lock)."""

    version: int
    outer_connection_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ConnectionRef(BaseModel):
    """A connection named from another connection's page: its code, name and the type it is."""

    id: UUID
    unique_code: str
    name: str
    status: str


class ConnectionOut(ProjectScopedRow):
    """A connection with its type and end names.

    An end is `locked` when the viewer can no longer read it (only its code is shown) and `shared` when another
    owner shares it with the project."""

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
    source_locked: bool = False
    source_shared: bool = False
    target_element_id: UUID
    target_element_code: str
    target_element_name: str
    target_port_id: UUID | None
    target_port_name: str | None
    target_locked: bool = False
    target_shared: bool = False
    protocol: str
    description: str
    folder_id: UUID | None = None
    folder_path: str | None = None
    status: str
    allowed_status_moves: list[str]
    version: int
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    realises: list[ConnectionRef] = Field(default_factory=list)
    realised_by: list[ConnectionRef] = Field(default_factory=list)


# --- Folders ---------------------------------------------------------------


class FolderCreate(BaseModel):
    """Create payload for a folder: a name in the tree of the kind the route names, under `parent_id` or at the top level."""

    name: str = Field(min_length=1, max_length=100)
    parent_id: UUID | None = None


class FolderUpdate(BaseModel):
    """Rename or move a folder. A field left out is kept; `parent_id` set to `null` moves it to the top level."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)


class FolderOut(BaseModel):
    """A folder with its path (names from the top, joined by `/`) and the number of records directly in it."""

    id: UUID
    project_id: UUID | None
    organization_id: UUID | None
    kind: FolderKind
    name: str
    parent_id: UUID | None
    sort_order: int
    path: str
    record_count: int


class FolderMove(BaseModel):
    """Moves records of the kind the route names into `folder_id` (`null` is the top level)."""

    record_ids: list[UUID] = Field(min_length=1, max_length=500)
    folder_id: UUID | None = None


class FolderMoveOut(BaseModel):
    """How many records a move changed (a record already in the folder is not counted)."""

    moved: int


# --- Collections and sharing -----------------------------------------------


class CollectionCreate(BaseModel):
    """Create payload for a collection."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)


class CollectionUpdate(BaseModel):
    """Partial update of a collection."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)


class CollectionMembersAdd(BaseModel):
    """The owner's elements to put in a collection (the tops of the subtrees to share)."""

    element_ids: list[UUID] = Field(min_length=1, max_length=500)


class CollectionMemberOut(BaseModel):
    """An element in a collection."""

    element_id: UUID
    unique_code: str
    name: str


class CollectionGrantCreate(BaseModel):
    """Access for one project (optionally with its descendants) or one group; name exactly one target."""

    project_id: UUID | None = None
    group: PrincipalRef | None = None
    include_descendants: bool = False


class CollectionGrantOut(BaseModel):
    """A grant with the name of what it reaches (`group` for a group grant, the project's name and code otherwise)."""

    id: UUID
    project_id: UUID | None
    project_name: str | None
    project_code: str | None
    group: PrincipalOut | None
    include_descendants: bool
    created_at: datetime


class CollectionOut(BaseModel):
    """A collection with its counts; `grants` is filled for a reader who may see who has access."""

    id: UUID
    project_id: UUID | None
    organization_id: UUID | None
    name: str
    description: str
    member_count: int
    grant_count: int
    grants: list[CollectionGrantOut]
    created_at: datetime
    updated_at: datetime


# --- Diagrams ----------------------------------------------------------------

#: A coordinate or size on the diagram canvas: finite and bounded, so a stored box cannot be used to break a renderer.
Coordinate = Annotated[float, Field(ge=-1_000_000, le=1_000_000, allow_inf_nan=False)]
Extent = Annotated[float, Field(ge=1, le=100_000, allow_inf_nan=False)]


class DiagramCreate(BaseModel):
    """Create payload for a diagram.

    Attributes:
        scope_element_id: The element whose inside the diagram shows, or `None` for the system context.
        connection_detail: Draw typed, labelled connections (otherwise plain lines).
        activate: Create the diagram `active` instead of `draft` (Save and activate).
        populate: Place the scope element's children (the root elements for the system context) in a grid.
    """

    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(default="", max_length=20000)
    scope_element_id: UUID | None = None
    connection_detail: bool = False
    folder_id: UUID | None = None
    activate: bool = False
    populate: bool = False


class DiagramUpdate(BaseModel):
    """Edit of a diagram's own fields. `version` is required; a field left out is kept, and `scope_element_id`
    set to `null` returns the diagram to the system context."""

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = Field(default=None, max_length=20000)
    scope_element_id: UUID | None = None
    connection_detail: bool | None = None
    folder_id: UUID | None = None


class DiagramOut(ProjectScopedRow):
    """A diagram with its counts. `scope_element_code` / `scope_element_name` are filled for a scope the viewer may read
    (the name is blank for one they may not)."""

    id: UUID
    project_id: UUID
    unique_code: str
    name: str
    purpose: str
    scope_element_id: UUID | None
    scope_element_code: str | None = None
    scope_element_name: str | None = None
    connection_detail: bool
    folder_id: UUID | None = None
    folder_path: str | None = None
    status: str
    allowed_status_moves: list[str]
    version: int
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    placement_count: int
    note_count: int
    toggle_count: int


class PlacementIn(BaseModel):
    """An element's box on a diagram."""

    element_id: UUID
    x: Coordinate = 0.0
    y: Coordinate = 0.0
    width: Extent = 160.0
    height: Extent = 80.0
    collapsed: bool = False


class NoteIn(BaseModel):
    """A plain-text note on a diagram (`id` keeps an existing note; none creates one)."""

    id: UUID | None = None
    text: str = Field(default="", max_length=2000)
    x: Coordinate = 0.0
    y: Coordinate = 0.0
    width: Extent = 160.0
    height: Extent = 60.0


class AnchorIn(BaseModel):
    """Where a drawn line meets its two boxes, chosen by a person. The line is the one joining the two placed elements
    (a merged or rolled-up line has one anchor for all it stands for); an end left `None` is automatic. At least one end
    is given."""

    source_element_id: UUID
    target_element_id: UUID
    source_point: AttachPoint | None = None
    target_point: AttachPoint | None = None


class AnchorOut(AnchorIn):
    """A stored anchor."""


class BoundaryIn(BaseModel):
    """A boundary box: the outer connection it stands for and its box on the diagram."""

    connection_id: UUID
    x: Coordinate = 0.0
    y: Coordinate = 0.0
    width: Extent = 120.0
    height: Extent = 48.0


class LayoutSave(BaseModel):
    """Replaces a diagram's placements, notes, line anchors and boundary boxes (what the editor saves). `version` is the
    optimistic lock; an element left out of `placements` is removed from the diagram (never from the model), with its
    anchors. `anchors` and `boundaries` left out (`None`) keep the stored ones; an empty list clears them."""

    version: int
    placements: list[PlacementIn] = Field(default_factory=list, max_length=2000)
    notes: list[NoteIn] = Field(default_factory=list, max_length=200)
    anchors: list[AnchorIn] | None = Field(default=None, max_length=5000)
    boundaries: list[BoundaryIn] | None = Field(default=None, max_length=2000)


class PlacementAdd(PlacementIn):
    """Places one more element on a diagram (`version` is the optimistic lock)."""

    version: int


class ToggleRule(BaseModel):
    """What a toggle matches besides its manual members: elements of the given types or domains, connections of the given
    types or domains, and records tagged with any of the tags. All lists are optional."""

    element_type_ids: list[UUID] = Field(default_factory=list, max_length=100)
    connection_type_ids: list[UUID] = Field(default_factory=list, max_length=100)
    domains: list[Domain] = Field(default_factory=list, max_length=3)
    tags: list[str] = Field(default_factory=list, max_length=50)


class ToggleIn(BaseModel):
    """One toggle: a name, its default state, its rule and its manual members (`id` keeps an existing toggle)."""

    id: UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    default_on: bool = True
    rule: ToggleRule = Field(default_factory=ToggleRule)
    element_ids: list[UUID] = Field(default_factory=list, max_length=2000)
    connection_ids: list[UUID] = Field(default_factory=list, max_length=2000)


class TogglesSave(BaseModel):
    """Replaces a diagram's toggles (`version` is the optimistic lock)."""

    version: int
    toggles: list[ToggleIn] = Field(default_factory=list, max_length=50)


class ToggleOut(BaseModel):
    """A toggle with its current state in the view (`on`)."""

    id: UUID
    name: str
    default_on: bool
    on: bool
    rule: ToggleRule
    element_ids: list[UUID]
    connection_ids: list[UUID]
    sort_order: int


class NoteOut(BaseModel):
    """A note on a diagram."""

    id: UUID
    text: str
    x: float
    y: float
    width: float
    height: float


class ViewPort(BaseModel):
    """A port of a placed element, as drawn."""

    id: UUID
    name: str
    direction: str
    connection_type_name: str | None


class ViewNode(BaseModel):
    """A placed element as the diagram draws it.

    A `locked` node is an element the viewer can no longer read: only its code is shown. `hidden` is a node a toggle
    switches off (kept in the placements, drawn on no export). `internal_connection_ids` are the connections wholly
    inside the element (drawn on no line)."""

    placement_id: UUID
    element_id: UUID
    unique_code: str
    name: str
    display_note: str = ""
    locked: bool
    shared: bool
    hidden: bool
    status: str
    parent_id: UUID | None
    element_type_id: UUID | None
    element_type_name: str
    shape: str
    color_light: str | None
    color_dark: str | None
    symbol_id: UUID | None
    ports: list[ViewPort]
    x: float
    y: float
    width: float
    height: float
    collapsed: bool
    internal_connection_ids: list[UUID]


class ViewBoundary(BaseModel):
    """A boundary box as the diagram draws it: the outer connection it stands for and the element outside.

    `shape` is a `BoundaryShape` value. A `locked` box is one whose outside element the viewer cannot read: only the
    connection's and the element's codes are given. `scope_end_element_id` is the element inside the scope the outer
    connection attaches to; `covered` is whether any connection realises the outer connection."""

    id: UUID
    connection_id: UUID
    connection_code: str
    connection_name: str
    type_name: str
    shape: str
    locked: bool
    outside_element_id: UUID
    outside_element_code: str
    outside_element_name: str
    scope_end_element_id: UUID
    scope_end_port_name: str | None
    covered: bool
    realised_by_count: int
    x: float
    y: float
    width: float
    height: float


class ViewHop(BaseModel):
    """A hidden element a bridged line passes through."""

    element_id: UUID
    unique_code: str
    name: str


class ViewEdge(BaseModel):
    """A line between two placed elements and the connections behind it.

    With connection detail off, `type_name`, `line_style`, `color_light`, `color_dark` and `label` are `None` (a plain
    line); with it on they describe the connections' shared type and protocol (`type_name` is `None` for mixed types).
    `connections` lists the underlying connections, which a selection shows either way."""

    id: str
    source_element_id: UUID
    target_element_id: UUID
    source_is_boundary: bool = False
    target_is_boundary: bool = False
    two_way: bool
    indirect: bool
    rolled_up: bool
    bridged: bool
    count: int
    type_name: str | None
    line_style: str | None
    color_light: str | None
    color_dark: str | None
    label: str | None
    connections: list[ConnectionOut]
    hops: list[ViewHop]


class DiagramView(BaseModel):
    """A diagram resolved for drawing: its record, toggles with their state, nodes, lines, notes and the line anchors a
    person chose (a line with none uses the nearest points)."""

    diagram: DiagramOut
    toggles: list[ToggleOut]
    nodes: list[ViewNode]
    edges: list[ViewEdge]
    notes: list[NoteOut]
    anchors: list[AnchorOut] = Field(default_factory=list)
    boundaries: list[ViewBoundary] = Field(default_factory=list)


class ModelElement(BaseModel):
    """An element as the editor needs it to draw a box and to resolve lines in the browser.

    A `locked` element is one the viewer cannot read: only its code is given, and its type, name and symbol are blank."""

    id: UUID
    unique_code: str
    name: str
    display_note: str = ""
    locked: bool
    shared: bool
    status: str
    element_type_id: UUID | None
    element_type_name: str
    color_light: str | None
    color_dark: str | None
    symbol_id: UUID | None


class ModelConnectionType(BaseModel):
    """A connection type's drawing attributes."""

    id: UUID
    name: str
    directional: bool
    line_style: str
    color_light: str | None
    color_dark: str | None


class ModelToggleMembers(BaseModel):
    """What one toggle switches off when it is off: its manual members plus whatever its rule matches."""

    toggle_id: UUID
    element_ids: list[UUID]
    connection_ids: list[UUID]


class ModelRealisation(BaseModel):
    """One inner connection realising one outer connection."""

    inner_connection_id: UUID
    outer_connection_id: UUID


class DiagramModel(BaseModel):
    """The model data a diagram's lines are resolved from, so the browser can redraw them while a layout is edited.

    `parents` maps every element listed, every connection end and every ancestor of one to its parent (a root to
    `None`). `connections` are the project's live connections as the viewer may read them."""

    elements: list[ModelElement]
    parents: dict[UUID, UUID | None]
    connections: list[ConnectionOut]
    connection_types: list[ModelConnectionType]
    toggle_members: list[ModelToggleMembers]
    realisations: list[ModelRealisation] = Field(default_factory=list)
