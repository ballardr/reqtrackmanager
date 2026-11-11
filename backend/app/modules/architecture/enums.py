"""
Module: modules.architecture.enums

Architecture-owned vocabulary, kept in this package rather than
`app.models.enums` because these are domain concepts this module owns.

The values are rendering and classification choices, not record states: a type
picks one `Domain`, an element type one `ElementShape` and a connection type
one `LineStyle`. They are stored as plain strings, so adding a value needs no
column change.
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
