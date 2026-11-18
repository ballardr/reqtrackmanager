"""Tests for the line shape (Straight, Curved or Spline) of a drawn line and its diagram's default.

Covers the diagram default (create, edit, refused values, version), a line's own shape (a shape-only route is stored, null
follows the diagram, an unknown shape is refused) for a block diagram's connections, a state machine's transitions and a
note's leaders, the server SVG drawing each shape, the project bundle round trip (and a bundle written before shapes, which
carried `smooth`), and the migration of the old flag. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import re
import zipfile

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.tests._helpers import (
    add_transition,
    machine_model,
    machine_version,
    make_connection,
    make_diagram,
    make_element,
    place_all,
    project_base,
    setup,
    sound_machine,
    view,
)
from tests.conftest import auth_headers, build_alembic_config


def _pair(client, token, project_id, **diagram_fields):
    """Two connected, placed elements side by side (160 x 80 boxes at x = 0 and 400): `(a, b, connection, diagram)`."""
    a = make_element(client, token, project_id, "Alpha")
    b = make_element(client, token, project_id, "Bravo")
    link = make_connection(client, token, project_id, a["id"], b["id"])
    diagram = place_all(client, token, project_id, make_diagram(client, token, project_id, "Flow", **diagram_fields), a["id"], b["id"])
    return a, b, link, _save(client, token, project_id, diagram, a, b)


def _boxes(a, b):
    return [{"element_id": a["id"], "x": 0, "y": 0}, {"element_id": b["id"], "x": 400, "y": 0}]


def _save(client, token, project_id, diagram, a, b, anchors=None, notes=(), expect=200):
    body = {"version": diagram["version"], "placements": _boxes(a, b), "notes": list(notes)}
    if anchors is not None:
        body["anchors"] = anchors
    resp = client.put(f"{project_base(project_id)}/diagrams/{diagram['id']}/layout", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _svg(client, token, project_id, diagram_id) -> str:
    resp = client.get(f"{project_base(project_id)}/diagrams/{diagram_id}/svg", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.text


def _edit(client, token, project_id, diagram, **fields):
    resp = client.put(
        f"{project_base(project_id)}/diagrams/{diagram['id']}", json={"version": diagram["version"], **fields}, headers=auth_headers(token),
    )
    return resp


# --- The diagram's default -----------------------------------------------------------------------------------------------


def test_a_diagram_default_is_straight_and_is_set_at_creation_and_by_an_edit(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape default")
    p = project["id"]
    plain = make_diagram(client, token, p, "Plain")
    assert plain["line_shape"] == "straight"
    curved = make_diagram(client, token, p, "Curved", line_shape="curved")
    assert curved["line_shape"] == "curved"
    edited = _edit(client, token, p, plain, line_shape="spline")
    assert edited.status_code == 200 and edited.json()["line_shape"] == "spline"
    assert edited.json()["version"] == plain["version"] + 1
    kept = _edit(client, token, p, edited.json(), name="Renamed")
    assert kept.json()["line_shape"] == "spline"  # a field left out is kept
    same = _edit(client, token, p, kept.json(), line_shape="spline")
    assert same.json()["version"] == kept.json()["version"]  # no change, no new version


def test_an_unknown_default_shape_is_refused(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape default bad")
    p = project["id"]
    made = client.post(f"{project_base(p)}/diagrams", json={"name": "Bad", "line_shape": "zigzag"}, headers=auth_headers(token))
    assert made.status_code == 422
    diagram = make_diagram(client, token, p, "Good")
    assert _edit(client, token, p, diagram, line_shape="zigzag").status_code == 422
    assert _edit(client, token, p, diagram, line_shape=None).status_code == 200  # null leaves it alone, it is never unset


def test_the_diagram_list_and_export_name_the_default_shape(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape default list")
    p = project["id"]
    make_diagram(client, token, p, "Curved", line_shape="curved")
    (row,) = client.get(f"{project_base(p)}/diagrams", headers=auth_headers(token)).json()
    assert row["line_shape"] == "curved"
    exported = client.get(f"/api/v1/projects/{p}/records/architecture_diagram/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    header, first = exported.content.decode("utf-8-sig").splitlines()[:2]
    assert "line_shape" in header.split(",") and "Curved" in first.split(",")


# --- A line's own shape ---------------------------------------------------------------------------------------------------


def test_a_route_that_sets_only_a_shape_is_stored_and_null_follows_the_diagram(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape own")
    p = project["id"]
    a, b, _link, diagram = _pair(client, token, p)
    route = {
        "source_element_id": a["id"], "target_element_id": b["id"], "source_point": None, "target_point": None, "points": [],
        "line_shape": "curved",
    }
    saved = _save(client, token, p, diagram, a, b, [route])
    assert saved["version"] == diagram["version"] + 1
    assert view(client, token, p, diagram["id"])["anchors"] == [{**route, "connection_id": None}]
    nothing = {**route, "line_shape": None}
    _save(client, token, p, saved, a, b, [nothing], expect=400)  # no end, no vertex and no shape: nothing to store
    cleared = _save(client, token, p, saved, a, b, [])
    assert view(client, token, p, cleared["id"])["anchors"] == []


def test_a_connections_own_route_may_carry_a_shape(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape connection")
    p = project["id"]
    a, b, link, diagram = _pair(client, token, p)
    route = {
        "source_element_id": a["id"], "target_element_id": b["id"], "connection_id": link["id"], "source_point": None, "target_point": None,
        "points": [], "line_shape": "spline",
    }
    _save(client, token, p, diagram, a, b, [route])
    (stored,) = view(client, token, p, diagram["id"])["anchors"]
    assert stored["connection_id"] == link["id"] and stored["line_shape"] == "spline"


def test_an_unknown_line_shape_is_refused(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape unknown")
    p = project["id"]
    a, b, _link, diagram = _pair(client, token, p)
    bad = {"source_element_id": a["id"], "target_element_id": b["id"], "points": [{"x": 1, "y": 1}], "line_shape": "zigzag"}
    _save(client, token, p, diagram, a, b, [bad], expect=422)
    notes = [{"text": "N", "leaders": [{"kind": "point", "x": 1, "y": 1, "line_shape": "zigzag"}]}]
    _save(client, token, p, diagram, a, b, notes=notes, expect=422)


# --- Drawing ---------------------------------------------------------------------------------------------------------------


def test_the_svg_draws_each_shape_and_a_line_follows_the_diagram_unless_it_has_its_own(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape svg")
    p = project["id"]
    a, b, _link, diagram = _pair(client, token, p)
    assert "<line " in _svg(client, token, p, diagram["id"]) and " C " not in _svg(client, token, p, diagram["id"])
    curved = _edit(client, token, p, diagram, line_shape="curved").json()
    svg = _svg(client, token, p, curved["id"])
    # The boxes face each other in line, so the curve leaves and arrives square on and lies on the chord (the control points are
    # 0.4 of the 240-unit chord from each end).
    assert 'd="M 160 40 C 256 40 304 40 400 40"' in svg and "<line " not in svg
    own = {"source_element_id": a["id"], "target_element_id": b["id"], "points": [], "line_shape": "straight"}
    saved = _save(client, token, p, curved, a, b, [own])
    svg = _svg(client, token, p, saved["id"])
    assert " C " not in svg and '<line x1="160.0" y1="40.0" x2="400.0" y2="40.0"' in svg  # its own straight overrides the curved default


def test_a_curved_default_draws_a_leader_and_its_hop_paths_still_arrive(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape leader")
    p = project["id"]
    a, b, _link, diagram = _pair(client, token, p, line_shape="curved", line_hops=True)
    notes = [{"text": "Note", "x": 100, "y": -200, "leaders": [{"kind": "point", "x": 300, "y": -60}]}]
    saved = _save(client, token, p, diagram, a, b, notes=notes)
    svg = _svg(client, token, p, saved["id"])
    assert len(re.findall(r" C ", svg)) >= 2  # the connection and the leader are both arcs


def _three_boxes(client, admin_token, name, reverse, fixed_points=False):
    """Battery (0, 0), MCU (400, 30) and Sensor Head (800, 230), joined Battery to MCU and MCU to Sensor Head (each stored the other
    way round when `reverse`), in a diagram that defaults to Curved. With `fixed_points` the lines meet the sides that face each
    other, whatever the order they are stored in. Returns the SVG."""
    _org, project, token = setup(client, admin_token, name)
    p = project["id"]
    battery, mcu, sensor = (make_element(client, token, p, n) for n in ("Battery Management", "MCU", "Sensor Head"))
    anchors = []
    for first, second in ((battery, mcu), (mcu, sensor)):
        source, target = (second, first) if reverse else (first, second)
        make_connection(client, token, p, source["id"], target["id"])
        points = ("left", "right") if reverse else ("right", "left")
        if fixed_points:
            anchors.append({
                "source_element_id": source["id"], "target_element_id": target["id"],
                "source_point": points[0], "target_point": points[1], "points": [],
            })
    diagram = make_diagram(client, token, p, "Power", line_shape="curved")
    layout = [
        {"element_id": battery["id"], "x": 0, "y": 0}, {"element_id": mcu["id"], "x": 400, "y": 30},
        {"element_id": sensor["id"], "x": 800, "y": 230},
    ]
    resp = client.put(
        f"{project_base(p)}/diagrams/{diagram['id']}/layout",
        json={"version": diagram["version"], "placements": layout, "notes": [], "anchors": anchors}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return _svg(client, token, p, resp.json()["id"])


def _curves(svg):
    """Every drawn single-span curve as `(start, control 1, control 2, end)`, left to right."""
    pattern = r'<path d="M ([\d.-]+) ([\d.-]+) C ([\d.-]+) ([\d.-]+) ([\d.-]+) ([\d.-]+) ([\d.-]+) ([\d.-]+)"'
    found = [tuple((float(m[i]), float(m[i + 1])) for i in range(0, 8, 2)) for m in re.findall(pattern, svg)]
    return sorted(found, key=lambda curve: min(curve[0][0], curve[3][0]))


def _deviation(curve):
    """The furthest the curve strays from the straight line between its ends."""
    (x0, y0), c1, c2, (x3, y3) = curve
    length = ((x3 - x0) ** 2 + (y3 - y0) ** 2) ** 0.5
    worst = 0.0
    for i in range(1, 20):
        t = i / 20
        m = 1 - t
        x = m**3 * x0 + 3 * m * m * t * c1[0] + 3 * m * t * t * c2[0] + t**3 * x3
        y = m**3 * y0 + 3 * m * m * t * c1[1] + 3 * m * t * t * c2[1] + t**3 * y3
        worst = max(worst, abs((x - x0) * (y3 - y0) - (y - y0) * (x3 - x0)) / length)
    return worst


#: The directions a line may leave a 160 x 80 box in: the four side normals and the four centre-to-corner diagonals.
_OUTWARD = [(1, 0), (-1, 0), (0, 1), (0, -1)] + [(sx * 0.8944272, sy * 0.4472136) for sx in (1, -1) for sy in (1, -1)]


def _leaves_outward(origin, control) -> bool:
    length = ((control[0] - origin[0]) ** 2 + (control[1] - origin[1]) ** 2) ** 0.5
    unit = ((control[0] - origin[0]) / length, (control[1] - origin[1]) / length)
    return any(abs(unit[0] - d[0]) < 1e-3 and abs(unit[1] - d[1]) < 1e-3 for d in _OUTWARD)


def test_a_curved_line_leaves_each_box_outward_and_bends_only_as_the_boxes_need(client, admin_token):
    battery_mcu, mcu_sensor = _curves(_three_boxes(client, admin_token, "Arch curved three", reverse=False))
    # Battery Management and the MCU are almost level: the line from one to the other is close to straight (it was bowed by 60).
    assert _deviation(battery_mcu) < 8
    for start, c1, c2, end in (battery_mcu, mcu_sensor):
        assert _leaves_outward(start, c1) and _leaves_outward(end, c2)
    # The Sensor Head sits lower and further on, so that line is an S that stays inside the boxes' offset.
    assert 0 < _deviation(mcu_sensor) < 60


def test_a_curved_line_is_the_same_whichever_way_the_connection_is_stored(client, admin_token):
    forward = _curves(_three_boxes(client, admin_token, "Arch curved forward", reverse=False, fixed_points=True))
    backward = _curves(_three_boxes(client, admin_token, "Arch curved backward", reverse=True, fixed_points=True))
    assert len(forward) == len(backward) == 2
    for a, b in zip(forward, backward, strict=True):
        assert a == tuple(reversed(b))


def test_three_lines_between_two_boxes_take_three_paths_and_stay_apart_when_curved():
    from app.modules.architecture.diagram_line_anchors import AnchorBox, AnchorLine, assign_line_anchors
    from app.modules.architecture.diagram_line_path import line_path
    from app.modules.architecture.diagram_points import ATTACH_POINTS, line_directions, point_xy

    boxes = {"a": AnchorBox(0, 0, 160, 80, ATTACH_POINTS), "b": AnchorBox(400, 0, 160, 80, ATTACH_POINTS)}
    lines = [AnchorLine("l1", "a", "b", None, None, ()), AnchorLine("l2", "b", "a", None, None, ()), AnchorLine("l3", "a", "b", None, None, ())]
    placed = assign_line_anchors(boxes, lines)
    paths = set()
    for line in lines:
        anchor = placed[line.id]
        source, target = boxes[line.source], boxes[line.target]
        a, b = (source.x, source.y, source.width, source.height), (target.x, target.y, target.width, target.height)
        start, end = point_xy(a, anchor.source), point_xy(b, anchor.target)
        start = (start[0] + anchor.shift[0], start[1] + anchor.shift[1])
        end = (end[0] + anchor.shift[0], end[1] + anchor.shift[1])
        paths.add(line_path(start, [], end, "curved", line_directions(a, b, anchor.source, anchor.target, [])))
    assert len(paths) == 3


# --- State machines --------------------------------------------------------------------------------------------------------


def test_a_state_machine_default_and_a_transitions_own_shape(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape machine")
    p = project["id"]
    element = make_element(client, token, p, "Printer")
    machine, states = sound_machine(client, token, p, element["id"])
    _spread(client, token, p, machine, states)
    assert machine["line_shape"] == "straight"
    url = f"{project_base(p)}/state-machine-diagrams/{machine['id']}"
    edited = client.put(url, json={"version": machine_version(client, token, p, machine["id"]), "line_shape": "curved"}, headers=auth_headers(token))
    assert edited.status_code == 200 and edited.json()["line_shape"] == "curved"
    svg = client.get(f"{url}/svg", headers=auth_headers(token)).text
    assert svg.count(" C ") >= 2 and re.search(r'<path d="M [\d. -]+ C ', svg)  # both transitions are arcs now
    first, second = machine_model(client, token, p, machine["id"])["transitions"]
    assert first["line_shape"] is None
    layout = {
        "version": machine_version(client, token, p, machine["id"]), "states": [],
        "transitions": [{"id": first["id"], "line_shape": "straight"}],
    }
    assert client.put(f"{url}/layout", json=layout, headers=auth_headers(token)).status_code == 200
    svg = client.get(f"{url}/svg", headers=auth_headers(token)).text
    assert svg.count(" C ") == 1 and "<line " in svg  # one transition straight by its own choice, one following the default
    assert second["id"] != first["id"] and states


def test_a_transition_shape_of_null_follows_the_diagram_again(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch shape machine null")
    p = project["id"]
    element = make_element(client, token, p, "Printer")
    machine, states = sound_machine(client, token, p, element["id"])
    made = add_transition(client, token, p, machine["id"], states["Running"]["id"], states["Running"]["id"], line_shape="spline")
    assert made["line_shape"] == "spline"
    url = f"{project_base(p)}/state-machine-diagrams/{machine['id']}/transitions/{made['id']}"
    version = machine_version(client, token, p, machine["id"])
    left_out = client.put(url, json={"version": version, "event": "again"}, headers=auth_headers(token))
    assert left_out.json()["line_shape"] == "spline"  # a field left out is kept
    cleared = client.put(url, json={"version": version + 1, "line_shape": None}, headers=auth_headers(token))
    assert cleared.status_code == 200 and cleared.json()["line_shape"] is None  # null is a value here: follow the diagram


# --- Bundles ---------------------------------------------------------------------------------------------------------------


def _spread(client, token, project_id, machine, states) -> None:
    """Puts the states of a sound state machine side by side, so no transition has zero length."""
    layout = {
        "version": machine_version(client, token, project_id, machine["id"]),
        "states": [
            {"id": state["id"], "x": index * 300, "y": 0, "width": 120, "height": 60} for index, state in enumerate(states.values())
        ],
        "transitions": [],
    }
    url = f"{project_base(project_id)}/state-machine-diagrams/{machine['id']}/layout"
    assert client.put(url, json=layout, headers=auth_headers(token)).status_code == 200


def _bundle(client, token, project_id) -> tuple[zipfile.ZipFile, dict]:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200
    source = zipfile.ZipFile(io.BytesIO(resp.content))
    return source, json.loads(source.read("project.json"))


def _import(client, token, org_id, source, data, name):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item.filename, json.dumps(data) if item.filename == "project.json" else source.read(item.filename))
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["project"]["id"]


def test_the_default_and_each_own_shape_round_trip_through_the_project_bundle(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch shape bundle")
    p = project["id"]
    a, b, _link, diagram = _pair(client, token, p, line_shape="curved")
    own = {"source_element_id": a["id"], "target_element_id": b["id"], "points": [{"x": 200, "y": -60}], "line_shape": "spline"}
    leaders = [{"kind": "point", "x": 300, "y": -60, "line_shape": "straight"}, {"kind": "element", "element_id": a["id"]}]
    notes = [{"text": "Note", "leaders": leaders}]
    _save(client, token, p, diagram, a, b, [own], notes)
    element = make_element(client, token, p, "Printer")
    machine, _states = sound_machine(client, token, p, element["id"])
    url = f"{project_base(p)}/state-machine-diagrams/{machine['id']}"
    client.put(url, json={"version": machine_version(client, token, p, machine["id"]), "line_shape": "spline"}, headers=auth_headers(token))
    source, data = _bundle(client, token, p)
    assert data["architecture_diagrams"][0]["line_shape"] == "curved"
    assert data["architecture_diagrams"][0]["anchors"][0]["line_shape"] == "spline"
    assert data["architecture_state_machine_diagrams"][0]["line_shape"] == "spline"
    copy = _import(client, token, org["id"], source, data, "Arch shape bundle copy")
    (diagram_copy,) = client.get(f"{project_base(copy)}/diagrams", headers=auth_headers(token)).json()
    assert diagram_copy["line_shape"] == "curved"
    copied = view(client, token, copy, diagram_copy["id"])
    assert [x["line_shape"] for x in copied["anchors"]] == ["spline"]
    assert sorted(str(leader["line_shape"]) for n in copied["notes"] for leader in n["leaders"]) == ["None", "straight"]
    (machine_copy,) = client.get(f"{project_base(copy)}/state-machine-diagrams", headers=auth_headers(token)).json()
    assert machine_copy["line_shape"] == "spline"


def test_a_bundle_written_before_shapes_reads_smooth_as_a_spline_and_an_unknown_shape_as_none(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch shape legacy")
    p = project["id"]
    a, b, _link, diagram = _pair(client, token, p)
    own = {"source_element_id": a["id"], "target_element_id": b["id"], "points": [{"x": 200, "y": -60}], "line_shape": "curved"}
    notes = [{"text": "Note", "leaders": [{"kind": "point", "x": 300, "y": -60}, {"kind": "element", "element_id": a["id"]}]}]
    _save(client, token, p, diagram, a, b, [own], notes)
    source, data = _bundle(client, token, p)
    entry = data["architecture_diagrams"][0]
    del entry["line_shape"]
    entry["anchors"][0].pop("line_shape")
    entry["anchors"][0]["smooth"] = True
    leaders = entry["notes"][0]["leaders"]
    leaders[0].pop("line_shape")
    leaders[0]["smooth"] = True
    leaders[1]["line_shape"] = "zigzag"
    copy = _import(client, token, org["id"], source, data, "Arch shape legacy copy")
    (diagram_copy,) = client.get(f"{project_base(copy)}/diagrams", headers=auth_headers(token)).json()
    assert diagram_copy["line_shape"] == "straight"  # an older bundle has no default
    copied = view(client, token, copy, diagram_copy["id"])
    assert [x["line_shape"] for x in copied["anchors"]] == ["spline"]
    assert sorted(str(leader["line_shape"]) for n in copied["notes"] for leader in n["leaders"]) == ["None", "spline"]


# --- Migration -------------------------------------------------------------------------------------------------------------


def test_the_line_shape_migration_turns_smooth_into_a_spline_and_back(client, admin_token):
    """Downgrading 0198 brings the flag back (a spline is smooth, any other shape is not, the diagrams' default is dropped);
    a flag raised while downgraded becomes a spline on upgrade and one not raised stays following the diagram."""
    _org, project, token = setup(client, admin_token, "Arch shape migration")
    p = project["id"]
    a, b, _link, diagram = _pair(client, token, p, line_shape="curved")
    routes = [
        {"source_element_id": a["id"], "target_element_id": b["id"], "points": [{"x": 5, "y": 5}], "line_shape": "spline"},
    ]
    saved = _save(client, token, p, diagram, a, b, routes)
    element = make_element(client, token, p, "Printer")
    machine, _states = sound_machine(client, token, p, element["id"])
    first = machine_model(client, token, p, machine["id"])["transitions"][0]["id"]
    layout = {"version": machine_version(client, token, p, machine["id"]), "states": [], "transitions": [{"id": first, "line_shape": "curved"}]}
    url = f"{project_base(p)}/state-machine-diagrams/{machine['id']}"
    assert client.put(f"{url}/layout", json=layout, headers=auth_headers(token)).status_code == 200
    command.downgrade(build_alembic_config(), "0197")
    try:
        with engine.connect() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name IN "
                "('architecture_diagram_anchors', 'architecture_transitions', 'architecture_diagrams')"
            ))}
            assert "smooth" in columns and "line_shape" not in columns
            assert conn.execute(text("SELECT smooth FROM architecture_diagram_anchors")).scalar_one() is True
            smooth = {r[0]: r[1] for r in conn.execute(text("SELECT id::text, smooth FROM architecture_transitions"))}
            assert smooth[first] is False  # curved is not a smooth flag
            conn.execute(text("UPDATE architecture_transitions SET smooth = true WHERE id = :i"), {"i": first})
            conn.commit()
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.connect() as conn:
        shapes = {r[0]: r[1] for r in conn.execute(text("SELECT id::text, line_shape FROM architecture_transitions"))}
        assert shapes[first] == "spline" and [v for k, v in shapes.items() if k != first] == [None] * (len(shapes) - 1)
        assert conn.execute(text("SELECT line_shape FROM architecture_diagram_anchors")).scalar_one() == "spline"
        default = text("SELECT line_shape FROM architecture_diagrams WHERE id = :i")
        assert conn.execute(default, {"i": uuid_of(saved["id"])}).scalar_one() == "straight"


def uuid_of(value: str):
    import uuid

    return uuid.UUID(value)
