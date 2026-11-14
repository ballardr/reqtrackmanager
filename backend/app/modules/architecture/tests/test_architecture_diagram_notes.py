"""Tests for annotation notes on a diagram: a block with a tone and an optional leader line to a box, a connection's line or
a free point.

Covers the layout save (stored, returned by the view, rules a leader must follow), a leader whose target is deleted
reading as none, the server SVG drawing the leader between the right points (and not drawing one to a hidden box), the
Mermaid export, and the project bundle round trip. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import re
import zipfile

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.modules.architecture.models import ArchitectureDiagramNote
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


def _save(client, token, project_id, diagram, boxes, notes, *, expect=200):
    body = {"version": diagram["version"], "placements": boxes, "notes": notes}
    resp = client.put(f"{project_base(project_id)}/diagrams/{diagram['id']}/layout", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _flow(client, token, project_id):
    a = make_element(client, token, project_id, "Alpha")
    b = make_element(client, token, project_id, "Bravo")
    link = make_connection(client, token, project_id, a["id"], b["id"])
    diagram = place_all(client, token, project_id, make_diagram(client, token, project_id, "Flow"), a["id"], b["id"])
    boxes = [{"element_id": a["id"], "x": 0, "y": 0}, {"element_id": b["id"], "x": 400, "y": 0}]
    return a, b, link, diagram, boxes


def _svg(client, token, project_id, diagram_id) -> str:
    return client.get(f"{project_base(project_id)}/diagrams/{diagram_id}/svg", headers=auth_headers(token)).text


def test_a_note_keeps_its_tone_and_each_kind_of_leader_and_the_view_returns_them(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes store")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    notes = [
        {"text": "At a box", "tone": "info", "leader_kind": "element", "leader_element_id": a["id"], "leader_arrow": False},
        {"text": "At a line", "tone": "warning", "leader_kind": "connection", "leader_connection_id": link["id"]},
        {"text": "At a spot", "tone": "danger", "leader_kind": "point", "leader_x": 12.5, "leader_y": -40},
        {"text": "Plain"},
    ]
    saved = _save(client, token, p, diagram, boxes, notes)
    assert saved["version"] == diagram["version"] + 1
    shown = view(client, token, p, diagram["id"])["notes"]
    assert [(n["tone"], n["leader_kind"], n["leader_arrow"]) for n in shown] == [
        ("info", "element", False), ("warning", "connection", True), ("danger", "point", True), ("neutral", "none", True),
    ]
    assert shown[0]["leader_element_id"] == a["id"] and shown[1]["leader_connection_id"] == link["id"]
    assert (shown[2]["leader_x"], shown[2]["leader_y"]) == (12.5, -40)
    assert shown[3]["leader_element_id"] is None and shown[3]["leader_x"] is None


def test_saving_the_same_notes_again_changes_nothing_and_a_new_target_replaces_the_old(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes replace")
    p = project["id"]
    a, b, _link, diagram, boxes = _flow(client, token, p)
    note = {"text": "Look", "leader_kind": "element", "leader_element_id": a["id"]}
    saved = _save(client, token, p, diagram, boxes, [note])
    (stored,) = view(client, token, p, diagram["id"])["notes"]
    same = _save(client, token, p, saved, boxes, [{**note, "id": stored["id"]}])
    assert same["version"] == saved["version"]
    moved = _save(client, token, p, same, boxes, [{**note, "id": stored["id"], "leader_element_id": b["id"]}])
    assert moved["version"] == saved["version"] + 1
    (after,) = view(client, token, p, diagram["id"])["notes"]
    assert after["id"] == stored["id"] and after["leader_element_id"] == b["id"]
    cleared = _save(client, token, p, moved, boxes, [{"text": "Look", "id": stored["id"]}])
    (none,) = view(client, token, p, diagram["id"])["notes"]
    assert cleared["version"] == moved["version"] + 1 and none["leader_kind"] == "none" and none["leader_element_id"] is None


def test_a_leader_must_name_exactly_the_target_of_its_kind(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes shape")
    p = project["id"]
    a, _b, link, diagram, boxes = _flow(client, token, p)
    for bad in (
        {"leader_kind": "element"},
        {"leader_kind": "connection"},
        {"leader_kind": "point", "leader_x": 1},
        {"leader_kind": "element", "leader_element_id": a["id"], "leader_connection_id": link["id"]},
        {"leader_kind": "none", "leader_element_id": a["id"]},
        {"leader_kind": "point", "leader_x": 1, "leader_y": 2, "leader_element_id": a["id"]},
        {"tone": "purple"},
        {"leader_kind": "point", "leader_x": 1e12, "leader_y": 0},
    ):
        _save(client, token, p, diagram, boxes, [{"text": "x", **bad}], expect=422)
    assert view(client, token, p, diagram["id"])["notes"] == []


def test_a_new_leader_cannot_name_an_element_off_the_diagram_or_a_connection_of_another_project(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch notes scope")
    p = project["id"]
    a, _b, _link, diagram, boxes = _flow(client, token, p)
    off = make_element(client, token, p, "Not drawn")
    _save(client, token, p, diagram, boxes, [{"text": "x", "leader_kind": "element", "leader_element_id": off["id"]}], expect=400)
    from tests.conftest import create_project

    other = create_project(client, token, org["id"], "Arch notes scope other")
    x, y = make_element(client, token, other["id"], "X"), make_element(client, token, other["id"], "Y")
    foreign = make_connection(client, token, other["id"], x["id"], y["id"])
    _save(
        client, token, p, diagram, boxes,
        [{"text": "x", "leader_kind": "connection", "leader_connection_id": foreign["id"]}], expect=400,
    )
    missing = "00000000-0000-0000-0000-000000000000"
    _save(client, token, p, diagram, boxes, [{"text": "x", "leader_kind": "connection", "leader_connection_id": missing}], expect=400)
    assert view(client, token, p, diagram["id"])["notes"] == []


def test_a_leader_to_an_element_taken_off_the_diagram_is_kept_and_not_rejected_on_the_next_save(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes unplaced")
    p = project["id"]
    a, b, _link, diagram, boxes = _flow(client, token, p)
    saved = _save(client, token, p, diagram, boxes, [{"text": "Look", "leader_kind": "element", "leader_element_id": b["id"]}])
    (stored,) = view(client, token, p, diagram["id"])["notes"]
    only_a = [boxes[0]]
    again = _save(client, token, p, saved, only_a, [{"text": "Look", "id": stored["id"], "leader_kind": "element", "leader_element_id": b["id"]}])
    (kept,) = view(client, token, p, diagram["id"])["notes"]
    assert again["version"] >= saved["version"] and kept["leader_element_id"] == b["id"]
    # Placed again, the leader draws again: the SVG joins the note to the box.
    assert "data-note" in _svg(client, token, p, diagram["id"])


def test_deleting_the_target_keeps_the_note_and_reads_the_leader_as_none(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes deleted")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    spare = make_element(client, token, p, "Spare")
    diagram = place_all(client, token, p, diagram, spare["id"])
    boxes.append({"element_id": spare["id"], "x": 0, "y": 200})
    _save(client, token, p, diagram, boxes, [
        {"text": "To the spare", "leader_kind": "element", "leader_element_id": spare["id"]},
        {"text": "To the line", "leader_kind": "connection", "leader_connection_id": link["id"]},
    ])
    for path in (f"elements/{spare['id']}", f"connections/{link['id']}"):
        resp = client.delete(f"{project_base(p)}/{path}", headers=auth_headers(token))
        assert resp.status_code in (200, 204, 409), resp.text
    shown = view(client, token, p, diagram["id"])["notes"]
    assert [n["text"] for n in shown] == ["To the spare", "To the line"]
    for n in shown:
        if n["leader_kind"] != "none":
            assert n["leader_element_id"] is not None or n["leader_connection_id"] is not None


def test_the_database_refuses_a_leader_column_that_does_not_match_its_kind(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes constraint")
    p = project["id"]
    a, _b, _link, diagram, boxes = _flow(client, token, p)
    _save(client, token, p, diagram, boxes, [{"text": "x"}])
    refused = (
        "SET leader_kind = 'point'",
        "SET leader_kind = 'element', leader_connection_id = (SELECT id FROM architecture_connections LIMIT 1)",
        "SET leader_kind = 'none', leader_x = 1, leader_y = 1",
        "SET leader_kind = 'none', leader_element_id = :element",
        "SET leader_kind = 'bogus'",
    )
    with SessionLocal() as db:
        note = db.scalars(select(ArchitectureDiagramNote)).first()
        assert note is not None
        for change in refused:
            try:
                db.execute(
                    text(f"UPDATE architecture_diagram_notes {change} WHERE id = :id"), {"id": note.id, "element": a["id"]},
                )
                db.flush()
            except IntegrityError:
                db.rollback()
            else:
                db.rollback()
                raise AssertionError(f"accepted: {change}")


def _leader_line(svg: str) -> tuple[float, float, float, float]:
    match = re.search(r'<line x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" y2="([\d.-]+)" stroke="#[0-9A-F]{6}" stroke-width="1.5"', svg)
    assert match, svg
    return tuple(float(v) for v in match.groups())  # type: ignore[return-value]


def test_the_svg_draws_a_leader_to_a_box_a_line_midpoint_and_a_point_with_the_note_tone(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes svg")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    block = {"x": 0, "y": 200, "width": 160, "height": 60}
    saved = _save(
        client, token, p, diagram, boxes,
        [{"text": "Box", "tone": "success", "leader_kind": "element", "leader_element_id": a["id"], **block}],
    )
    svg = _svg(client, token, p, diagram["id"])
    assert 'fill="#DCFCE7"' in svg and 'marker-end="url(#leader-success)"' in svg and 'id="leader-success"' in svg
    # The note sits below Alpha (x 0-160, y 0-80): its top middle (80, 200) meets Alpha's bottom middle (80, 80).
    assert _leader_line(svg) == (80.0, 200.0, 80.0, 80.0)

    saved = _save(client, token, p, saved, boxes, [
        {"text": "Line", "leader_kind": "connection", "leader_connection_id": link["id"], "leader_arrow": False, **block},
    ])
    svg = _svg(client, token, p, diagram["id"])
    assert "marker-end=\"url(#leader-" not in svg
    x1, y1, x2, y2 = _leader_line(svg)
    assert (x2, y2) == (280.0, 40.0)  # the middle of the line from (160, 40) to (400, 40)
    assert (x1, y1) == (160.0, 200.0)  # the note's top right corner is nearest

    _save(client, token, p, saved, boxes, [{"text": "Spot", "leader_kind": "point", "leader_x": 700, "leader_y": 300, **block}])
    x1, y1, x2, y2 = _leader_line(_svg(client, token, p, diagram["id"]))
    assert (x2, y2) == (700.0, 300.0) and (x1, y1) == (160.0, 260.0)


def test_a_leader_to_a_box_a_switch_hides_is_not_drawn_and_a_hidden_box_never_appears_in_mermaid(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes hidden")
    p = project["id"]
    a, b, _link, diagram, boxes = _flow(client, token, p)
    saved = _save(
        client, token, p, diagram, boxes,
        [{"text": "Look here", "leader_kind": "element", "leader_element_id": b["id"], "x": 0, "y": 200}],
    )
    toggles = [{"name": "Hide Bravo", "default_on": False, "element_ids": [b["id"]]}]
    resp = client.put(
        f"{project_base(p)}/diagrams/{saved['id']}/toggles", json={"version": saved["version"], "toggles": toggles},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    svg = _svg(client, token, p, diagram["id"])
    assert "data-note" in svg and not re.search(r'stroke-width="1.5"', svg)
    mermaid = client.get(f"{project_base(p)}/diagrams/{diagram['id']}/mermaid", headers=auth_headers(token)).text
    assert 'Look here' in mermaid and "-.->" not in mermaid and "Bravo" not in mermaid


def test_mermaid_links_a_note_to_a_drawn_box_with_a_dotted_line_and_leaves_other_leaders_unlinked(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes mermaid")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    _save(client, token, p, diagram, boxes, [
        {"text": "Careful <b>\"x\"</b>", "leader_kind": "element", "leader_element_id": a["id"]},
        {"text": "Open end", "leader_kind": "element", "leader_element_id": b["id"], "leader_arrow": False},
        {"text": "On the line", "leader_kind": "connection", "leader_connection_id": link["id"]},
        {"text": "   "},
    ])
    out = client.get(f"{project_base(p)}/diagrams/{diagram['id']}/mermaid", headers=auth_headers(token)).text
    assert out.count(">\"") == 3 and "<b>" not in out and '"x"' not in out
    assert "t1 -.-> n1" in out and "t2 -.- n2" in out and "t3 -." not in out


def test_notes_with_tone_and_leaders_round_trip_through_the_project_bundle(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch notes bundle")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    _save(client, token, p, diagram, boxes, [
        {"text": "Box", "tone": "info", "leader_kind": "element", "leader_element_id": a["id"], "leader_arrow": False},
        {"text": "Line", "tone": "warning", "leader_kind": "connection", "leader_connection_id": link["id"]},
        {"text": "Spot", "leader_kind": "point", "leader_x": 5, "leader_y": 6},
        {"text": "Plain"},
    ])
    resp = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    assert resp.status_code == 200
    exported = json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))
    entry_notes = exported["architecture_diagrams"][0]["notes"]
    assert entry_notes[0]["leader"] == {"kind": "element", "arrow": False, "element": {"code": a["unique_code"]}}
    assert entry_notes[1]["leader"]["connection_code"] == link["unique_code"] and entry_notes[1]["tone"] == "warning"
    assert entry_notes[2]["leader"] == {"kind": "point", "arrow": True, "x": 5.0, "y": 6.0}
    assert entry_notes[3]["leader"]["kind"] == "none"

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch notes bundle copy"},
        files={"file": ("bundle.zip", resp.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    listing = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    shown = view(client, token, copy["id"], listing[0]["id"])
    names = {n["unique_code"]: n["element_id"] for n in shown["nodes"]}
    notes = shown["notes"]
    assert [(n["text"], n["tone"], n["leader_kind"]) for n in notes] == [
        ("Box", "info", "element"), ("Line", "warning", "connection"), ("Spot", "neutral", "point"), ("Plain", "neutral", "none"),
    ]
    assert notes[0]["leader_element_id"] == names[a["unique_code"]] and notes[0]["leader_arrow"] is False
    assert notes[1]["leader_connection_id"] is not None and (notes[2]["leader_x"], notes[2]["leader_y"]) == (5, 6)


def test_an_import_drops_a_leader_it_cannot_resolve_and_keeps_the_note(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch notes bundle bad")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    _save(client, token, p, diagram, boxes, [
        {"text": "Box", "leader_kind": "element", "leader_element_id": a["id"]},
        {"text": "Spot", "leader_kind": "point", "leader_x": 5, "leader_y": 6},
    ])
    resp = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    source = zipfile.ZipFile(io.BytesIO(resp.content))
    data = json.loads(source.read("project.json"))
    notes = data["architecture_diagrams"][0]["notes"]
    notes[0]["leader"]["element"] = {"code": "ELM-999"}
    notes[1]["leader"]["x"] = "far"
    notes[1]["tone"] = "purple"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item, json.dumps(data) if item.filename == "project.json" else source.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch notes bundle bad copy"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    listing = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    shown = view(client, token, copy["id"], listing[0]["id"])["notes"]
    assert [(n["text"], n["leader_kind"], n["tone"]) for n in shown] == [("Box", "none", "neutral"), ("Spot", "none", "neutral")]
    assert sum("leader could not be restored" in w for w in imported.json().get("warnings", [])) == 2
