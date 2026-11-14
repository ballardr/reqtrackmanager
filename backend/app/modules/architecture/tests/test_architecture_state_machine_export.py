"""Tests for the state machine diagram's SVG and Mermaid exports: both draw the stored states and transitions (so a rename
reaches every export), the SVG is well-formed XML with every user text escaped, a composite state is a frame holding its
children, a self transition is a loop with its label, the Mermaid text keeps to the statements the export writes and writes
each stored state once, and both are read through the model's gate. The label rules the exports share are pinned here and
in `stateLabelCases.json`. Every test builds its own organisation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from sqlalchemy import event

from app.database import engine
from app.modules.architecture.state_shapes import action_lines, transition_label
from app.modules.architecture.tests._helpers import (
    add_state,
    add_transition,
    machine_model,
    make_architect,
    make_element,
    make_machine,
    project_base,
    setup,
    sound_machine,
)
from tests.conftest import auth_headers

LABEL_FILE = Path(__file__).resolve().parents[5] / "frontend" / "src" / "modules" / "architecture" / "stateLabelCases.json"
SVG = "{http://www.w3.org/2000/svg}"

#: The statements the Mermaid export writes after its header: a comment, a declaration, a description, a block's opening or
#: closing, and a transition.
_STATEMENT = re.compile(
    r"^ +(%% [^\n]*"
    r"|state \"[^\"\n]*\" as s\d+"
    r"|state s\d+ <<choice>>"
    r"|s\d+ : [^\n]*"
    r"|state s\d+ \{"
    r"|\}"
    r"|(\[\*\]|s\d+) --> (\[\*\]|s\d+)( : [^\n]*)?)$"
)

LABEL_CASES = [
    ("nothing", "", "", ""),
    ("an event only", "tick", "", ""),
    ("a guard only", "", "armed", ""),
    ("an event and a guard", "tick", "armed", ""),
    ("an action only", "", "", "log()"),
    ("a short one-line label", "tick", "armed", "log()"),
    ("a long label breaks before the action", "temperature_exceeded", "sensor_ok", "raise_alarm_and_stop()"),
    ("a long action with no head stays on one line", "", "", "a_very_long_action_name_that_has_no_head_to_keep()"),
]
ACTION_CASES = [
    ("none", "", "", ""),
    ("entry only", "init()", "", ""),
    ("all three", "init()", "release()", "poll()"),
    ("exit and do", "", "release()", "poll()"),
]


def _svg(client, token, project_id, machine_id, *, expect=200) -> str:
    resp = client.get(f"{project_base(project_id)}/state-machine-diagrams/{machine_id}/svg", headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.text


def _mermaid(client, token, project_id, machine_id, *, expect=200) -> str:
    resp = client.get(f"{project_base(project_id)}/state-machine-diagrams/{machine_id}/mermaid", headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.text


def _body(text: str) -> list[str]:
    lines = text.splitlines()
    assert lines[0].startswith("%% ") and lines[1] == "stateDiagram-v2" and text.endswith("\n")
    return lines[2:]


def _texts(svg: str) -> list[str]:
    return ["".join(t.itertext()) for t in ET.fromstring(svg).iter(f"{SVG}text")]


# --- Shared label rules --------------------------------------------------------


def label_cases() -> dict:
    """The label and action-line cases with what the Python rule gives, as the shared file holds them."""
    return {
        "labels": [
            {"name": n, "event": e, "guard": g, "action": a, "label": transition_label(e, g, a)} for n, e, g, a in LABEL_CASES
        ],
        "actions": [
            {"name": n, "entry": e, "exit": x, "activity": d, "lines": action_lines(e, x, d)} for n, e, x, d in ACTION_CASES
        ],
    }


def test_the_shared_label_cases_are_current():
    produced = json.dumps(label_cases(), indent=2) + "\n"
    if os.environ.get("UPDATE_SHAPE_CASES") == "1":
        LABEL_FILE.write_text(produced, encoding="utf-8")
    assert LABEL_FILE.read_text(encoding="utf-8") == produced, (
        "stateLabelCases.json is out of date with state_shapes; run this test with UPDATE_SHAPE_CASES=1, review the diff "
        "and update stateMachineModel.ts to match."
    )


def test_the_label_rules_write_event_guard_and_action_in_that_order():
    assert transition_label("tick", "armed", "log()") == "tick [armed] / log()"
    assert transition_label("", "", "log()") == "/ log()"
    assert transition_label("temperature_exceeded", "sensor_ok", "raise_alarm_and_stop()") == (
        "temperature_exceeded [sensor_ok]\n/ raise_alarm_and_stop()"
    )
    assert action_lines("a", "", "c") == ["entry / a", "do / c"]


# --- SVG -----------------------------------------------------------------------


def test_the_svg_is_well_formed_and_draws_each_state_and_transition(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd svg basic")
    element = make_element(client, token, project["id"], "Gear")
    machine, _states = sound_machine(client, token, project["id"], element["id"], "Gear modes")
    resp = client.get(f"{project_base(project['id'])}/state-machine-diagrams/{machine['id']}/svg", headers=auth_headers(token))
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("image/svg+xml")
    assert resp.headers["cache-control"] == "private, no-store" and resp.headers["x-content-type-options"] == "nosniff"
    root = ET.fromstring(resp.text)
    assert root.tag == f"{SVG}svg" and "SMD-001 Gear modes" in root.attrib["aria-label"]
    texts = _texts(resp.text)
    assert "Running" in texts and "STE-002" in texts and "entry / spin_up()" in texts and "halt" in texts
    model = machine_model(client, token, project["id"], machine["id"])
    assert len(model["transitions"]) == 2 and resp.text.count("marker-end") == 2
    # Two transition lines and the rule under Running's name (the only state with an action line).
    assert len(list(root.iter(f"{SVG}line"))) == 3


def test_an_empty_diagram_says_so(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd svg empty")
    element = make_element(client, token, project["id"], "Gear")
    machine = make_machine(client, token, project["id"], element["id"])
    assert "No states" in _texts(_svg(client, token, project["id"], machine["id"]))
    assert _body(_mermaid(client, token, project["id"], machine["id"])) == ['    state "No states" as empty']


def test_the_svg_is_the_same_bytes_twice_and_a_rename_reaches_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd svg rename")
    element = make_element(client, token, project["id"], "Gear")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    first = _svg(client, token, project["id"], machine["id"])
    assert _svg(client, token, project["id"], machine["id"]) == first
    version = machine_model(client, token, project["id"], machine["id"])["diagram"]["version"]
    resp = client.put(
        f"{project_base(project['id'])}/states/{states['Running']['id']}", json={"version": version, "name": "Spinning"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    after, text = _svg(client, token, project["id"], machine["id"]), _mermaid(client, token, project["id"], machine["id"])
    assert "Spinning" in _texts(after) and "Running" not in _texts(after) and "Spinning" in text and "Running" not in text


def test_a_composite_state_is_a_frame_drawn_before_its_children_and_a_self_transition_is_a_loop(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd svg composite")
    element = make_element(client, token, project["id"], "Gear")
    machine = make_machine(client, token, project["id"], element["id"], "Nested")
    on = add_state(client, token, project["id"], machine["id"], "On", x=0, y=0, width=400, height=240)
    idle = add_state(client, token, project["id"], machine["id"], "Idle", parent_state_id=on["id"], x=40, y=60, width=160, height=64)
    add_transition(client, token, project["id"], machine["id"], idle["id"], idle["id"], event="poll", guard="ready", action="read()")
    other = add_state(client, token, project["id"], machine["id"], "Away", x=500, y=0)
    add_transition(
        client, token, project["id"], machine["id"], idle["id"], other["id"], event="temperature_exceeded", guard="sensor_ok",
        action="raise_alarm_and_stop()",
    )
    svg = _svg(client, token, project["id"], machine["id"])
    ET.fromstring(svg)
    assert svg.index(">On<") < svg.index(">Idle<")  # the frame (parent) comes first
    assert 'y1="32.0" x2="400.0" y2="32.0"' in svg  # the header rule across the composite's frame
    assert len(re.findall(r'<path d="M [\d. -]+ C [\d. -]+"', svg)) == 1  # the loop
    texts = _texts(svg)
    assert "poll [ready] / read()" in texts  # a short label stays on one line
    assert "temperature_exceeded [sensor_ok]" in texts and "/ raise_alarm_and_stop()" in texts  # a long one breaks before the action


def test_a_marker_is_drawn_as_its_standard_shape_with_its_own_name(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd svg markers")
    element = make_element(client, token, project["id"], "Gear")
    machine = make_machine(client, token, project["id"], element["id"])
    start = add_state(client, token, project["id"], machine["id"], "Start", kind="initial", x=0, y=0, width=20, height=20)
    pick = add_state(client, token, project["id"], machine["id"], "Mode?", kind="choice", x=100, y=0, width=36, height=36)
    stop = add_state(client, token, project["id"], machine["id"], "Stop", kind="final", x=200, y=0, width=28, height=28)
    add_transition(client, token, project["id"], machine["id"], start["id"], pick["id"])
    add_transition(client, token, project["id"], machine["id"], pick["id"], stop["id"], guard="done")
    svg = _svg(client, token, project["id"], machine["id"])
    ET.fromstring(svg)
    texts = _texts(svg)
    assert svg.count("<circle") == 3 and svg.count("<polygon") == 1  # the dot, the ringed dot (two circles) and the diamond
    assert "Mode?" in texts and "Start" in texts and "Stop" in texts  # a marker is captioned with its own name


def test_every_user_text_is_escaped_in_the_svg(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd svg escape")
    element = make_element(client, token, project["id"], "Gear")
    hostile = '<script>alert(1)</script> "q" & <img src=x onerror=1>'
    machine = make_machine(client, token, project["id"], element["id"], hostile)
    a = add_state(client, token, project["id"], machine["id"], hostile, entry_action=hostile, x=0, y=0)
    b = add_state(client, token, project["id"], machine["id"], "B", x=300, y=0)
    add_transition(client, token, project["id"], machine["id"], a["id"], b["id"], event=hostile, guard=hostile, action=hostile)
    svg = _svg(client, token, project["id"], machine["id"])
    ET.fromstring(svg)  # well-formed: nothing ended an attribute or a text early
    assert "<script" not in svg and "<img" not in svg and "&lt;script&gt;" in svg


# --- Mermaid -------------------------------------------------------------------


def test_the_mermaid_text_writes_each_stored_state_once_and_each_transition(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd mermaid basic")
    element = make_element(client, token, project["id"], "Gear")
    machine, _states = sound_machine(client, token, project["id"], element["id"], "Gear modes")
    resp = client.get(f"{project_base(project['id'])}/state-machine-diagrams/{machine['id']}/mermaid", headers=auth_headers(token))
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/plain")
    assert resp.headers["x-content-type-options"] == "nosniff" and resp.headers["cache-control"] == "private, no-store"
    assert resp.text.splitlines()[0] == "%% SMD-001 Gear modes"
    body = _body(resp.text)
    assert all(_STATEMENT.match(x) for x in body), body
    declared = [x for x in body if x.lstrip().startswith("state ")]
    assert declared == ['    state "STE-002 Running" as s2']  # the initial and the final state are the start and end marks
    assert "    s2 : entry / spin_up()" in body
    assert "    [*] --> s2" in body and "    s2 --> [*] : halt" in body


def test_a_composite_state_is_a_nested_block_with_its_own_start_mark_and_a_choice_is_declared(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd mermaid nested")
    element = make_element(client, token, project["id"], "Gear")
    machine = make_machine(client, token, project["id"], element["id"], "Nested")
    on = add_state(client, token, project["id"], machine["id"], "On")
    start = add_state(client, token, project["id"], machine["id"], "Begin", kind="initial", parent_state_id=on["id"])
    idle = add_state(client, token, project["id"], machine["id"], "Idle", parent_state_id=on["id"])
    pick = add_state(client, token, project["id"], machine["id"], "Pick", kind="choice")
    off = add_state(client, token, project["id"], machine["id"], "Off")
    add_transition(client, token, project["id"], machine["id"], start["id"], idle["id"])
    add_transition(client, token, project["id"], machine["id"], on["id"], pick["id"], event="stop")
    add_transition(client, token, project["id"], machine["id"], pick["id"], off["id"], guard="ok")
    add_transition(client, token, project["id"], machine["id"], idle["id"], off["id"], event="crash")  # crosses the block
    text = _mermaid(client, token, project["id"], machine["id"])
    body = _body(text)
    assert all(_STATEMENT.match(x) for x in body), body
    opened = next(i for i, x in enumerate(body) if x.strip().startswith("state s1 {"))
    closed = next(i for i, x in enumerate(body) if x.strip() == "}")
    inside = body[opened + 1:closed]
    assert any("[*] --> s3" in x for x in inside) and any('"STE-003 Idle" as s3' in x for x in inside)
    assert "    state s4 <<choice>>" in body and "    s1 --> s4 : stop" in body and "    s4 --> s5 : [ok]" in body
    assert "    s3 --> s5 : crash" in body[closed + 1:]  # a transition between blocks is written outside both
    declared = [x.split(" as ")[1].split()[0] for x in body if " as s" in x]
    assert sorted(declared) == ["s1", "s3", "s5"] and len(declared) == len(set(declared))


def test_a_transition_between_a_marker_and_another_block_is_left_out(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd mermaid cross")
    element = make_element(client, token, project["id"], "Gear")
    machine = make_machine(client, token, project["id"], element["id"])
    on = add_state(client, token, project["id"], machine["id"], "On")
    inner_start = add_state(client, token, project["id"], machine["id"], "Begin", kind="initial", parent_state_id=on["id"])
    outer = add_state(client, token, project["id"], machine["id"], "Elsewhere")
    add_transition(client, token, project["id"], machine["id"], inner_start["id"], outer["id"])
    assert "[*]" not in _mermaid(client, token, project["id"], machine["id"])


def test_every_user_text_is_made_safe_in_the_mermaid_text(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd mermaid escape")
    element = make_element(client, token, project["id"], "Gear")
    hostile = 'A "b"; {c}\nstate x { %%{init: {}}%% }'
    machine = make_machine(client, token, project["id"], element["id"], hostile)
    a = add_state(client, token, project["id"], machine["id"], hostile, entry_action=hostile)
    b = add_state(client, token, project["id"], machine["id"], "B")
    add_transition(client, token, project["id"], machine["id"], a["id"], b["id"], event=hostile, guard=hostile, action=hostile)
    text = _mermaid(client, token, project["id"], machine["id"])
    body = _body(text)
    assert all(_STATEMENT.match(x) for x in body), body
    assert not any(x.strip().startswith("%%{") for x in text.splitlines()) and len(text.splitlines()) == 2 + len(body)
    assert not any(ch in "\n".join(body) for ch in "{}")  # no block opens or closes from user text


def test_the_mermaid_text_is_read_by_the_real_parser(client, admin_token, tmp_path):
    """A nested diagram with a start mark, a choice, a loop, a final state and hostile text parses with Mermaid itself.
    Skipped where `node` or the parser's packages (`scripts/mermaid_parse.mjs`) are not installed."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    _org, project, token = setup(client, admin_token, "Arch smd mermaid parse")
    element = make_element(client, token, project["id"], "Gear")
    p = project["id"]
    machine = make_machine(client, token, p, element["id"], "Parsed; {x}")
    m = machine["id"]
    start = add_state(client, token, p, m, "Start", kind="initial")
    on = add_state(client, token, p, m, "On", entry_action="never written for a block")
    begin = add_state(client, token, p, m, "Begin", kind="initial", parent_state_id=on["id"])
    idle = add_state(client, token, p, m, 'Idle "x"; {y}', parent_state_id=on["id"], entry_action="init()", activity="poll()")
    pick = add_state(client, token, p, m, "Mode?", kind="choice")
    off = add_state(client, token, p, m, "Off")
    stop = add_state(client, token, p, m, "Stop", kind="final")
    for source, target, fields in (
        (start, on, {}), (begin, idle, {}), (idle, idle, {"event": "poll", "guard": "ready", "action": "read()"}),
        (on, pick, {"event": "temperature_exceeded", "guard": "sensor_ok", "action": "raise_alarm_and_stop()"}),
        (pick, off, {"guard": "ok"}), (off, stop, {"event": "done; {x}"}), (idle, off, {"event": "crash"}),
    ):
        add_transition(client, token, p, m, source["id"], target["id"], **fields)
    file = tmp_path / "machine.mmd"
    file.write_text(_mermaid(client, token, p, m), encoding="utf-8")
    script = Path(__file__).resolve().parents[5] / "scripts" / "mermaid_parse.mjs"
    done = subprocess.run(["node", str(script), str(file)], capture_output=True, text=True, timeout=120, check=False)
    if done.returncode == 2:
        pytest.skip("the Mermaid parser is not installed (npm ci in frontend and docs/website)")
    assert done.returncode == 0, done.stdout + done.stderr


# --- Access --------------------------------------------------------------------


def test_the_exports_need_the_state_machine_sub_component_and_a_readable_element(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch smd export gate")
    element = make_element(client, token, project["id"], "Gear")
    machine, _states = sound_machine(client, token, project["id"], element["id"])
    reader = make_architect(client, token, org["id"], project["id"], "arch.smd.export@example.com")
    assert _svg(client, reader, project["id"], machine["id"])
    assert client.get(f"{project_base(project['id'])}/state-machine-diagrams/{machine['id']}/svg").status_code in (401, 403)


def test_the_exports_use_the_same_number_of_statements_however_large_the_diagram(client, admin_token):
    """Both exports read the model (states, transitions, element names) in bulk, so a larger diagram costs no more."""
    _org, project, token = setup(client, admin_token, "Arch smd export reads")
    element = make_element(client, token, project["id"], "Gear")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    urls = [f"{project_base(project['id'])}/state-machine-diagrams/{machine['id']}/{kind}" for kind in ("svg", "mermaid")]

    def count(url) -> int:
        seen: list[str] = []

        def record(_conn, _cursor, statement, *_args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            assert client.get(url, headers=auth_headers(token)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    few = [count(u) for u in urls]
    previous = states["Running"]
    for i in range(8):
        nxt = add_state(client, token, project["id"], machine["id"], f"More {i}", x=100 * i, y=200)
        add_transition(client, token, project["id"], machine["id"], previous["id"], nxt["id"], event=f"e{i}")
        previous = nxt
    assert [count(u) for u in urls] == few
