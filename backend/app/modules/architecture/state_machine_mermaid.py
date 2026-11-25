"""
Module: modules.architecture.state_machine_mermaid

Renders a state machine diagram (`schemas.StateMachineModel`) as Mermaid `stateDiagram-v2` text for the Mermaid export
endpoint, so a diagram can be pasted into documentation that renders Mermaid.

Responsibilities: one declaration per state (code and name; a choice as `<<choice>>`) with entry, exit and do lines as
descriptions; a composite state as a nested block; an initial state as `[*] --> target` and a transition into a final
state as `source --> [*]`, in their own block; one line per transition labelled `event [guard] / action`; every
user-supplied text made safe so none can end its line, close a block or start a directive.

Design decisions:
- It reads the model the editor reads, with the shared `state_shapes.transition_label` (line break written as a space),
  so the text cannot disagree with the drawing.
- A transition is written in the block of its two states when they share a parent, else at the top level, because
  Mermaid scopes start and end marks to a block. One leaving an initial state or entering a final one across blocks is
  not written.
- An annotation note is written as `note left|right of <state>` beside the first drawn, declared state its leaders point
  at. A note with no such leader (none, or only to a transition, a point, or an initial or final state) is not written:
  Mermaid has no free note and cannot point at a line. The SVG, PNG and bundle keep every note.
- Positions, sizes, attach points and vertices are left out (Mermaid lays out the graph); several final states in one
  block collapse into one end mark.
- Mermaid accepts no description on a composite state, so its entry, exit and do lines are not written. A choice's name
  and label are not drawn (the diamond has no text), so its code and label are written as a comment line.

Dependencies: `schemas` (the model), `state_shapes` (the label rules).
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict

from app.modules.architecture.enums import LeaderKind, StateKind
from app.modules.architecture.schemas import NoteOut, StateMachineModel, StateOut, TransitionOut
from app.modules.architecture.state_shapes import action_lines, transition_label

_CONTROL = re.compile(r"[\x00-\x1f\x7f  ￾￿]+")
#: Characters Mermaid reads as syntax in a label, replaced by a look-alike that cannot start a statement.
_REPLACEMENTS = {'"': "'", ";": ",", "{": "(", "}": ")"}


def _text(value: str) -> str:
    """User text made safe for a Mermaid state label, description or transition label: control characters become a space and
    the characters of `_REPLACEMENTS` are replaced."""
    return "".join(_REPLACEMENTS.get(ch, ch) for ch in _CONTROL.sub(" ", value).strip())


def _label(t: TransitionOut) -> str:
    """The text after a transition's colon, on one line."""
    return _text(transition_label(t.event, t.guard, t.action).replace("\n", " "))


def _note_lines(note: NoteOut) -> list[str]:
    """A note's text for a `note … end note` block: the title, then the typed lines. A line that would end the block is
    prefixed with a figure dash, so no text can close it early."""
    lines = [" ".join(note.title.split())] if note.title.strip() else []
    lines += note.text.strip().splitlines()
    safe = [_text(line) for line in lines if line.strip()]
    return [f"\u2012 {line}" if line.lower().startswith("end") else line for line in safe]


def render_state_machine_mermaid(model: StateMachineModel) -> str:
    """The state machine diagram as Mermaid `stateDiagram-v2` text.

    Args:
        model: The diagram with its states, transitions and notes (`state_machines.model_of`).

    Returns:
        The Mermaid text, ending in a newline.
    """
    states = {s.id: s for s in model.states}
    keys = {s.id: f"s{i}" for i, s in enumerate(model.states, start=1)}
    children: dict[uuid.UUID | None, list[StateOut]] = defaultdict(list)
    for s in model.states:
        children[s.parent_state_id if s.parent_state_id in states else None].append(s)
    parent_of = {s.id: (s.parent_state_id if s.parent_state_id in states else None) for s in model.states}
    scoped: dict[uuid.UUID | None, list[TransitionOut]] = defaultdict(list)
    for t in model.transitions:
        if t.source_state_id not in states or t.target_state_id not in states:
            continue
        same = parent_of[t.source_state_id] == parent_of[t.target_state_id]
        crossing_mark = StateKind(states[t.source_state_id].kind) is StateKind.INITIAL or StateKind(states[t.target_state_id].kind) is StateKind.FINAL
        if not same and crossing_mark:
            continue
        scoped[parent_of[t.source_state_id] if same else None].append(t)

    def end(state_id: uuid.UUID, as_source: bool) -> str:
        kind = StateKind(states[state_id].kind)
        if as_source and kind is StateKind.INITIAL or not as_source and kind is StateKind.FINAL:
            return "[*]"
        return keys[state_id]

    attached: dict[uuid.UUID, list[NoteOut]] = defaultdict(list)
    for note in model.notes:
        if not _note_lines(note):
            continue
        target = next((
            leader.state_id for leader in note.leaders
            if leader.kind == LeaderKind.STATE and leader.state_id in states
            and StateKind(states[leader.state_id].kind) not in (StateKind.INITIAL, StateKind.FINAL)
        ), None)
        if target is not None:
            attached[target].append(note)

    def notes_of(state: StateOut, indent: str) -> list[str]:
        """The note blocks beside a state."""
        out: list[str] = []
        for note in attached[state.id]:
            side = "right" if note.x + note.width / 2 >= state.x + state.width / 2 else "left"
            out += [f"{indent}note {side} of {keys[state.id]}", *(f"{indent}    {line}" for line in _note_lines(note)), f"{indent}end note"]
        return out

    def block(parent: uuid.UUID | None, indent: str) -> list[str]:
        out: list[str] = []
        for s in children[parent]:
            kind, key = StateKind(s.kind), keys[s.id]
            if kind in (StateKind.INITIAL, StateKind.FINAL):
                continue
            if kind is StateKind.CHOICE:
                out += [f"{indent}%% {_text(f'{s.unique_code} {s.label}'.strip())}", f"{indent}state {key} <<choice>>"]
                out += notes_of(s, indent)
                continue
            out.append(f'{indent}state "{_text(s.unique_code)} {_text(s.name)}" as {key}')
            if children[s.id]:
                out += [f"{indent}state {key} {{", *block(s.id, indent + "    "), f"{indent}}}"]
            else:
                out += [f"{indent}{key} : {_text(line)}" for line in action_lines(s.entry_action, s.exit_action, s.activity)]
            out += notes_of(s, indent)
        for t in scoped[parent]:
            line = f"{indent}{end(t.source_state_id, True)} --> {end(t.target_state_id, False)}"
            out.append(f"{line} : {_label(t)}" if _label(t) else line)
        return out

    head = f"{model.diagram.unique_code} {model.diagram.name}"
    lines = [f"%% {_CONTROL.sub(' ', head).strip()}", "stateDiagram-v2"]
    body = block(None, "    ")
    lines += body or ['    state "No states" as empty']
    return "\n".join(lines) + "\n"
