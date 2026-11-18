"""Tests for waypoints on state machine transitions: the vertices and curve a person gives a line.

Covers creating and editing a transition with a route, the layout save (stored, kept when left out, cleared, refused when
invalid), the server SVG drawing a routed transition as a path, the project bundle round trip with cleaning, and the
migration. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import re
import zipfile

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.tests._helpers import (
    add_state,
    add_transition,
    machine_model,
    machine_version,
    make_element,
    project_base,
    setup,
    sound_machine,
)
from tests.conftest import auth_headers, build_alembic_config

VERTICES = [{"x": 120.0, "y": 200.0}, {"x": 260.5, "y": 210.0}]


def _transition(client, token, project_id, machine_id, index=0) -> dict:
    return machine_model(client, token, project_id, machine_id)["transitions"][index]


def _layout(client, token, project_id, machine_id, transitions, *, expect=200):
    body = {"version": machine_version(client, token, project_id, machine_id), "states": [], "transitions": transitions}
    resp = client.put(f"{project_base(project_id)}/state-machine-diagrams/{machine_id}/layout", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def test_a_transition_is_created_with_a_route_and_edited_field_by_field(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch route create")
    element = make_element(client, token, project["id"], "Printer")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    p = project["id"]
    made = add_transition(client, token, p, machine["id"], states["Running"]["id"], states["Running"]["id"], points=VERTICES, line_shape="spline")
    assert made["points"] == VERTICES and made["line_shape"] == "spline"
    plain = add_transition(client, token, p, machine["id"], states["Start"]["id"], states["Stop"]["id"])
    assert plain["points"] == [] and plain["line_shape"] is None
    url = f"{project_base(p)}/state-machine-diagrams/{machine['id']}/transitions/{plain['id']}"
    version = machine_version(client, token, p, machine["id"])
    edited = client.put(url, json={"version": version, "points": VERTICES}, headers=auth_headers(token))
    assert edited.status_code == 200 and edited.json()["points"] == VERTICES and edited.json()["line_shape"] is None
    smoothed = client.put(url, json={"version": version + 1, "line_shape": "spline"}, headers=auth_headers(token))
    assert smoothed.json()["points"] == VERTICES and smoothed.json()["line_shape"] == "spline"  # a field left out is kept
    unchanged = client.put(url, json={"version": version + 2, "points": VERTICES, "line_shape": "spline"}, headers=auth_headers(token))
    assert unchanged.status_code == 200 and machine_version(client, token, p, machine["id"]) == version + 2
    cleared = client.put(url, json={"version": version + 2, "points": []}, headers=auth_headers(token))
    assert cleared.json()["points"] == []
    refused = client.put(url, json={"version": version + 3, "points": [{"x": 1e9, "y": 0}]}, headers=auth_headers(token))
    assert refused.status_code == 422


def test_the_layout_save_stores_keeps_and_clears_a_route_and_refuses_an_invalid_one(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch route layout")
    element = make_element(client, token, project["id"], "Printer")
    machine, _states = sound_machine(client, token, project["id"], element["id"])
    p = project["id"]
    first = _transition(client, token, p, machine["id"])["id"]
    saved = _layout(client, token, p, machine["id"], [{"id": first, "points": VERTICES, "line_shape": "spline"}])
    stored = _transition(client, token, p, machine["id"])
    assert stored["points"] == VERTICES and stored["line_shape"] == "spline"
    # Points and line shape left out keep the route; only the attach points are replaced.
    _layout(client, token, p, machine["id"], [{"id": first, "source_point": "top"}])
    kept = _transition(client, token, p, machine["id"])
    assert kept["points"] == VERTICES and kept["line_shape"] == "spline" and kept["source_point"] == "top"
    same = _layout(client, token, p, machine["id"], [{"id": first, "source_point": "top", "points": VERTICES, "line_shape": "spline"}])
    assert same["version"] == saved["version"] + 1  # the second save advanced it; the identical third did not
    _layout(client, token, p, machine["id"], [{"id": first, "source_point": "top", "points": []}])
    assert _transition(client, token, p, machine["id"])["points"] == []
    _layout(client, token, p, machine["id"], [{"id": first, "points": [{"x": i, "y": i} for i in range(17)]}], expect=422)
    _layout(client, token, p, machine["id"], [{"id": first, "points": [{"x": "NaN", "y": 0}]}], expect=422)


def test_the_svg_draws_a_routed_transition_as_a_path_and_keeps_its_vertices_in_the_picture(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch route svg")
    element = make_element(client, token, project["id"], "Printer")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    p = project["id"]
    add_state(client, token, p, machine["id"], "Idle")
    first = _transition(client, token, p, machine["id"])["id"]
    _layout(client, token, p, machine["id"], [{"id": first, "points": [{"x": 50, "y": -400}], "line_shape": None}])
    svg = client.get(f"{project_base(p)}/state-machine-diagrams/{machine['id']}/svg", headers=auth_headers(token)).text
    assert re.search(r'<path d="M [\d. -]+ L 50 -400 L [\d. -]+" fill="none"', svg), svg
    top = re.search(r'viewBox="[\d.-]+ (-?[\d.]+) ', svg)
    assert top is not None and float(top.group(1)) < -400
    _layout(client, token, p, machine["id"], [{"id": first, "line_shape": "spline"}])
    svg = client.get(f"{project_base(p)}/state-machine-diagrams/{machine['id']}/svg", headers=auth_headers(token)).text
    assert re.search(r'<path d="M [\d. -]+ C [\d. -]+ C ', svg), svg
    assert states  # the other transitions stay plain lines
    assert len(re.findall(r'<line [^>]*marker-end="url\(#arrow\)"', svg)) == 1


def test_a_route_round_trips_through_the_project_bundle_and_bad_points_are_cleaned(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch route bundle")
    element = make_element(client, token, project["id"], "Printer")
    machine, _states = sound_machine(client, token, project["id"], element["id"])
    p = project["id"]
    first = _transition(client, token, p, machine["id"])["id"]
    _layout(client, token, p, machine["id"], [{"id": first, "points": VERTICES, "line_shape": "spline"}])
    resp = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    assert resp.status_code == 200
    source = zipfile.ZipFile(io.BytesIO(resp.content))
    data = json.loads(source.read("project.json"))
    transitions = data["architecture_state_machine_diagrams"][0]["transitions"]
    assert transitions[0]["points"] == VERTICES and transitions[0]["line_shape"] == "spline"
    assert transitions[1]["points"] == [] and transitions[1]["line_shape"] is None
    transitions[0]["points"] += [{"x": "far", "y": 1}, "nonsense", {"x": 9_999_999, "y": 0}]
    transitions[1]["line_shape"] = "yes"  # only a named shape counts
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item.filename, json.dumps(data) if item.filename == "project.json" else source.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch route bundle copy"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]["id"]
    (machine_copy,) = client.get(f"{project_base(copy)}/state-machine-diagrams", headers=auth_headers(token)).json()
    model = machine_model(client, token, copy, machine_copy["id"])
    assert model["transitions"][0]["points"] == VERTICES and model["transitions"][0]["line_shape"] == "spline"
    assert model["transitions"][1]["points"] == [] and model["transitions"][1]["line_shape"] is None


def test_the_waypoints_migration_adds_the_columns_with_empty_defaults_and_reverses_cleanly(client, admin_token):
    """Downgrading 0189 drops the columns and the anchor rows that held only vertices; upgrading restores empty routes."""
    from app.modules.architecture.tests._helpers import make_connection, make_diagram, place_all

    _org, project, token = setup(client, admin_token, "Arch route migration")
    p = project["id"]
    a = make_element(client, token, p, "Alpha")
    b = make_element(client, token, p, "Bravo")
    make_connection(client, token, p, a["id"], b["id"])
    diagram = place_all(client, token, p, make_diagram(client, token, p, "Flow"), a["id"], b["id"])
    anchors = [
        {"source_element_id": a["id"], "target_element_id": b["id"], "source_point": None, "target_point": None,
         "points": [{"x": 5, "y": 5}], "line_shape": "spline"},
    ]
    saved = client.put(
        f"{project_base(p)}/diagrams/{diagram['id']}/layout", headers=auth_headers(token),
        json={
            "version": diagram["version"], "anchors": anchors,
            "placements": [{"element_id": a["id"], "x": 0, "y": 0}, {"element_id": b["id"], "x": 400, "y": 0}],
        },
    )
    assert saved.status_code == 200, saved.text
    command.downgrade(build_alembic_config(), "0188")
    try:
        with engine.connect() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name IN ('architecture_diagram_anchors', 'architecture_transitions')"
            ))}
            assert "points" not in columns and "smooth" not in columns and "line_shape" not in columns
            assert conn.execute(text("SELECT count(*) FROM architecture_diagram_anchors")).scalar_one() == 0  # held only a vertex
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.connect() as conn:
        shaped = text("SELECT count(*) FROM architecture_transitions WHERE points <> '[]'::jsonb OR line_shape IS NOT NULL")
        assert conn.execute(shaped).scalar_one() == 0
