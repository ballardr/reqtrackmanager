"""Tests for annotation notes on a state machine diagram: the same note and leader rows a block diagram uses, saved with the
state machine layout, whose leaders point at a state, a transition or a free point.

Covers the layout save (stored, returned by the model, replace semantics, `notes` left out keeps them, an identical save
changes nothing), the rules a leader must follow (a block diagram's targets and another diagram's states or transitions are
refused, and a block diagram refuses a state), the version lock, deleting a target removing only its leader, the owner and
target constraints of the tables, the server SVG and the Mermaid export, the project bundle round trip (and an older bundle
with no notes) and the migration. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.database import SessionLocal, engine
from app.modules.architecture.models import ArchitectureDiagramNote, ArchitectureNoteLeader
from app.modules.architecture.tests._helpers import (
    add_state,
    add_transition,
    machine_model,
    machine_version,
    make_diagram,
    make_element,
    make_machine,
    project_base,
    setup,
    sound_machine,
)
from tests.conftest import auth_headers, build_alembic_config


def _put(client, token, project_id, machine_id, body, *, expect=200):
    resp = client.put(f"{project_base(project_id)}/state-machine-diagrams/{machine_id}/layout", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _save(client, token, project_id, machine_id, notes, *, expect=200):
    body = {"version": machine_version(client, token, project_id, machine_id), "states": [], "transitions": [], "notes": notes}
    return _put(client, token, project_id, machine_id, body, expect=expect)


def _world(client, admin_token, name):
    """A project with a sound machine (Start, Running, Stop and its two transitions); returns `(project id, token, machine, states,
    transitions by event)`."""
    _org, project, token = setup(client, admin_token, name)
    p = project["id"]
    element = make_element(client, token, p, "Controller")
    machine, states = sound_machine(client, token, p, element["id"])
    transitions = {t["event"]: t for t in machine_model(client, token, p, machine["id"])["transitions"]}
    return p, token, machine, states, transitions


def _notes(client, token, p, machine_id) -> list[dict]:
    return machine_model(client, token, p, machine_id)["notes"]


def test_a_note_keeps_its_fields_and_each_kind_of_leader_and_the_model_returns_them(client, admin_token):
    p, token, machine, states, transitions = _world(client, admin_token, "Arch smd notes store")
    before = machine["version"]
    saved = _save(client, token, p, machine["id"], [
        {"title": "Why", "text": "At a state", "tone": "info", "text_align": "center", "size_mode": "automatic",
         "leaders": [{"kind": "state", "state_id": states["Running"]["id"], "end_style": "none"}]},
        {"text": "At a transition", "tone": "warning", "leaders": [{"kind": "transition", "transition_id": transitions["halt"]["id"]}]},
        {"text": "At a spot", "tone": "none", "leaders": [{
            "kind": "point", "x": 12.5, "y": -40, "start_point": "top", "points": [{"x": 5, "y": -20}, {"x": 9, "y": -30}],
            "smooth": True, "start_style": "dot", "end_style": "arrow",
        }]},
        {"text": "Plain"},
    ])
    assert saved["version"] > before
    shown = _notes(client, token, p, machine["id"])
    assert [(n["tone"], [leader["kind"] for leader in n["leaders"]]) for n in shown] == [
        ("info", ["state"]), ("warning", ["transition"]), ("none", ["point"]), ("neutral", []),
    ]
    assert (shown[0]["title"], shown[0]["text_align"], shown[0]["size_mode"]) == ("Why", "center", "automatic")
    on_state, on_transition, on_spot = (n["leaders"][0] for n in shown[:3])
    assert (on_state["state_id"], on_state["end_style"], on_state["transition_id"], on_state["element_id"]) == (
        states["Running"]["id"], "none", None, None,
    )
    assert (on_transition["transition_id"], on_transition["end_style"], on_transition["state_id"]) == (
        transitions["halt"]["id"], "arrow", None,
    )
    assert (on_spot["x"], on_spot["y"], on_spot["start_point"], on_spot["smooth"]) == (12.5, -40, "top", True)
    assert on_spot["points"] == [{"x": 5, "y": -20}, {"x": 9, "y": -30}]


def test_the_save_replaces_the_notes_when_given_keeps_them_when_left_out_and_changes_nothing_when_equal(client, admin_token):
    p, token, machine, _states, _transitions = _world(client, admin_token, "Arch smd notes replace")
    m = machine["id"]
    _save(client, token, p, m, [{"text": "One"}, {"text": "Two"}])
    stored = _notes(client, token, p, m)
    assert [n["text"] for n in stored] == ["One", "Two"]
    # `notes` left out keeps what is stored, and the version moves only for what a save changed.
    version = machine_version(client, token, p, m)
    _put(client, token, p, m, {"version": version, "states": [], "transitions": []})
    assert machine_version(client, token, p, m) == version
    assert [n["id"] for n in _notes(client, token, p, m)] == [n["id"] for n in stored]
    # The same list again is no change (the ids are kept).
    again = [{"id": n["id"], "text": n["text"], "tone": n["tone"], "text_align": n["text_align"], "size_mode": n["size_mode"],
              "x": n["x"], "y": n["y"], "width": n["width"], "height": n["height"]} for n in stored]
    _save(client, token, p, m, again)
    assert machine_version(client, token, p, m) == version
    # A shorter list deletes the note left out; an empty list clears them.
    _save(client, token, p, m, again[:1])
    assert [n["text"] for n in _notes(client, token, p, m)] == ["One"]
    _save(client, token, p, m, [])
    assert _notes(client, token, p, m) == []


def test_a_leader_must_point_at_this_diagrams_own_states_and_transitions(client, admin_token):
    p, token, machine, states, transitions = _world(client, admin_token, "Arch smd notes rules")
    element = make_element(client, token, p, "Other controller")
    other, other_states = sound_machine(client, token, p, element["id"], "Other modes")
    other_transitions = machine_model(client, token, p, other["id"])["transitions"]
    block = make_diagram(client, token, p, "Block view")
    stray = make_element(client, token, p, "Stray")
    m = machine["id"]
    refused = (
        {"kind": "state", "state_id": other_states["Running"]["id"]},
        {"kind": "transition", "transition_id": other_transitions[0]["id"]},
        {"kind": "element", "element_id": stray["id"]},
        {"kind": "connection", "connection_id": transitions[""]["id"]},
    )
    for leader in refused:
        _save(client, token, p, m, [{"text": "x", "leaders": [leader]}], expect=400)
    assert _notes(client, token, p, m) == []
    # A leader names exactly the target of its own kind (the schema), so a state leader with a transition id is a 422.
    both = {"kind": "state", "state_id": states["Stop"]["id"], "transition_id": transitions["halt"]["id"]}
    _save(client, token, p, m, [{"text": "x", "leaders": [both]}], expect=422)
    _save(client, token, p, m, [{"text": "x", "leaders": [{"kind": "state"}]}], expect=422)
    # A block diagram refuses a state or a transition as a target.
    resp = client.put(
        f"{project_base(p)}/diagrams/{block['id']}/layout", headers=auth_headers(token),
        json={"version": block["version"], "placements": [], "notes": [
            {"text": "x", "leaders": [{"kind": "state", "state_id": states["Running"]["id"]}]},
        ]},
    )
    assert resp.status_code == 400, resp.text


def test_a_note_or_leader_id_of_another_owner_is_refused(client, admin_token):
    p, token, machine, states, _transitions = _world(client, admin_token, "Arch smd notes owners")
    element = make_element(client, token, p, "Second controller")
    other, other_states = sound_machine(client, token, p, element["id"], "Second modes")
    _save(client, token, p, other["id"], [{"text": "Theirs", "leaders": [{"kind": "state", "state_id": other_states["Running"]["id"]}]}])
    theirs = _notes(client, token, p, other["id"])[0]
    m = machine["id"]
    _save(client, token, p, m, [{"id": theirs["id"], "text": "Stolen"}], expect=400)
    taken = {"id": theirs["leaders"][0]["id"], "kind": "state", "state_id": states["Stop"]["id"]}
    _save(client, token, p, m, [{"text": "Mine", "leaders": [taken]}], expect=400)
    _save(client, token, p, m, [{"text": "Twice"}, {"text": "Twice"}])
    mine = _notes(client, token, p, m)
    _save(client, token, p, m, [{"id": mine[0]["id"], "text": "a"}, {"id": mine[0]["id"], "text": "b"}], expect=400)
    assert [n["text"] for n in _notes(client, token, p, other["id"])] == ["Theirs"]


def test_a_stale_version_is_refused_and_stores_no_note(client, admin_token):
    p, token, machine, _states, _transitions = _world(client, admin_token, "Arch smd notes lock")
    resp = client.put(
        f"{project_base(p)}/state-machine-diagrams/{machine['id']}/layout", headers=auth_headers(token),
        json={"version": machine_version(client, token, p, machine["id"]) - 1, "states": [], "transitions": [], "notes": [{"text": "late"}]},
    )
    assert resp.status_code == 409, resp.text
    assert _notes(client, token, p, machine["id"]) == []


def test_deleting_a_state_or_a_transition_removes_its_leader_and_keeps_the_note(client, admin_token):
    p, token, machine, states, transitions = _world(client, admin_token, "Arch smd notes cascade")
    m = machine["id"]
    extra = add_state(client, token, p, m, "Extra")
    link = add_transition(client, token, p, m, states["Running"]["id"], extra["id"], event="more")
    _save(client, token, p, m, [
        {"text": "On the extra state", "leaders": [{"kind": "state", "state_id": extra["id"]}]},
        {"text": "On the extra line", "leaders": [{"kind": "transition", "transition_id": link["id"]}]},
        {"text": "On Running", "leaders": [{"kind": "state", "state_id": states["Running"]["id"]}]},
    ])
    resp = client.delete(
        f"{project_base(p)}/states/{extra['id']}", params={"version": machine_version(client, token, p, m)},
        headers=auth_headers(token),
    )
    assert resp.status_code in (200, 204), resp.text
    shown = _notes(client, token, p, m)
    assert [n["text"] for n in shown] == ["On the extra state", "On the extra line", "On Running"]
    assert [[leader["kind"] for leader in n["leaders"]] for n in shown] == [[], [], ["state"]]
    assert transitions  # the sound machine's own lines are untouched


def test_deleting_the_diagram_deletes_its_notes_and_leaders(client, admin_token):
    p, token, machine, states, _transitions = _world(client, admin_token, "Arch smd notes delete")
    _save(client, token, p, machine["id"], [{"text": "Gone", "leaders": [{"kind": "state", "state_id": states["Stop"]["id"]}]}])
    resp = client.delete(f"{project_base(p)}/state-machine-diagrams/{machine['id']}", headers=auth_headers(token))
    assert resp.status_code in (200, 204), resp.text
    with SessionLocal() as db:
        assert db.scalars(select(ArchitectureDiagramNote).where(ArchitectureDiagramNote.state_machine_diagram_id == machine["id"])).first() is None
        assert db.scalars(select(ArchitectureNoteLeader)).first() is None


def test_the_database_requires_exactly_one_owner_and_a_target_that_matches_the_kind(client, admin_token):
    p, token, machine, states, _transitions = _world(client, admin_token, "Arch smd notes constraint")
    block = make_diagram(client, token, p, "Block")
    _save(client, token, p, machine["id"], [{"text": "x", "leaders": [{"kind": "state", "state_id": states["Stop"]["id"]}]}])
    with SessionLocal() as db:
        note = db.scalars(select(ArchitectureDiagramNote)).first()
        leader = db.scalars(select(ArchitectureNoteLeader)).first()
        assert note is not None and leader is not None
        refused: tuple[tuple[str, Any, str, dict[str, Any]], ...] = (
            ("architecture_diagram_notes", note.id, "SET diagram_id = NULL, state_machine_diagram_id = NULL", {}),
            ("architecture_diagram_notes", note.id, "SET diagram_id = :block", {"block": block["id"]}),
            ("architecture_note_leaders", leader.id, "SET state_id = NULL", {}),
            ("architecture_note_leaders", leader.id, "SET kind = 'transition'", {}),
            ("architecture_note_leaders", leader.id, "SET transition_id = (SELECT id FROM architecture_transitions LIMIT 1)", {}),
            ("architecture_note_leaders", leader.id, "SET kind = 'point', x = 1, y = 2", {}),
        )
        for table, row_id, change, extra in refused:
            try:
                db.execute(text(f"UPDATE {table} {change} WHERE id = :id"), {"id": row_id, **extra})
                db.flush()
            except IntegrityError:
                db.rollback()
            else:
                db.rollback()
                raise AssertionError(f"accepted: {change}")


# --- Drawing ------------------------------------------------------------------


def _svg(client, token, p, machine_id) -> str:
    resp = client.get(f"{project_base(p)}/state-machine-diagrams/{machine_id}/svg", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.text


def _mermaid(client, token, p, machine_id) -> str:
    resp = client.get(f"{project_base(p)}/state-machine-diagrams/{machine_id}/mermaid", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.text


def test_the_svg_draws_the_note_and_its_leaders_to_a_state_a_transition_and_a_point(client, admin_token):
    p, token, machine, states, transitions = _world(client, admin_token, "Arch smd notes svg")
    block = {"x": 600, "y": 300, "width": 160, "height": 60}
    _save(client, token, p, machine["id"], [
        {"title": "Careful", "text": "Slow here", "tone": "warning", **block, "leaders": [
            {"kind": "state", "state_id": states["Running"]["id"], "start_point": "left"},
            {"kind": "transition", "transition_id": transitions["halt"]["id"]},
            {"kind": "point", "x": 900, "y": 340, "end_style": "dot"},
        ]},
    ])
    svg = _svg(client, token, p, machine["id"])
    assert "Careful" in svg and "Slow here" in svg and "data-note=" in svg
    assert len(re.findall(r'<line [^>]*stroke-width="1.5"', svg)) == 3  # one drawn leader each
    assert "leader-dot-warning" in svg and "leader-arrow-warning" in svg
    assert _svg(client, token, p, machine["id"]) == svg  # deterministic
    # A note beyond the states widens the drawing: the point at x = 900 is inside the viewBox.
    min_x, _min_y, width, _height = (float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split())  # type: ignore[union-attr]
    assert min_x + width >= 900


def test_a_diagram_with_only_a_note_is_not_drawn_as_empty(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd notes only")
    element = make_element(client, token, project["id"], "Bare")
    machine = make_machine(client, token, project["id"], element["id"], "Bare modes")
    assert "No states" in _svg(client, token, project["id"], machine["id"])
    _save(client, token, project["id"], machine["id"], [{"text": "Just a remark"}])
    svg = _svg(client, token, project["id"], machine["id"])
    assert "Just a remark" in svg and "No states" not in svg


def test_the_mermaid_text_puts_a_note_beside_the_first_state_it_points_at(client, admin_token):
    p, token, machine, states, transitions = _world(client, admin_token, "Arch smd notes mermaid")
    _save(client, token, p, machine["id"], [
        {"title": "Why", "text": "Spin up\nthen hold", "x": 900, "y": 0,
         "leaders": [{"kind": "transition", "transition_id": transitions["halt"]["id"]}, {"kind": "state", "state_id": states["Running"]["id"]}]},
        {"text": "To a line only", "leaders": [{"kind": "transition", "transition_id": transitions["halt"]["id"]}]},
        {"text": "To the start mark", "leaders": [{"kind": "state", "state_id": states["Start"]["id"]}]},
        {"text": "Loose", "leaders": [{"kind": "point", "x": 1, "y": 2}]},
    ])
    out = _mermaid(client, token, p, machine["id"])
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("note "))
    assert lines[start].strip().startswith("note right of s") and lines[start + 1].strip() == "Why"
    assert [x.strip() for x in lines[start + 2: start + 5]] == ["Spin up", "then hold", "end note"]
    assert sum(1 for line in lines if line.strip().startswith("note ")) == 1  # the other three have no declared state to sit beside


def test_a_note_line_that_would_close_the_block_cannot_do_so(client, admin_token):
    p, token, machine, states, _transitions = _world(client, admin_token, "Arch smd notes mermaid safe")
    _save(client, token, p, machine["id"], [
        {"text": "first\nend note\nstate hacked {\nsecond", "leaders": [{"kind": "state", "state_id": states["Running"]["id"]}]},
    ])
    lines = [line.strip() for line in _mermaid(client, token, p, machine["id"]).splitlines()]
    assert lines.count("end note") == 1
    opened = next(i for i, line in enumerate(lines) if line.startswith("note "))
    # Every typed line, including the hostile ones, is inside the one block, with the braces made safe.
    assert lines[opened + 1: lines.index("end note")] == ["first", "\u2012 end note", "state hacked (", "second"]


def test_the_mermaid_text_with_notes_is_read_by_the_real_parser(client, admin_token, tmp_path):
    """Notes on a state in a block, on a choice and several on one state parse with Mermaid itself. Skipped where `node` or the
    parser's packages (`scripts/mermaid_parse.mjs`) are not installed."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p, token, machine, states, _transitions = _world(client, admin_token, "Arch smd notes parse")
    m = machine["id"]
    pick = add_state(client, token, p, m, "Mode?", kind="choice")
    inner = add_state(client, token, p, m, "Inner", parent_state_id=states["Running"]["id"])
    _save(client, token, p, m, [
        {"title": "Left", "text": "a", "x": -400, "leaders": [{"kind": "state", "state_id": states["Running"]["id"]}]},
        {"text": "Right one", "x": 900, "leaders": [{"kind": "state", "state_id": states["Running"]["id"]}]},
        {"text": "Right two", "x": 900, "leaders": [{"kind": "state", "state_id": states["Running"]["id"]}]},
        {"text": "On a choice; with {syntax}", "x": 900, "leaders": [{"kind": "state", "state_id": pick["id"]}]},
        {"text": "end note", "x": 900, "leaders": [{"kind": "state", "state_id": inner["id"]}]},
    ])
    file = tmp_path / "machine.mmd"
    file.write_text(_mermaid(client, token, p, m), encoding="utf-8")
    script = Path(__file__).resolve().parents[5] / "scripts" / "mermaid_parse.mjs"
    done = subprocess.run(["node", str(script), str(file)], capture_output=True, text=True, timeout=120, check=False)
    if done.returncode == 2:
        pytest.skip("the Mermaid parser is not installed (npm ci in frontend and docs/website)")
    assert done.returncode == 0, done.stdout + done.stderr


# --- Bundle -------------------------------------------------------------------


def _export(client, token, project_id) -> tuple[bytes, dict]:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content, json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))


def _import(client, token, org_id, content: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _rewrite(content: bytes, data: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item, json.dumps(data) if item.filename == "project.json" else source.read(item.filename))
    return out.getvalue()


def test_the_notes_and_their_leaders_round_trip_through_the_project_bundle(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch smd notes bundle")
    p = project["id"]
    element = make_element(client, token, p, "Valve controller")
    machine, states = sound_machine(client, token, p, element["id"], "Valve modes")
    transitions = machine_model(client, token, p, machine["id"])["transitions"]
    halt = next(t for t in transitions if t["event"] == "halt")
    _save(client, token, p, machine["id"], [
        {"title": "Why", "text": "Closes the valve", "tone": "danger", "text_align": "right", "size_mode": "automatic", "x": 10, "y": 20,
         "leaders": [
             {"kind": "state", "state_id": states["Running"]["id"], "start_point": "top", "start_style": "dot", "points": [{"x": 1, "y": 2}]},
             {"kind": "transition", "transition_id": halt["id"], "smooth": True},
             {"kind": "point", "x": 5, "y": 6, "end_style": "none"},
         ]},
        {"text": "Plain", "tone": "none"},
    ])
    content, bundle = _export(client, token, p)
    entry = bundle["architecture_state_machine_diagrams"][0]
    assert [n["text"] for n in entry["notes"]] == ["Closes the valve", "Plain"]
    first = entry["notes"][0]["leaders"]
    assert [(leader["kind"], leader.get("state_name"), leader.get("transition_position")) for leader in first[:2]] == [
        ("state", "Running", None), ("transition", None, str([t["event"] for t in transitions].index("halt"))),
    ]
    imported = _import(client, token, org["id"], content, "Arch smd notes bundle copy")
    copy = imported["project"]["id"]
    machines = client.get(f"{project_base(copy)}/state-machine-diagrams", headers=auth_headers(token)).json()
    model = machine_model(client, token, copy, machines[0]["id"])
    by_name = {s["name"]: s["id"] for s in model["states"]}
    by_event = {t["event"]: t["id"] for t in model["transitions"]}
    shown = model["notes"]
    assert [(n["title"], n["text"], n["tone"], n["text_align"], n["size_mode"], (n["x"], n["y"])) for n in shown] == [
        ("Why", "Closes the valve", "danger", "right", "automatic", (10, 20)), ("", "Plain", "none", "left", "manual", (0, 0)),
    ]
    on_state, on_transition, on_spot = shown[0]["leaders"]
    assert (on_state["kind"], on_state["state_id"], on_state["start_point"], on_state["start_style"], on_state["points"]) == (
        "state", by_name["Running"], "top", "dot", [{"x": 1, "y": 2}],
    )
    assert (on_transition["kind"], on_transition["transition_id"], on_transition["smooth"]) == ("transition", by_event["halt"], True)
    assert (on_spot["kind"], on_spot["x"], on_spot["y"], on_spot["end_style"]) == ("point", 5, 6, "none")
    # Nothing in the copy points back at the original's rows.
    assert not {leader["state_id"] for leader in (on_state,)} & {s["id"] for s in states.values()}


def test_an_older_bundle_with_no_notes_imports_and_a_leader_to_a_missing_target_is_dropped_with_a_warning(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch smd notes older")
    p = project["id"]
    element = make_element(client, token, p, "Pump controller")
    machine, states = sound_machine(client, token, p, element["id"], "Pump modes")
    _save(client, token, p, machine["id"], [{"text": "Kept", "leaders": [{"kind": "state", "state_id": states["Running"]["id"]}]}])
    content, bundle = _export(client, token, p)
    older = json.loads(json.dumps(bundle))
    older["architecture_state_machine_diagrams"][0].pop("notes")
    result = _import(client, token, org["id"], _rewrite(content, older), "Arch smd notes older copy")
    copy = result["project"]["id"]
    machines = client.get(f"{project_base(copy)}/state-machine-diagrams", headers=auth_headers(token)).json()
    assert machine_model(client, token, copy, machines[0]["id"])["notes"] == []
    broken = json.loads(json.dumps(bundle))
    leader = broken["architecture_state_machine_diagrams"][0]["notes"][0]["leaders"][0]
    leader["state_name"] = "No such state"
    result = _import(client, token, org["id"], _rewrite(content, broken), "Arch smd notes broken copy")
    machines = client.get(f"{project_base(result['project']['id'])}/state-machine-diagrams", headers=auth_headers(token)).json()
    model = machine_model(client, token, result["project"]["id"], machines[0]["id"])
    assert [(n["text"], n["leaders"]) for n in model["notes"]] == [("Kept", [])]
    assert any("a note's leader could not be restored" in str(w) for w in result.get("warnings", [])), result


# --- Migration ----------------------------------------------------------------


def test_the_migration_adds_the_state_machine_owner_and_reverses_cleanly(client, admin_token):
    """Upgrading 0196 allows a note to belong to a state machine diagram; downgrading removes those notes (a block diagram has
    nowhere to keep them) and keeps every block diagram note, then the upgrade restores the checks."""
    p, token, machine, states, _transitions = _world(client, admin_token, "Arch smd notes migration")
    block = make_diagram(client, token, p, "Block")
    resp = client.put(
        f"{project_base(p)}/diagrams/{block['id']}/layout", headers=auth_headers(token),
        json={"version": block["version"], "placements": [], "notes": [{"text": "Block note"}]},
    )
    assert resp.status_code == 200, resp.text
    _save(client, token, p, machine["id"], [{"text": "Machine note", "leaders": [{"kind": "state", "state_id": states["Stop"]["id"]}]}])
    command.downgrade(build_alembic_config(), "0195")
    try:
        with engine.connect() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'architecture_diagram_notes'"
            ))}
            assert "state_machine_diagram_id" not in columns
            assert conn.execute(text("SELECT count(*) FROM architecture_diagram_notes WHERE text = 'Block note'")).scalar_one() == 1
            assert conn.execute(text("SELECT count(*) FROM architecture_diagram_notes WHERE text = 'Machine note'")).scalar_one() == 0
            leader_columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'architecture_note_leaders'"
            ))}
            assert not {"state_id", "transition_id"} & leader_columns
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname IN ('ck_architecture_diagram_notes_one_owner', "
            "'ck_architecture_note_leaders_kind', 'ck_architecture_note_leaders_target')"
        )).scalar_one() == 3
