"""Tests for the line hops setting of a diagram: stored on the block diagram and on the state machine diagram, edited with the
version lock and audited, drawn by the server SVG as an arc where one line crosses another (and not drawn with the setting
off), carried by the project bundle and by the migration. The geometry rule itself is tested in
`test_architecture_line_hops.py`. Every test builds its own organisation."""

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
    make_connection,
    make_diagram,
    make_element,
    make_machine,
    project_base,
    setup,
    view,
)
from tests.conftest import auth_headers, build_alembic_config


def _crossing_diagram(client, token, project_id, **fields):
    """A block diagram with a long horizontal line (Alpha to Bravo) and a long vertical one (Charlie to Delta) across it."""
    names = ["Alpha", "Bravo", "Charlie", "Delta"]
    a, b, c, d = (make_element(client, token, project_id, name) for name in names)
    make_connection(client, token, project_id, a["id"], b["id"])
    make_connection(client, token, project_id, c["id"], d["id"])
    diagram = make_diagram(client, token, project_id, "Crossing", **fields)
    layout = [
        {"element_id": a["id"], "x": 0, "y": 300}, {"element_id": b["id"], "x": 700, "y": 300},
        {"element_id": c["id"], "x": 350, "y": 0}, {"element_id": d["id"], "x": 350, "y": 600},
    ]
    resp = client.put(
        f"{project_base(project_id)}/diagrams/{diagram['id']}/layout",
        json={"version": diagram["version"], "placements": layout, "notes": []}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _svg(client, token, project_id, diagram_id) -> str:
    resp = client.get(f"{project_base(project_id)}/diagrams/{diagram_id}/svg", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.text


def test_a_diagram_has_line_hops_off_and_the_setting_is_edited_with_the_version_lock_and_audited(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch hops setting")
    p = project["id"]
    diagram = make_diagram(client, token, p, "Plain")
    assert diagram["line_hops"] is False
    url = f"{project_base(p)}/diagrams/{diagram['id']}"
    on = client.put(url, json={"version": diagram["version"], "line_hops": True}, headers=auth_headers(token))
    assert on.status_code == 200 and on.json()["line_hops"] is True and on.json()["version"] == diagram["version"] + 1
    same = client.put(url, json={"version": diagram["version"] + 1, "line_hops": True}, headers=auth_headers(token))
    assert same.status_code == 200 and same.json()["version"] == diagram["version"] + 1  # no change, no new version
    other = client.put(url, json={"version": diagram["version"] + 1, "name": "Renamed"}, headers=auth_headers(token))
    assert other.json()["line_hops"] is True  # a field left out is kept
    stale = client.put(url, json={"version": diagram["version"], "line_hops": False}, headers=auth_headers(token))
    assert stale.status_code == 409
    created = make_diagram(client, token, p, "Born with hops", line_hops=True)
    assert created["line_hops"] is True


def test_the_svg_draws_an_arc_where_two_lines_cross_only_with_the_setting_on(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch hops svg")
    p = project["id"]
    diagram = _crossing_diagram(client, token, p)
    off = _svg(client, token, p, diagram["id"])
    assert " A " not in off and off.count("<line ") == 2
    version = diagram["version"]
    client.put(f"{project_base(p)}/diagrams/{diagram['id']}", json={"version": version, "line_hops": True}, headers=auth_headers(token))
    on = _svg(client, token, p, diagram["id"])
    arcs = re.findall(r'<path d="(M [^"]* A 6 6 0 0 [01] [^"]*)" fill="none"', on)
    assert len(arcs) == 1 and on.count("<line ") == 1  # one of the two lines hops; the other stays a plain line
    assert on == _svg(client, token, p, diagram["id"])  # deterministic


def test_every_crossing_of_a_leader_and_a_connection_is_drawn_once(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch hops leader")
    p = project["id"]
    diagram = _crossing_diagram(client, token, p, line_hops=True)
    note = {"text": "Far", "tone": "info", "x": 0, "y": 0, "width": 120, "height": 40,
            "leaders": [{"kind": "point", "x": 700, "y": 900, "start_point": "bottom"}]}
    placements = [{"element_id": b["element_id"], "x": b["x"], "y": b["y"]} for b in view(client, token, p, diagram["id"])["nodes"]]
    resp = client.put(
        f"{project_base(p)}/diagrams/{diagram['id']}/layout",
        json={"version": diagram["version"], "placements": placements, "notes": [note]}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    # Each crossing is drawn once, by whichever of its two lines has the later id: the two connections cross once, and the
    # leader crosses each of them once.
    assert _svg(client, token, p, diagram["id"]).count(" A 6 6 ") == 3


def _machine_with_crossing_transitions(client, token, project_id):
    element = make_element(client, token, project_id, "Printer")
    machine = make_machine(client, token, project_id, element["id"], "Modes")
    base = f"{project_base(project_id)}/state-machine-diagrams/{machine['id']}"
    names = {"A": (0, 300), "B": (700, 300), "C": (350, 0), "D": (350, 600)}
    states = {name: add_state(client, token, project_id, machine["id"], name, x=x, y=y) for name, (x, y) in names.items()}
    add_transition(client, token, project_id, machine["id"], states["A"]["id"], states["B"]["id"], event="across")
    add_transition(client, token, project_id, machine["id"], states["C"]["id"], states["D"]["id"], event="down")
    return machine, base


def test_a_state_machine_diagram_stores_the_setting_and_its_svg_hops(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch hops machine")
    p = project["id"]
    machine, base = _machine_with_crossing_transitions(client, token, p)
    assert machine["line_hops"] is False
    off = client.get(f"{base}/svg", headers=auth_headers(token)).text
    assert " A 6 6 " not in off
    on = client.put(
        base, json={"version": machine_version(client, token, p, machine["id"]), "line_hops": True}, headers=auth_headers(token),
    )
    assert on.status_code == 200 and on.json()["line_hops"] is True
    svg = client.get(f"{base}/svg", headers=auth_headers(token)).text
    assert svg.count(" A 6 6 ") == 1
    assert machine_model(client, token, p, machine["id"])["diagram"]["line_hops"] is True


def test_the_setting_round_trips_through_the_project_bundle_for_both_diagram_types(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch hops bundle")
    p = project["id"]
    _crossing_diagram(client, token, p, line_hops=True)
    machine, base = _machine_with_crossing_transitions(client, token, p)
    client.put(base, json={"version": machine_version(client, token, p, machine["id"]), "line_hops": True}, headers=auth_headers(token))
    resp = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    data = json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))
    assert data["architecture_diagrams"][0]["line_hops"] is True and data["architecture_state_machine_diagrams"][0]["line_hops"] is True
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch hops bundle copy"},
        files={"file": ("bundle.zip", resp.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]["id"]
    (diagram,) = client.get(f"{project_base(copy)}/diagrams", headers=auth_headers(token)).json()
    (machine_copy,) = client.get(f"{project_base(copy)}/state-machine-diagrams", headers=auth_headers(token)).json()
    assert diagram["line_hops"] is True and machine_copy["line_hops"] is True


def test_an_older_bundle_with_no_setting_imports_with_hops_off(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch hops old bundle")
    p = project["id"]
    _crossing_diagram(client, token, p, line_hops=True)
    resp = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    source = zipfile.ZipFile(io.BytesIO(resp.content))
    data = json.loads(source.read("project.json"))
    for entry in data["architecture_diagrams"]:
        entry.pop("line_hops")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item, json.dumps(data) if item.filename == "project.json" else source.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch hops old copy"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    (diagram,) = client.get(f"{project_base(imported.json()['project']['id'])}/diagrams", headers=auth_headers(token)).json()
    assert diagram["line_hops"] is False


def test_the_migration_adds_the_column_off_for_existing_diagrams_and_reverses_cleanly(client, admin_token):
    config = build_alembic_config()
    try:
        command.downgrade(config, "0190")
        with engine.connect() as connection:
            columns = {
                row[0] for row in connection.execute(text(
                    "SELECT table_name FROM information_schema.columns WHERE column_name = 'line_hops'"
                ))
            }
        assert columns == set()
        command.upgrade(config, "0191")
        with engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT table_name, is_nullable, column_default FROM information_schema.columns WHERE column_name = 'line_hops' "
                "ORDER BY table_name"
            )).all()
        assert [r[0] for r in rows] == ["architecture_diagrams", "architecture_state_machine_diagrams"]
        assert all(r[1] == "NO" and "false" in str(r[2]) for r in rows)
    finally:
        command.upgrade(config, "head")
