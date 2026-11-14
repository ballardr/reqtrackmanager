"""
Module: modules.architecture.state_machine_mermaid

Renders a state machine diagram (`schemas.StateMachineModel`) as Mermaid `stateDiagram-v2` text, for the Mermaid export
endpoint, so a diagram can be pasted into documentation that renders Mermaid.

Responsibilities:
- Write one declaration per state (code and name; a choice as `<<choice>>`), its entry, exit and do lines as descriptions,
  a composite state as a nested block of its child states, and one line per transition labelled `event [guard] / action`.
- Write an initial state as the start mark (`[*] --> target`) and a transition into a final state as an arrow to the end
  mark (`source --> [*]`), in the block they belong to.
- Make every user-supplied text safe, so no name, action or label can end its line, close a block or start a directive.

Design decisions:
- **Same data as the screen and the SVG.** It reads the model the editor reads, so the text cannot disagree with the drawing;
  the label rule is the shared `state_shapes.transition_label` with its line break written as a space (Mermaid reads one line).
- **A transition is written in the block of its two states** when they share a parent and at the top level when they do not,
  because Mermaid scopes the start and end marks to a block and draws a line that crosses blocks only from the top.
- Positions, sizes and attach points are left out: Mermaid lays the graph out itself. Several final states in one block
  collapse into the block's single end mark, which Mermaid cannot tell apart.
- A transition that leaves an initial state, or enters a final one, for a state in another block is not written: the marks
  belong to their own block and Mermaid has no mark that reaches across.
- A composite state's entry, exit and do lines are not written: Mermaid refuses a description on a block (its label is all
  it takes). The SVG omits them for the same reason of room.
- A choice's name is left out (Mermaid draws the diamond without text); its code is written as a comment line so the text
  still names it.

Dependencies: `schemas` (the model), `state_shapes` (the label rules).
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict

from app.modules.architecture.enums import StateKind
from app.modules.architecture.schemas import StateMachineModel, StateOut, TransitionOut
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


def render_state_machine_mermaid(model: StateMachineModel) -> str:
    """The state machine diagram as Mermaid `stateDiagram-v2` text.

    Args:
        model: The diagram with its states and transitions (`state_machines.model_of`).

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

    def block(parent: uuid.UUID | None, indent: str) -> list[str]:
        out: list[str] = []
        for s in children[parent]:
            kind, key = StateKind(s.kind), keys[s.id]
            if kind in (StateKind.INITIAL, StateKind.FINAL):
                continue
            if kind is StateKind.CHOICE:
                out += [f"{indent}%% {_text(s.unique_code)}", f"{indent}state {key} <<choice>>"]
                continue
            out.append(f'{indent}state "{_text(s.unique_code)} {_text(s.name)}" as {key}')
            if children[s.id]:
                out += [f"{indent}state {key} {{", *block(s.id, indent + "    "), f"{indent}}}"]
            else:
                out += [f"{indent}{key} : {_text(line)}" for line in action_lines(s.entry_action, s.exit_action, s.activity)]
        for t in scoped[parent]:
            line = f"{indent}{end(t.source_state_id, True)} --> {end(t.target_state_id, False)}"
            out.append(f"{line} : {_label(t)}" if _label(t) else line)
        return out

    head = f"{model.diagram.unique_code} {model.diagram.name}"
    lines = [f"%% {_CONTROL.sub(' ', head).strip()}", "stateDiagram-v2"]
    body = block(None, "    ")
    lines += body or ['    state "No states" as empty']
    return "\n".join(lines) + "\n"
