"""Tests for the line anchors of a diagram: where a drawn line meets its boxes when a person has chosen the points.

Covers the layout save (stored, replaced, kept when the field is left out, cleared by an empty list), what the save
refuses, the removal of an anchor with its box (unplacing and deleting the element), the version lock, the server SVG
drawing the chosen points, and the project bundle round trip. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import re
import zipfile

from app.modules.architecture.tests._helpers import (
    make_connection,
    make_diagram,
    make_element,
    place_all,
    project_base,
    setup,
    view,
)
from tests.conftest import auth_headers


def _save(client, token, project_id, diagram, placements, anchors=None, *, expect=200, notes=()):
    body = {"version": diagram["version"], "placements": placements, "notes": list(notes)}
    if anchors is not None:
        body["anchors"] = anchors
    resp = client.put(f"{project_base(project_id)}/diagrams/{diagram['id']}/layout", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _pair(client, token, project_id):
    """Two connected, placed elements side by side: `(a, b, diagram)`."""
    a = make_element(client, token, project_id, "Alpha")
    b = make_element(client, token, project_id, "Bravo")
    make_connection(client, token, project_id, a["id"], b["id"])
    diagram = place_all(client, token, project_id, make_diagram(client, token, project_id, "Flow"), a["id"], b["id"])
    return a, b, diagram


def _boxes(a, b):
    return [{"element_id": a["id"], "x": 0, "y": 0}, {"element_id": b["id"], "x": 400, "y": 0}]


def _anchor(a, b, source_point="bottom", target_point="top"):
    return {"source_element_id": a["id"], "target_element_id": b["id"], "source_point": source_point, "target_point": target_point}


def test_an_anchor_is_stored_returned_in_the_view_and_advances_the_version(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch anchors store")
    a, b, diagram = _pair(client, token, project["id"])
    assert view(client, token, project["id"], diagram["id"])["anchors"] == []
    saved = _save(client, token, project["id"], diagram, _boxes(a, b), [_anchor(a, b)])
    assert saved["version"] == diagram["version"] + 1
    assert view(client, token, project["id"], diagram["id"])["anchors"] == [_anchor(a, b)]


def test_one_end_can_be_left_automatic(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch anchors half")
    a, b, diagram = _pair(client, token, project["id"])
    _save(client, token, project["id"], diagram, _boxes(a, b), [_anchor(a, b, "left", None)])
    (stored,) = view(client, token, project["id"], diagram["id"])["anchors"]
    assert (stored["source_point"], stored["target_point"]) == ("left", None)


def test_a_save_that_leaves_anchors_out_keeps_them_and_an_empty_list_clears_them(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch anchors keep")
    a, b, diagram = _pair(client, token, project["id"])
    saved = _save(client, token, project["id"], diagram, _boxes(a, b), [_anchor(a, b)])
    moved = _save(client, token, project["id"], saved, [{"element_id": a["id"], "x": 10, "y": 0}, {"element_id": b["id"], "x": 400, "y": 0}])
    assert len(view(client, token, project["id"], diagram["id"])["anchors"]) == 1
    _save(client, token, project["id"], moved, [{"element_id": a["id"], "x": 10, "y": 0}, {"element_id": b["id"], "x": 400, "y": 0}], [])
    assert view(client, token, project["id"], diagram["id"])["anchors"] == []


def test_a_save_of_the_same_anchors_changes_nothing_and_a_new_choice_replaces_the_old(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch anchors replace")
    a, b, diagram = _pair(client, token, project["id"])
    saved = _save(client, token, project["id"], diagram, _boxes(a, b), [_anchor(a, b)])
    again = _save(client, token, project["id"], saved, _boxes(a, b), [_anchor(a, b)])
    assert again["version"] == saved["version"]
    changed = _save(client, token, project["id"], again, _boxes(a, b), [_anchor(a, b, "right", "left")])
    assert changed["version"] == saved["version"] + 1
    assert view(client, token, project["id"], diagram["id"])["anchors"] == [_anchor(a, b, "right", "left")]


def test_the_save_refuses_a_bad_anchor(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch anchors refuse")
    a, b, diagram = _pair(client, token, project["id"])
    c = make_element(client, token, project["id"], "Charlie")
    p = project["id"]
    _save(client, token, p, diagram, _boxes(a, b), [_anchor(a, a)], expect=400)  # to itself
    _save(client, token, p, diagram, _boxes(a, b), [_anchor(a, c)], expect=400)  # an end that is not placed
    _save(client, token, p, diagram, _boxes(a, b), [_anchor(a, b, None, None)], expect=400)  # fixes nothing
    _save(client, token, p, diagram, _boxes(a, b), [_anchor(a, b, "middle", "top")], expect=422)  # not one of the eight
    _save(client, token, p, diagram, _boxes(a, b), [_anchor(a, b), _anchor(b, a)], expect=400)  # one line, twice
    assert view(client, token, p, diagram["id"])["anchors"] == []


def test_unplacing_a_box_removes_its_anchors_and_so_does_deleting_the_element(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch anchors follow")
    a, b, diagram = _pair(client, token, project["id"])
    p = project["id"]
    saved = _save(client, token, p, diagram, _boxes(a, b), [_anchor(a, b)])
    # Leaving the box out of a save drops the anchor even though the save names no anchors.
    kept = _save(client, token, p, saved, [{"element_id": a["id"], "x": 0, "y": 0}])
    assert view(client, token, p, diagram["id"])["anchors"] == []
    # The box and its anchor come back only by being saved again.
    again = _save(client, token, p, kept, _boxes(a, b), [_anchor(a, b)])
    resp = client.delete(
        f"{project_base(p)}/diagrams/{diagram['id']}/placements/{b['id']}", params={"version": again["version"]},
        headers=auth_headers(token),
    )
    assert resp.status_code in (200, 204), resp.text
    assert view(client, token, p, diagram["id"])["anchors"] == []
    # Deleting the element removes the anchor with its box (a database cascade).
    c = make_element(client, token, p, "Charlie")
    current = client.get(f"{project_base(p)}/diagrams/{diagram['id']}", headers=auth_headers(token)).json()
    placed = _save(client, token, p, current, [{"element_id": a["id"], "x": 0, "y": 0}, {"element_id": c["id"], "x": 400, "y": 0}], [_anchor(a, c)])
    assert len(view(client, token, p, diagram["id"])["anchors"]) == 1 and placed["version"] > current["version"]
    assert client.delete(f"{project_base(p)}/elements/{c['id']}", headers=auth_headers(token)).status_code in (200, 204)
    assert view(client, token, p, diagram["id"])["anchors"] == []


def test_a_stale_version_is_refused_and_stores_no_anchor(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch anchors stale")
    a, b, diagram = _pair(client, token, project["id"])
    _save(client, token, project["id"], diagram, _boxes(a, b), [_anchor(a, b)])
    _save(client, token, project["id"], diagram, _boxes(a, b), [_anchor(a, b, "left", "right")], expect=409)
    assert view(client, token, project["id"], diagram["id"])["anchors"] == [_anchor(a, b)]


def _line_ends(svg: str) -> tuple[float, float, float, float]:
    match = re.search(r'<line x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" y2="([\d.-]+)"', svg)
    assert match, svg
    x1, y1, x2, y2 = (float(v) for v in match.groups())
    return x1, y1, x2, y2


def test_the_svg_draws_the_nearest_points_and_then_the_chosen_ones(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch anchors svg")
    a, b, diagram = _pair(client, token, project["id"])
    p = project["id"]
    # Boxes are 160 x 80 at x = 0 and 400: the facing sides' middles are at (160, 40) and (400, 40).
    saved = _save(client, token, p, diagram, _boxes(a, b))
    svg = client.get(f"{project_base(p)}/diagrams/{saved['id']}/svg", headers=auth_headers(token)).text
    assert _line_ends(svg) == (160.0, 40.0, 400.0, 40.0)
    # Chosen: the bottom of Alpha (80, 80) to the top-left corner of Bravo (400, 0).
    chosen = _save(client, token, p, saved, _boxes(a, b), [_anchor(a, b, "bottom", "top_left")])
    svg = client.get(f"{project_base(p)}/diagrams/{chosen['id']}/svg", headers=auth_headers(token)).text
    assert _line_ends(svg) == (80.0, 80.0, 400.0, 0.0)
    # An end left automatic follows the other: with Alpha's bottom fixed, Bravo's nearest point to (80, 80) is its bottom-left corner.
    half = _save(client, token, p, chosen, _boxes(a, b), [_anchor(a, b, "bottom", None)])
    svg = client.get(f"{project_base(p)}/diagrams/{half['id']}/svg", headers=auth_headers(token)).text
    assert _line_ends(svg) == (80.0, 80.0, 400.0, 80.0)


def test_an_anchor_applies_to_a_line_drawn_the_other_way(client, admin_token):
    """A line from Bravo to Alpha shares the anchor stored for Alpha to Bravo, with the ends swapped."""
    _org, project, token = setup(client, admin_token, "Arch anchors reversed")
    a = make_element(client, token, project["id"], "Alpha")
    b = make_element(client, token, project["id"], "Bravo")
    make_connection(client, token, project["id"], b["id"], a["id"])
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Flow"), a["id"], b["id"])
    saved = _save(client, token, project["id"], diagram, _boxes(a, b), [_anchor(a, b, "bottom", "top_left")])
    svg = client.get(f"{project_base(project['id'])}/diagrams/{saved['id']}/svg", headers=auth_headers(token)).text
    # The line runs Bravo (source) to Alpha (target); the anchor's Alpha end is the line's target end.
    assert _line_ends(svg) == (400.0, 0.0, 80.0, 80.0)


def test_anchors_round_trip_through_the_project_bundle(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch anchors bundle")
    a, b, diagram = _pair(client, token, project["id"])
    _save(client, token, project["id"], diagram, _boxes(a, b), [_anchor(a, b, "bottom", None)])
    resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert resp.status_code == 200
    data = json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))
    (entry,) = data["architecture_diagrams"]
    assert entry["anchors"] == [{
        "source": {"code": a["unique_code"]}, "target": {"code": b["unique_code"]}, "source_point": "bottom", "target_point": None,
    }]
    assert str(a["id"]) not in json.dumps(entry)  # codes, never ids

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch anchors bundle copy"},
        files={"file": ("bundle.zip", resp.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    (diagram_copy,) = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    (stored,) = view(client, token, copy["id"], diagram_copy["id"])["anchors"]
    assert (stored["source_point"], stored["target_point"]) == ("bottom", None)
    copy_elements = {e["name"]: e["id"] for e in client.get(f"{project_base(copy['id'])}/elements", headers=auth_headers(token)).json()}
    assert (stored["source_element_id"], stored["target_element_id"]) == (copy_elements["Alpha"], copy_elements["Bravo"])


def test_an_import_drops_an_anchor_it_cannot_restore_with_a_warning(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch anchors bad bundle")
    a, b, diagram = _pair(client, token, project["id"])
    _save(client, token, project["id"], diagram, _boxes(a, b), [_anchor(a, b)])
    resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    source = zipfile.ZipFile(io.BytesIO(resp.content))
    data = json.loads(source.read("project.json"))
    entry = data["architecture_diagrams"][0]
    good = entry["anchors"][0]
    entry["anchors"] = [
        {**good, "source_point": "middle"},  # not one of the eight
        {**good, "source": {"code": "ELM-999"}},  # an element the bundle does not hold
        {**good, "source_point": None, "target_point": None},  # fixes nothing
        good,
        {"source": good["target"], "target": good["source"], "source_point": "top", "target_point": "top"},  # the same line again
    ]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item.filename, json.dumps(data) if item.filename == "project.json" else source.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch anchors bad copy"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    (diagram_copy,) = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    assert len(view(client, token, copy["id"], diagram_copy["id"])["anchors"]) == 1
    assert sum("line anchor" in w for w in imported.json().get("warnings", [])) == 4
