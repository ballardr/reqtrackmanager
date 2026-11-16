"""Tests for the label position of an initial, final or choice state (`inside`, `left`, `right`, `above` or `below`): it is
stored on create and edit with `inside` as the default, only a marker may place its label outside the symbol, changing a state
to an ordinary one resets it, it is listed and exported as a column, carried by the project bundle (an unknown value or a value
on an ordinary state is tidied on import), drawn by the SVG with the symbol at its stored box and the text beside it, kept out of
the way of lines (the side the label is on is not offered to an open line end), and the migration adds and drops the column.
Every test builds its own organisation."""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest
from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.diagram_points import SIDE_POINTS
from app.modules.architecture.diagram_symbol_label import LABEL_PADDING, beside_label
from app.modules.architecture.enums import AttachPoint, LabelPosition, StateKind
from app.modules.architecture.state_shapes import marker_attach_points, marker_frame
from app.modules.architecture.tests._helpers import (
    add_state,
    machine_model,
    machine_version,
    make_element,
    make_machine,
    project_base,
    setup,
    sound_machine,
)
from tests.conftest import auth_headers, build_alembic_config

STATE = "architecture_state"
SVG = "{http://www.w3.org/2000/svg}"


def _update(client, token, project_id, machine_id, state_id, **fields):
    return client.put(
        f"{project_base(project_id)}/states/{state_id}",
        json={"version": machine_version(client, token, project_id, machine_id), **fields}, headers=auth_headers(token),
    )


def test_a_marker_takes_a_label_position_on_create_and_edit_and_inside_is_the_default(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch position crud")
    element = make_element(client, token, project["id"], "Pump")
    machine = make_machine(client, token, project["id"], element["id"])
    plain = add_state(client, token, project["id"], machine["id"], "Start", kind="initial", label="Go")
    assert plain["label_position"] == "inside"
    right = add_state(client, token, project["id"], machine["id"], "Level", kind="choice", label="Tank full?", label_position="right")
    assert right["label_position"] == "right"
    edited = _update(client, token, project["id"], machine["id"], plain["id"], label_position="above")
    assert edited.status_code == 200 and edited.json()["label_position"] == "above"
    back = _update(client, token, project["id"], machine["id"], plain["id"], label_position="inside")
    assert back.json()["label_position"] == "inside"
    assert {s["name"]: s["label_position"] for s in machine_model(client, token, project["id"], machine["id"])["states"]} == {
        "Start": "inside", "Level": "right",
    }


def test_an_unknown_position_is_refused_and_an_ordinary_state_cannot_place_a_label(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch position rules")
    element = make_element(client, token, project["id"], "Valve")
    machine = make_machine(client, token, project["id"], element["id"])
    add_state(client, token, project["id"], machine["id"], "Odd", kind="choice", label_position="diagonal", expect=422)
    add_state(client, token, project["id"], machine["id"], "Ordinary", kind="state", label_position="left", expect=400)
    ordinary = add_state(client, token, project["id"], machine["id"], "Open", kind="state", label_position="inside")
    refused = _update(client, token, project["id"], machine["id"], ordinary["id"], label_position="below")
    assert refused.status_code == 400 and "place its symbol label" in refused.json()["detail"]
    assert _update(client, token, project["id"], machine["id"], ordinary["id"], label_position="diagonal").status_code == 422


def test_changing_a_marker_to_an_ordinary_state_resets_its_position(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch position kind")
    element = make_element(client, token, project["id"], "Door")
    machine = make_machine(client, token, project["id"], element["id"])
    choice = add_state(client, token, project["id"], machine["id"], "Check", kind="choice", label="Locked?", label_position="left")
    changed = _update(client, token, project["id"], machine["id"], choice["id"], kind="state")
    assert changed.status_code == 200, changed.text
    assert changed.json()["label_position"] == "inside" and changed.json()["label"] == ""
    assert _update(client, token, project["id"], machine["id"], choice["id"], kind="state", label_position="right").status_code == 400


def test_the_position_is_a_listed_and_exported_column_named_by_its_display_label(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch position tables")
    element = make_element(client, token, project["id"], "Engine")
    machine = make_machine(client, token, project["id"], element["id"])
    add_state(client, token, project["id"], machine["id"], "Gate", kind="choice", label="Oil hot?", label_position="below")
    listed = client.get(f"{project_base(project['id'])}/states", headers=auth_headers(token)).json()
    assert [(s["name"], s["label_position"]) for s in listed] == [("Gate", "below")]
    exported = client.get(f"/api/v1/projects/{project['id']}/records/{STATE}/export", headers=auth_headers(token))
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["label_position"] == "Below"


def test_the_position_round_trips_in_the_project_bundle_and_an_unknown_or_misplaced_value_becomes_inside(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch position bundle")
    element = make_element(client, token, project["id"], "Fan")
    machine, _states = sound_machine(client, token, project["id"], element["id"], "Speeds")
    add_state(client, token, project["id"], machine["id"], "Branch", kind="choice", label="Too fast?", label_position="right")
    add_state(client, token, project["id"], machine["id"], "Begin", kind="initial", label="Go", label_position="above")
    resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    bundle = json.loads(archive.read("project.json"))
    states = bundle["architecture_state_machine_diagrams"][0]["states"]
    assert {s["name"]: s["label_position"] for s in states}["Branch"] == "right"
    for s in states:  # a file from elsewhere: an unknown value on a marker, a position on an ordinary state, and an older file with none
        if s["name"] == "Branch":
            s["label_position"] = "diagonal"
        if s["name"] == "Running":
            s["label_position"] = "left"
        if s["name"] == "Begin":
            del s["label_position"]
    rebuilt = io.BytesIO()
    with zipfile.ZipFile(rebuilt, "w") as out:
        for item in archive.infolist():
            out.writestr(item, json.dumps(bundle) if item.filename == "project.json" else archive.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch position bundle copy"},
        files={"file": ("bundle.zip", rebuilt.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    copies = client.get(f"{project_base(new_id)}/state-machine-diagrams", headers=auth_headers(token)).json()
    positions = {s["name"]: s["label_position"] for s in machine_model(client, token, new_id, copies[0]["id"])["states"]}
    assert positions["Branch"] == "inside" and positions["Running"] == "inside" and positions["Begin"] == "inside"


def test_a_good_position_survives_the_bundle_round_trip(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch position kept")
    element = make_element(client, token, project["id"], "Heater")
    machine = make_machine(client, token, project["id"], element["id"])
    add_state(client, token, project["id"], machine["id"], "Hot?", kind="choice", label="Too hot?", label_position="left")
    resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch position kept copy"},
        files={"file": ("bundle.zip", resp.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    copies = client.get(f"{project_base(new_id)}/state-machine-diagrams", headers=auth_headers(token)).json()
    states = machine_model(client, token, new_id, copies[0]["id"])["states"]
    assert [(s["name"], s["label_position"]) for s in states] == [("Hot?", "left")]


@pytest.mark.parametrize("position", ["left", "right", "above", "below"])
def test_the_svg_draws_the_symbol_at_its_stored_box_with_the_text_beside_it(client, admin_token, position):
    _org, project, token = setup(client, admin_token, f"Arch position svg {position}")
    element = make_element(client, token, project["id"], "Lamp")
    machine = make_machine(client, token, project["id"], element["id"])
    add_state(
        client, token, project["id"], machine["id"], "Gate", kind="choice", x=100, y=100, width=36, height=36,
        label="Power ok?", label_position=position,
    )
    svg = client.get(
        f"{project_base(project['id'])}/state-machine-diagrams/{machine['id']}/svg", headers=auth_headers(token),
    ).text
    ET.fromstring(svg)
    # The symbol is drawn at its plain notation size on the stored box, not enlarged to hold the text.
    assert "translate(100.0 100.0) scale(1.0000 1.0000)" in svg
    layout = beside_label("Power ok?", LabelPosition(position), 36, 36)
    assert layout is not None
    texts = [t for t in ET.fromstring(svg).iter(f"{SVG}text") if t.text in layout.lines]
    assert [t.text for t in texts] == layout.lines
    anchor = {"left": "start", "center": "middle", "right": "end"}[layout.align]
    assert {t.get("text-anchor") for t in texts} == {anchor}
    first = texts[0]
    reach = {"start": 0, "middle": layout.width / 2, "end": layout.width}[anchor]
    assert float(first.get("x", "0")) == pytest.approx(100 + layout.x + reach, abs=0.1)
    assert first.get("fill") != "#FFFFFF"  # outside the symbol the text sits on the page, not on a fill
    # The drawing's extent includes the text, so none of it is cut off.
    view = [float(v) for v in ET.fromstring(svg).get("viewBox", "").split()]
    left, top = 100 + min(0, layout.x), 100 + min(0, layout.y)
    right, bottom = 100 + max(36, layout.x + layout.width), 100 + max(36, layout.y + layout.height)
    assert view[0] <= left and view[1] <= top and view[0] + view[2] >= right and view[1] + view[3] >= bottom


def test_a_line_to_a_marker_does_not_end_on_the_side_its_label_is_on(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch position lines")
    element = make_element(client, token, project["id"], "Gate")
    machine = make_machine(client, token, project["id"], element["id"])
    from app.modules.architecture.tests._helpers import add_transition

    start = add_state(client, token, project["id"], machine["id"], "Begin", kind="initial", x=0, y=0, width=20, height=20)
    ask = add_state(
        client, token, project["id"], machine["id"], "Ask", kind="choice", x=200, y=0, width=36, height=36, label="Open?",
        label_position="left",
    )
    add_transition(client, token, project["id"], machine["id"], start["id"], ask["id"])
    svg = client.get(
        f"{project_base(project['id'])}/state-machine-diagrams/{machine['id']}/svg", headers=auth_headers(token),
    ).text
    line = next(e for e in ET.fromstring(svg).iter(f"{SVG}line"))
    # The nearest side of the choice would be its left (where the text is); the line ends at its top instead.
    assert (float(line.get("x2", "0")), float(line.get("y2", "0"))) == (218.0, 0.0)


def test_the_marker_attach_points_leave_out_the_side_of_a_label_outside_the_symbol():
    assert marker_attach_points("Go", LabelPosition.INSIDE) == SIDE_POINTS
    assert marker_attach_points("", LabelPosition.LEFT) == SIDE_POINTS and marker_attach_points("  ", LabelPosition.RIGHT) == SIDE_POINTS
    assert marker_attach_points("Go", LabelPosition.LEFT) == (AttachPoint.TOP, AttachPoint.RIGHT, AttachPoint.BOTTOM)
    assert marker_attach_points("Go", LabelPosition.RIGHT) == (AttachPoint.TOP, AttachPoint.BOTTOM, AttachPoint.LEFT)
    assert marker_attach_points("Go", LabelPosition.ABOVE) == (AttachPoint.RIGHT, AttachPoint.BOTTOM, AttachPoint.LEFT)
    assert marker_attach_points("Go", LabelPosition.BELOW) == (AttachPoint.TOP, AttachPoint.RIGHT, AttachPoint.LEFT)


def test_a_label_outside_leaves_the_frame_as_stored_and_inside_grows_it():
    box = (100.0, 50.0, 36.0, 36.0)
    for position in (LabelPosition.LEFT, LabelPosition.RIGHT, LabelPosition.ABOVE, LabelPosition.BELOW):
        assert marker_frame(StateKind.CHOICE, box, "A long enough label to need more room", position) == box
    assert marker_frame(StateKind.CHOICE, box, "Full?", LabelPosition.INSIDE) != box
    assert LABEL_PADDING == 4


def test_the_position_migration_adds_the_column_with_an_inside_default_and_reverses_cleanly(client, admin_token):
    """Downgrading 0193 drops `label_position`; upgrading restores it as `inside` for every existing state."""
    _org, project, token = setup(client, admin_token, "Arch position migration")
    element = make_element(client, token, project["id"], "Kept")
    machine = make_machine(client, token, project["id"], element["id"])
    state = add_state(client, token, project["id"], machine["id"], "Gate", kind="choice", label="Kept", label_position="right")
    command.downgrade(build_alembic_config(), "0192")
    try:
        with engine.connect() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'architecture_states'"
            ))}
            assert "label_position" not in columns
            assert conn.execute(text("SELECT count(*) FROM architecture_states WHERE id = :i"), {"i": state["id"]}).scalar_one() == 1
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.connect() as conn:
        value = conn.execute(text("SELECT label_position FROM architecture_states WHERE id = :i"), {"i": state["id"]}).scalar_one()
        assert value == "inside"
        refused = conn.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'ck_architecture_states_label_position'"
        )).scalar_one()
        assert refused == 1
