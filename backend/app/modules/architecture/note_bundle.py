"""
Module: modules.architecture.note_bundle

How an annotation note and its leader lines are written to a project bundle and read back, for both diagram types (`export`
carries a block diagram's, `state_machine_export` a state machine diagram's). Only what the two share is here: the note's own
block, tone, title, alignment and size mode, and a leader's line (start point, vertices, curve, ends). What a leader points at
differs, so each exporter adds and resolves its own target.

Responsibilities:
- `note_json` / `leader_json`: the bundle's shape of a note and of a leader's line, without targets.
- `note_row` / `leader_row`: the stored row for a bundled one, with every value validated (a bundle is not trusted to
  respect the caps or the vocabularies, and an older bundle lacks the newer fields).

Design decisions:
- A leader's target is never read here: it names records by portable key (a code, a name, a position), which only the owner of
  the diagram can resolve.

Dependencies: this module's models, enums and `diagram_line_path`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.modules.architecture.diagram_line_path import clean_waypoints
from app.modules.architecture.enums import (
    NOTE_TITLE_MAX,
    AttachPoint,
    LineEnd,
    NoteAlign,
    NoteSizeMode,
    NoteTone,
)
from app.modules.architecture.models import ArchitectureDiagramNote, ArchitectureNoteLeader


def note_json(note: ArchitectureDiagramNote) -> dict[str, Any]:
    """A note for the bundle: its title, text, alignment, size mode, block and tone (its leaders are added by the exporter).

    Args:
        note: The stored note.

    Returns:
        The bundle row.
    """
    return {
        "title": note.title, "text_align": note.text_align, "size_mode": note.size_mode, "text": note.text, "x": note.x,
        "y": note.y, "width": note.width, "height": note.height, "tone": note.tone,
    }


def leader_json(leader: ArchitectureNoteLeader) -> dict[str, Any]:
    """A leader's line for the bundle: its kind, start point, vertices, curve and ends (the exporter adds its target).

    Args:
        leader: The stored leader.

    Returns:
        The bundle row.
    """
    return {
        "kind": leader.kind, "start_point": leader.start_point, "points": clean_waypoints(leader.points), "smooth": leader.smooth,
        "start_style": leader.start_style, "end_style": leader.end_style,
    }


def note_row(raw: dict[str, Any], order: int, **owner: UUID) -> ArchitectureDiagramNote:
    """The note row for a bundled note, validated: an unknown tone reads as neutral, an unknown alignment as left, a title is cut
    to its cap, and an older bundle with no size mode keeps a toned note at its drawn size and sizes a note with no tone to
    its text (as an upgrade does).

    Args:
        raw: The bundled note.
        order: Its position among the diagram's notes.
        **owner: The owner column and its id (`diagram_id=` or `state_machine_diagram_id=`).

    Returns:
        A new, unadded row.
    """
    tone, align, title = raw.get("tone"), raw.get("text_align"), raw.get("title")
    tone = tone if tone in {t.value for t in NoteTone} else NoteTone.NEUTRAL.value
    size_mode = raw.get("size_mode")
    return ArchitectureDiagramNote(
        id=uuid4(), text=raw.get("text", ""), x=raw.get("x", 0.0), y=raw.get("y", 0.0), width=raw.get("width", 160.0),
        height=raw.get("height", 60.0), sort_order=order, tone=tone,
        size_mode=size_mode if size_mode in {m.value for m in NoteSizeMode} else (
            NoteSizeMode.AUTOMATIC.value if tone == NoteTone.NONE.value else NoteSizeMode.MANUAL.value
        ),
        title=title[:NOTE_TITLE_MAX] if isinstance(title, str) else "",
        text_align=align if align in {a.value for a in NoteAlign} else NoteAlign.LEFT.value,
        **owner,
    )


def leader_row(note_id: UUID, order: int, raw: dict[str, Any]) -> ArchitectureNoteLeader:
    """The leader row for a bundled leader's line, validated: an unknown start point reads as automatic, an unknown end style
    as plain (start) or an arrowhead (end), vertices are cleaned. The caller sets the target column of its kind.

    Args:
        note_id: The note.
        order: Its position among the note's leaders.
        raw: The bundled leader.

    Returns:
        A new, unadded row with no target.
    """
    valid_points = {p.value for p in AttachPoint}
    valid_ends = {e.value for e in LineEnd}
    return ArchitectureNoteLeader(
        note_id=note_id, sort_order=order, kind=str(raw.get("kind")), points=clean_waypoints(raw.get("points")),
        smooth=raw.get("smooth") is True,
        start_point=raw.get("start_point") if raw.get("start_point") in valid_points else None,
        start_style=raw.get("start_style") if raw.get("start_style") in valid_ends else LineEnd.NONE.value,
        end_style=raw.get("end_style") if raw.get("end_style") in valid_ends else LineEnd.ARROW.value,
    )
