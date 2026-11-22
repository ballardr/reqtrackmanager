"""
Module: modules.architecture.enums

Architecture-owned vocabulary, kept in this package rather than
`app.models.enums` because these are domain concepts this module owns.

`ElementShape` and `LineStyle` are rendering choices of a type; `RecordStatus` and `PortDirection` classify a record and its ports;
`AttachPoint` names the eight places a line can meet a box on a diagram; `NoteTone` and `LeaderKind` describe an
annotation note and what its leader points at; `LineEnd` is how a leader begins or ends. All are stored as plain
strings, so adding a value needs no column change.
"""

from __future__ import annotations

import enum

#: The longest display note an element may carry (characters): the line drawn inside its box on a diagram.
DISPLAY_NOTE_MAX = 500

#: The longest title an annotation note may carry (characters): the bold line drawn above its text.
NOTE_TITLE_MAX = 120

#: The longest label an initial, final or choice symbol may carry (characters): the text drawn inside the symbol.
SYMBOL_LABEL_LENGTH = 256


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


class LineShape(str, enum.Enum):
    """How a drawn line runs between its ends (a connection, a transition or a note's leader). Named apart from `LineStyle`,
    which is how a connection type is stroked (solid, dashed, dotted)."""

    STRAIGHT = "straight"
    CURVED = "curved"
    SPLINE = "spline"


class RecordStatus(str, enum.Enum):
    """The lifecycle of an element, a connection or a diagram. There is no approval gate: a person who may manage the
    record may make any move `transitions.STATUS_MOVES` lists (a retired record can be reactivated, a rejected one reopened as a draft)."""

    DRAFT = "draft"
    PROPOSED = "proposed"
    ACTIVE = "active"
    RETIRED = "retired"
    REJECTED = "rejected"


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


class NoteTone(str, enum.Enum):
    """The colour family of an annotation note on a diagram, drawn from the theme's tokens (light and dark). `NONE` draws
    the text alone, with no fill, border or dashed outline."""

    NONE = "none"
    NEUTRAL = "neutral"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"


class NoteAlign(str, enum.Enum):
    """How the title and the text of an annotation note are aligned in its block. Full justification is not offered: SVG has
    no justified text, so the exports could not match the screen."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class NoteSizeMode(str, enum.Enum):
    """Whether an annotation note is drawn at the size stored for it (Manual) or at the size its content needs (Automatic)."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class LeaderKind(str, enum.Enum):
    """What an annotation note's leader line ends at: a placed element's box, a connection's drawn line (its midpoint), a
    state machine diagram's state or transition, or a free point of the canvas. (`NONE` is a note with no leader: it has no
    leader row, so a stored leader is never `NONE`.) A block diagram's notes use `element`, `connection` and `point`; a state
    machine diagram's use `state`, `transition` and `point`."""

    NONE = "none"
    ELEMENT = "element"
    CONNECTION = "connection"
    STATE = "state"
    TRANSITION = "transition"
    POINT = "point"


class LineEnd(str, enum.Enum):
    """How a leader line begins or ends: plain, with an arrowhead or with a dot."""

    NONE = "none"
    ARROW = "arrow"
    DOT = "dot"


class FolderKind(str, enum.Enum):
    """Which list a folder organises; each kind has its own tree of folders."""

    ELEMENT = "element"
    CONNECTION = "connection"
    DIAGRAM = "diagram"
    SYMBOL = "symbol"


class StateKind(str, enum.Enum):
    """What a state of a state machine diagram is: the single `INITIAL` start marker of a level, an ordinary `STATE`, a
    `FINAL` end marker or a `CHOICE` (a diamond whose outgoing transitions are chosen by their guards). A composite state
    is an ordinary state that has child states, not a kind of its own."""

    INITIAL = "initial"
    STATE = "state"
    FINAL = "final"
    CHOICE = "choice"


class LabelPosition(str, enum.Enum):
    """Where an initial, final or choice symbol's label is drawn: `INSIDE` the symbol (which grows to hold it), or outside it
    on one side, against the symbol at its plain notation size."""

    INSIDE = "inside"
    LEFT = "left"
    RIGHT = "right"
    ABOVE = "above"
    BELOW = "below"


class ValidationSeverity(str, enum.Enum):
    """How serious a validation issue on a state machine diagram is: an `ERROR` blocks activation, a `WARNING` never does."""

    ERROR = "error"
    WARNING = "warning"
