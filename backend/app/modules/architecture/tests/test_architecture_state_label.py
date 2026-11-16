"""Tests for the symbol label of an initial, final or choice state (up to 256 characters): it is stored on create and edit
and cleared with an empty value, only a marker may carry one (an ordinary state's name is drawn in its box), changing a state to
an ordinary one clears it, it is searched, listed and exported as the `label` column (a state has no import), carried by the
project bundle (cut to the limit when a file from elsewhere is longer), drawn inside a symbol that grows to hold it by the SVG,
and the migrations add, widen and drop the column. Every test builds its own organisation."""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
import zipfile

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.enums import StateKind
from app.modules.architecture.diagram_symbol_label import BASE_SIZE, fit_label
from app.modules.architecture.enums import SYMBOL_LABEL_LENGTH
from app.modules.architecture.state_shapes import (
    LABEL_ON_FILL,
    STATE_MARKERS,
    labelled_svg,
    marker_frame,
)
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


def test_a_marker_takes_a_label_on_create_and_edit_and_an_empty_value_clears_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch label crud")
    element = make_element(client, token, project["id"], "Pump")
    machine = make_machine(client, token, project["id"], element["id"])
    choice = add_state(client, token, project["id"], machine["id"], "Level", kind="choice", label="  Tank full?  ")
    assert choice["label"] == "Tank full?"
    plain = add_state(client, token, project["id"], machine["id"], "Start", kind="initial")
    assert plain["label"] == ""
    edited = _update(client, token, project["id"], machine["id"], plain["id"], label="Power on")
    assert edited.status_code == 200 and edited.json()["label"] == "Power on"
    cleared = _update(client, token, project["id"], machine["id"], plain["id"], label="")
    assert cleared.json()["label"] == ""
    assert {s["name"]: s["label"] for s in machine_model(client, token, project["id"], machine["id"])["states"]} == {
        "Level": "Tank full?", "Start": "",
    }


def test_a_label_may_have_up_to_256_characters_the_api_refuses_more_and_an_ordinary_state_refuses_one(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch label rules")
    element = make_element(client, token, project["id"], "Valve")
    machine = make_machine(client, token, project["id"], element["id"])
    assert SYMBOL_LABEL_LENGTH == 256
    add_state(client, token, project["id"], machine["id"], "Too long", kind="choice", label="x" * 257, expect=422)
    exact = add_state(client, token, project["id"], machine["id"], "Exactly", kind="choice", label="word " * 51 + "x")
    assert len(exact["label"]) == 256
    add_state(client, token, project["id"], machine["id"], "Ordinary", kind="state", label="No place", expect=400)
    ordinary = add_state(client, token, project["id"], machine["id"], "Open")
    refused = _update(client, token, project["id"], machine["id"], ordinary["id"], label="No place")
    assert refused.status_code == 400
    assert "symbol label" in refused.json()["detail"]


def test_changing_a_marker_to_an_ordinary_state_clears_its_label(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch label kind")
    element = make_element(client, token, project["id"], "Door")
    machine = make_machine(client, token, project["id"], element["id"])
    choice = add_state(client, token, project["id"], machine["id"], "Check", kind="choice", label="Locked?")
    changed = _update(client, token, project["id"], machine["id"], choice["id"], kind="state")
    assert changed.status_code == 200, changed.text
    assert changed.json()["kind"] == "state" and changed.json()["label"] == ""
    both = _update(client, token, project["id"], machine["id"], choice["id"], kind="final", label="Done")
    assert both.json()["label"] == "Done"
    assert _update(client, token, project["id"], machine["id"], choice["id"], kind="state", label="Kept").status_code == 400


def test_the_label_is_found_by_search_listed_and_exported_as_a_column_that_imports(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch label tables")
    element = make_element(client, token, project["id"], "Engine")
    machine = make_machine(client, token, project["id"], element["id"])
    add_state(client, token, project["id"], machine["id"], "Gate", kind="choice", label="Oil hot?")
    listed = client.get(f"{project_base(project['id'])}/states", params={"search": "oil hot"}, headers=auth_headers(token)).json()
    assert [s["name"] for s in listed] == ["Gate"] and listed[0]["label"] == "Oil hot?"
    found = client.post(
        "/api/v1/search", json={"q": "oil hot", "scope": "project", "project_id": project["id"], "fields": ["label"]},
        headers=auth_headers(token),
    ).json()["hits"]
    assert [(h["type"], h["title"]) for h in found if h["type"] == STATE] == [(STATE, "Gate")]

    tier = f"/api/v1/projects/{project['id']}/records/{STATE}"
    exported = client.get(f"{tier}/export", headers=auth_headers(token))
    assert exported.status_code == 200
    body = exported.content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(body)))
    assert rows[0]["label"] == "Oil hot?"


def test_the_label_round_trips_in_the_project_bundle_and_an_overlong_or_misplaced_label_is_tidied_on_import(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch label bundle")
    element = make_element(client, token, project["id"], "Fan")
    machine, _states = sound_machine(client, token, project["id"], element["id"], "Speeds")
    add_state(client, token, project["id"], machine["id"], "Branch", kind="choice", label="Too fast?")
    resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    bundle = json.loads(archive.read("project.json"))
    states = bundle["architecture_state_machine_diagrams"][0]["states"]
    assert {s["name"]: s["label"] for s in states}["Branch"] == "Too fast?"
    for s in states:  # a file from elsewhere: too long on a marker, and a label on an ordinary state
        if s["name"] == "Branch":
            s["label"] = "y" * 300
        if s["name"] == "Running":
            s["label"] = "Ordinary"
    rebuilt = io.BytesIO()
    with zipfile.ZipFile(rebuilt, "w") as out:
        for item in archive.infolist():
            out.writestr(item, json.dumps(bundle) if item.filename == "project.json" else archive.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch label bundle copy"},
        files={"file": ("bundle.zip", rebuilt.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    copies = client.get(f"{project_base(new_id)}/state-machine-diagrams", headers=auth_headers(token)).json()
    labels = {s["name"]: s["label"] for s in machine_model(client, token, new_id, copies[0]["id"])["states"]}
    assert labels["Branch"] == "y" * 256 and labels["Running"] == ""


def test_the_svg_draws_a_labelled_symbol_larger_with_its_text_inside_and_an_unlabelled_one_as_before(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch label svg")
    element = make_element(client, token, project["id"], "Lamp")
    machine = make_machine(client, token, project["id"], element["id"])
    add_state(client, token, project["id"], machine["id"], "Start", kind="initial", x=0, y=0, width=20, height=20, label="Power on")
    add_state(client, token, project["id"], machine["id"], "End", kind="final", x=200, y=0, width=28, height=28)
    base = project_base(project["id"])
    svg = client.get(f"{base}/state-machine-diagrams/{machine['id']}/svg", headers=auth_headers(token)).text
    ET.fromstring(svg)
    layout = fit_label(StateKind.INITIAL, "Power on")
    assert layout is not None
    size = layout.size
    # The labelled dot is drawn at the size its label needs, centred on the stored 20 x 20 box; the final state is untouched.
    assert f'translate({-(size - 20) / 2:.1f} {-(size - 20) / 2:.1f}) scale(1.0000 1.0000)' in svg
    assert "translate(200.0 0.0) scale(1.0000 1.0000)" in svg
    texts = [t for t in ET.fromstring(svg).iter(f"{SVG}text") if t.get("fill") == LABEL_ON_FILL]
    assert [t.text for t in texts] == layout.lines and " ".join(layout.lines) == "Power on"  # broken between words only


def test_the_marker_frame_grows_a_labelled_symbol_around_its_centre_and_leaves_an_unlabelled_one_alone():
    box = (100.0, 50.0, 36.0, 36.0)
    assert marker_frame(StateKind.CHOICE, box, "") == box and marker_frame(StateKind.CHOICE, box, "   ") == box
    size = BASE_SIZE[StateKind.CHOICE]
    x, y, w, h = marker_frame(StateKind.CHOICE, box, "Full?")
    assert (w, h) == (size, size) and (x + w / 2, y + h / 2) == (118.0, 68.0)
    # A box already larger than the labelled size is kept.
    assert marker_frame(StateKind.INITIAL, (0.0, 0.0, 200.0, 100.0), "x") == (0.0, 0.0, 200.0, 100.0)


def test_a_longer_label_grows_the_frame_and_the_drawing_at_any_size_keeps_its_viewbox_and_stroke():
    box = (100.0, 50.0, 36.0, 36.0)
    long_label = "Is the tank level above the high-level alarm threshold for more than ten seconds"
    layout = fit_label(StateKind.CHOICE, long_label)
    assert layout is not None and layout.size > BASE_SIZE[StateKind.CHOICE]
    x, y, w, h = marker_frame(StateKind.CHOICE, box, long_label)
    assert (w, h) == (layout.size, layout.size) and (x + w / 2, y + h / 2) == (118.0, 68.0)
    for kind, plain in STATE_MARKERS.items():
        for size in (BASE_SIZE[kind], 200):
            svg = labelled_svg(kind, size)
            assert size > plain[0] and f'viewBox="0 0 {size} {size}"' in svg and svg.startswith("<svg") and svg.endswith("</svg>")
            assert "<script" not in svg and "href" not in svg
        if kind is not StateKind.INITIAL:
            assert 'stroke-width="2"' in labelled_svg(kind, 200)


def test_the_label_migration_adds_the_column_with_an_empty_default_and_reverses_cleanly(client, admin_token):
    """Downgrading 0188 drops `label`; upgrading restores it empty for every existing state."""
    _org, project, token = setup(client, admin_token, "Arch label migration")
    element = make_element(client, token, project["id"], "Kept")
    machine = make_machine(client, token, project["id"], element["id"])
    state = add_state(client, token, project["id"], machine["id"], "Gate", kind="choice", label="Dropped with the column.")
    command.downgrade(build_alembic_config(), "0187")
    try:
        with engine.connect() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'architecture_states'"
            ))}
            assert "label" not in columns
            assert conn.execute(text("SELECT count(*) FROM architecture_states WHERE id = :i"), {"i": state["id"]}).scalar_one() == 1
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT label FROM architecture_states WHERE id = :i"), {"i": state["id"]}).scalar_one() == ""


def test_the_widening_migration_keeps_every_label_and_a_downgrade_cuts_a_long_one_to_forty_characters(client, admin_token):
    """Downgrading 0192 narrows `label` to 40 characters (cutting a longer one); upgrading restores 256 and keeps what is left."""
    _org, project, token = setup(client, admin_token, "Arch label width")
    element = make_element(client, token, project["id"], "Wide")
    machine = make_machine(client, token, project["id"], element["id"])
    long_label = "word " * 40 + "end"
    long = add_state(client, token, project["id"], machine["id"], "Long", kind="choice", label=long_label)
    short = add_state(client, token, project["id"], machine["id"], "Short", kind="choice", label="Full?")
    column = "SELECT character_maximum_length FROM information_schema.columns WHERE table_name = 'architecture_states' AND column_name = 'label'"
    with engine.connect() as conn:
        assert conn.execute(text(column)).scalar_one() == 256
    command.downgrade(build_alembic_config(), "0191")
    try:
        with engine.connect() as conn:
            assert conn.execute(text(column)).scalar_one() == 40
            assert conn.execute(text("SELECT label FROM architecture_states WHERE id = :i"), {"i": long["id"]}).scalar_one() == long_label[:40]
            assert conn.execute(text("SELECT label FROM architecture_states WHERE id = :i"), {"i": short["id"]}).scalar_one() == "Full?"
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.connect() as conn:
        assert conn.execute(text(column)).scalar_one() == 256
        assert conn.execute(text("SELECT label FROM architecture_states WHERE id = :i"), {"i": short["id"]}).scalar_one() == "Full?"
