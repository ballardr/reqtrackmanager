"""
Module: modules.architecture.enums

Architecture-owned vocabulary, kept in this package rather than
`app.models.enums` because these are domain concepts this module owns.

`Domain`, `ElementShape` and `LineStyle` are rendering and classification choices
of a type; `RecordStatus` and `PortDirection` classify a record and its ports;
`AttachPoint` names the eight places a line can meet a box on a diagram. All
are stored as plain strings, so adding a value needs no column change.
"""

from __future__ import annotations

import enum


class Domain(str, enum.Enum):
    """Which kind of architecture a type belongs to; `ANY` suits both."""

    SOFTWARE = "software"
    HARDWARE = "hardware"
    ANY = "any"


class ElementShape(str, enum.Enum):
    """The outline an element type is drawn with when it has no symbol."""

    RECTANGLE = "rectangle"
    ROUNDED = "rounded"
    CYLINDER = "cylinder"
    HEXAGON = "hexagon"
    ELLIPSE = "ellipse"
    PARALLELOGRAM = "parallelogram"
    FOLDER = "folder"
    CHIP = "chip"


class LineStyle(str, enum.Enum):
    """How a connection type is drawn."""

    SOLID = "solid"
    DASHED = "dashed"
    DOTTED = "dotted"


class RecordStatus(str, enum.Enum):
    """The lifecycle of an element, a connection or a diagram. There is no approval gate: a person who may manage the
    record may make any move `transitions.STATUS_MOVES` lists (a retired record can be reactivated)."""

    DRAFT = "draft"
    PLANNED = "planned"
    ACTIVE = "active"
    RETIRED = "retired"


class PortDirection(str, enum.Enum):
    """Which way traffic crosses a port, seen from its element."""

    IN = "in"
    OUT = "out"
    BOTH = "both"


class BoundaryShape(str, enum.Enum):
    """How a boundary box is drawn, from the direction of the outer connection it stands for, seen from inside the
    scope: `INPUT` (the scope receives), `OUTPUT` (the scope sends), `BIDIRECTIONAL` (a two-way connection) and `DOT`
    (no direction disclosed, as when the viewer cannot read the element outside)."""

    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"
    DOT = "dot"


class AttachPoint(str, enum.Enum):
    """One of the eight places on a box where a diagram line can meet it: the middle of each side and the four corners."""

    TOP = "top"
    RIGHT = "right"
    BOTTOM = "bottom"
    LEFT = "left"
    TOP_RIGHT = "top_right"
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM_LEFT = "bottom_left"
    TOP_LEFT = "top_left"
