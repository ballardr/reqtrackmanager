"""Tests for annotation notes on a diagram: a block with a tone and none or several leader lines, each to a box, a
connection's line or a free point, with a start point, vertices, a line shape and a start and an end style.

Covers the layout save (stored, returned by the view, rules a leader must follow, several per note), a deleted target
removing its leader and keeping the note, the server SVG drawing the leader between the right points (and not drawing
one to a hidden box), the Mermaid export, the project bundle round trip (and an older bundle's single leader) and the
leader table's own constraints. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import re
import zipfile

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.modules.architecture.models import ArchitectureDiagramNote, ArchitectureNoteLeader
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
        {"text": "At a box", "tone": "info", "leaders": [{"kind": "element", "element_id": a["id"], "end_style": "none"}]},
        {"text": "At a line", "tone": "warning", "leaders": [{"kind": "connection", "connection_id": link["id"]}]},
        {"text": "At a spot", "tone": "danger", "leaders": [{
            "kind": "point", "x": 12.5, "y": -40, "start_point": "top", "points": [{"x": 5, "y": -20}, {"x": 9, "y": -30}],
            "line_shape": "spline", "start_style": "dot", "end_style": "arrow",
        }]},
        {"text": "Plain"},
    ]
    saved = _save(client, token, p, diagram, boxes, notes)
    assert saved["version"] == diagram["version"] + 1
    shown = view(client, token, p, diagram["id"])["notes"]
    assert [(n["tone"], [leader["kind"] for leader in n["leaders"]]) for n in shown] == [
        ("info", ["element"]), ("warning", ["connection"]), ("danger", ["point"]), ("neutral", []),
    ]
    box, line, spot = (n["leaders"][0] for n in shown[:3])
    assert (box["element_id"], box["start_style"], box["end_style"], box["start_point"]) == (a["id"], "none", "none", None)
    assert (line["connection_id"], line["end_style"], line["points"], line["line_shape"]) == (link["id"], "arrow", [], None)
    assert (spot["x"], spot["y"], spot["start_point"], spot["line_shape"]) == (12.5, -40, "top", "spline")
    assert spot["points"] == [{"x": 5, "y": -20}, {"x": 9, "y": -30}] and (spot["start_style"], spot["end_style"]) == ("dot", "arrow")
    assert spot["element_id"] is None and spot["connection_id"] is None and box["x"] is None


def test_a_note_can_have_several_leaders_in_order(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes several")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    leaders = [
        {"kind": "element", "element_id": b["id"]},
        {"kind": "element", "element_id": a["id"]},
        {"kind": "point", "x": 1, "y": 2},
    ]
    _save(client, token, p, diagram, boxes, [{"text": "Both", "leaders": leaders}])
    (note,) = view(client, token, p, diagram["id"])["notes"]
    assert [(leader["kind"], leader["element_id"]) for leader in note["leaders"]] == [("element", b["id"]), ("element", a["id"]), ("point", None)]
    too_many = [{"kind": "point", "x": i, "y": 0} for i in range(11)]
    _save(client, token, p, diagram, boxes, [{"text": "Many", "leaders": too_many}], expect=422)


def test_saving_the_same_notes_again_changes_nothing_and_a_changed_leader_is_updated_in_place(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes replace")
    p = project["id"]
    a, b, _link, diagram, boxes = _flow(client, token, p)
    saved = _save(client, token, p, diagram, boxes, [{"text": "Look", "leaders": [{"kind": "element", "element_id": a["id"]}]}])
    (stored,) = view(client, token, p, diagram["id"])["notes"]
    (leader,) = stored["leaders"]

    def note(**change):
        return {"text": "Look", "id": stored["id"], "leaders": [{**leader, **change}]}

    same = _save(client, token, p, saved, boxes, [note()])
    assert same["version"] == saved["version"]
    moved = _save(client, token, p, same, boxes, [note(element_id=b["id"], end_style="dot")])
    assert moved["version"] == saved["version"] + 1
    (after,) = view(client, token, p, diagram["id"])["notes"]
    assert after["id"] == stored["id"] and after["leaders"][0]["id"] == leader["id"]
    assert (after["leaders"][0]["element_id"], after["leaders"][0]["end_style"]) == (b["id"], "dot")
    bent = _save(client, token, p, moved, boxes, [note(element_id=b["id"], end_style="dot", points=[{"x": 3, "y": 4}], line_shape="spline")])
    assert bent["version"] == moved["version"] + 1
    cleared = _save(client, token, p, bent, boxes, [{"text": "Look", "id": stored["id"]}])
    (none,) = view(client, token, p, diagram["id"])["notes"]
    assert cleared["version"] == bent["version"] + 1 and none["leaders"] == []


def test_a_leader_must_name_exactly_the_target_of_its_kind(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes shape")
    p = project["id"]
    a, _b, link, diagram, boxes = _flow(client, token, p)
    for bad in (
        {"kind": "element"},
        {"kind": "connection"},
        {"kind": "point", "x": 1},
        {"kind": "element", "element_id": a["id"], "connection_id": link["id"]},
        {"kind": "none"},
        {"kind": "point", "x": 1, "y": 2, "element_id": a["id"]},
        {"kind": "point", "x": 1e12, "y": 0},
        {"kind": "point", "x": 1, "y": 0, "start_point": "middle"},
        {"kind": "point", "x": 1, "y": 0, "end_style": "square"},
        {"kind": "point", "x": 1, "y": 0, "points": [{"x": 1e12, "y": 0}]},
        {"kind": "point", "x": 1, "y": 0, "points": [{"x": i, "y": 0} for i in range(17)]},
    ):
        _save(client, token, p, diagram, boxes, [{"text": "x", "leaders": [bad]}], expect=422)
    _save(client, token, p, diagram, boxes, [{"text": "x", "tone": "purple"}], expect=422)
    assert view(client, token, p, diagram["id"])["notes"] == []


def test_a_new_leader_cannot_name_an_element_off_the_diagram_or_a_connection_of_another_project(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch notes scope")
    p = project["id"]
    a, _b, _link, diagram, boxes = _flow(client, token, p)
    off = make_element(client, token, p, "Not drawn")
    _save(client, token, p, diagram, boxes, [{"text": "x", "leaders": [{"kind": "element", "element_id": off["id"]}]}], expect=400)
    from tests.conftest import create_project

    other = create_project(client, token, org["id"], "Arch notes scope other")
    x, y = make_element(client, token, other["id"], "X"), make_element(client, token, other["id"], "Y")
    foreign = make_connection(client, token, other["id"], x["id"], y["id"])
    _save(
        client, token, p, diagram, boxes,
        [{"text": "x", "leaders": [{"kind": "connection", "connection_id": foreign["id"]}]}], expect=400,
    )
    missing = "00000000-0000-0000-0000-000000000000"
    _save(client, token, p, diagram, boxes, [{"text": "x", "leaders": [{"kind": "connection", "connection_id": missing}]}], expect=400)
    assert view(client, token, p, diagram["id"])["notes"] == []


def test_a_leader_id_must_be_the_notes_own_and_listed_once(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes leader ids")
    p = project["id"]
    a, _b, _link, diagram, boxes = _flow(client, token, p)
    saved = _save(client, token, p, diagram, boxes, [
        {"text": "One", "leaders": [{"kind": "element", "element_id": a["id"]}]},
        {"text": "Two", "leaders": [{"kind": "point", "x": 1, "y": 1}]},
    ])
    one, two = view(client, token, p, diagram["id"])["notes"]
    stolen = {**two["leaders"][0]}
    _save(client, token, p, saved, boxes, [{"text": "One", "id": one["id"], "leaders": [stolen]}], expect=400)
    mine = one["leaders"][0]
    _save(client, token, p, saved, boxes, [{"text": "One", "id": one["id"], "leaders": [mine, mine]}], expect=400)
    _save(client, token, p, saved, boxes, [{"text": "New", "leaders": [mine]}], expect=400)
    other_leader = {"kind": "point", "x": 1, "y": 1, "id": "00000000-0000-0000-0000-000000000000"}
    _save(client, token, p, saved, boxes, [{"text": "One", "id": one["id"], "leaders": [other_leader]}], expect=400)


def test_a_leader_to_an_element_taken_off_the_diagram_is_kept_and_not_rejected_on_the_next_save(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes unplaced")
    p = project["id"]
    a, b, _link, diagram, boxes = _flow(client, token, p)
    saved = _save(client, token, p, diagram, boxes, [{"text": "Look", "leaders": [{"kind": "element", "element_id": b["id"]}]}])
    (stored,) = view(client, token, p, diagram["id"])["notes"]
    only_a = [boxes[0]]
    kept_leader = stored["leaders"][0]
    again = _save(client, token, p, saved, only_a, [{"text": "Look", "id": stored["id"], "leaders": [kept_leader]}])
    (kept,) = view(client, token, p, diagram["id"])["notes"]
    assert again["version"] >= saved["version"] and kept["leaders"][0]["element_id"] == b["id"]
    # Placed again, the leader draws again: the SVG joins the note to the box.
    assert "data-note" in _svg(client, token, p, diagram["id"])


def test_deleting_the_target_removes_its_leader_and_keeps_the_note_and_its_other_leaders(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes deleted")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    spare = make_element(client, token, p, "Spare")
    diagram = place_all(client, token, p, diagram, spare["id"])
    boxes.append({"element_id": spare["id"], "x": 0, "y": 200})
    _save(client, token, p, diagram, boxes, [
        {"text": "To the spare", "leaders": [{"kind": "element", "element_id": spare["id"]}, {"kind": "point", "x": 9, "y": 9}]},
        {"text": "To the line", "leaders": [{"kind": "connection", "connection_id": link["id"]}]},
    ])
    for path in (f"elements/{spare['id']}", f"connections/{link['id']}"):
        resp = client.delete(f"{project_base(p)}/{path}", headers=auth_headers(token))
        assert resp.status_code in (200, 204), resp.text
    shown = view(client, token, p, diagram["id"])["notes"]
    assert [n["text"] for n in shown] == ["To the spare", "To the line"]
    assert [[leader["kind"] for leader in n["leaders"]] for n in shown] == [["point"], []]


def test_the_database_refuses_a_leader_row_that_does_not_match_its_kind(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes constraint")
    p = project["id"]
    a, _b, _link, diagram, boxes = _flow(client, token, p)
    _save(client, token, p, diagram, boxes, [{"text": "x", "leaders": [{"kind": "point", "x": 1, "y": 2}]}])
    refused = (
        "SET kind = 'point', x = NULL",
        "SET kind = 'element', element_id = NULL",
        "SET kind = 'element', connection_id = (SELECT id FROM architecture_connections LIMIT 1)",
        "SET kind = 'none'",
        "SET kind = 'bogus'",
        "SET start_style = 'square'",
        "SET end_style = 'bogus'",
        "SET x = 1, y = NULL",
        "SET element_id = :element",
    )
    with SessionLocal() as db:
        leader = db.scalars(select(ArchitectureNoteLeader)).first()
        assert leader is not None
        for change in refused:
            try:
                db.execute(
                    text(f"UPDATE architecture_note_leaders {change} WHERE id = :id"), {"id": leader.id, "element": a["id"]},
                )
                db.flush()
            except IntegrityError:
                db.rollback()
            else:
                db.rollback()
                raise AssertionError(f"accepted: {change}")
    # The note table has no leader column left to disagree with.
    with SessionLocal() as db:
        assert db.scalars(select(ArchitectureDiagramNote)).first() is not None


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
        [{"text": "Box", "tone": "success", "leaders": [{"kind": "element", "element_id": a["id"]}], **block}],
    )
    svg = _svg(client, token, p, diagram["id"])
    assert 'fill="#DCFCE7"' in svg and 'marker-end="url(#leader-arrow-success)"' in svg and 'id="leader-arrow-success"' in svg
    assert "marker-start" not in svg
    # The note sits below Alpha (x 0-160, y 0-80): its top middle (80, 200) meets Alpha's bottom middle (80, 80).
    assert _leader_line(svg) == (80.0, 200.0, 80.0, 80.0)

    saved = _save(client, token, p, saved, boxes, [
        {"text": "Line", "leaders": [{"kind": "connection", "connection_id": link["id"], "end_style": "none"}], **block},
    ])
    svg = _svg(client, token, p, diagram["id"])
    assert "marker-end=\"url(#leader-" not in svg
    x1, y1, x2, y2 = _leader_line(svg)
    assert (x2, y2) == (280.0, 40.0)  # the middle of the line from (160, 40) to (400, 40)
    assert (x1, y1) == (160.0, 200.0)  # the note's top right corner is nearest

    _save(client, token, p, saved, boxes, [{"text": "Spot", "leaders": [{"kind": "point", "x": 700, "y": 300}], **block}])
    x1, y1, x2, y2 = _leader_line(_svg(client, token, p, diagram["id"]))
    assert (x2, y2) == (700.0, 300.0) and (x1, y1) == (160.0, 260.0)


def test_the_svg_draws_a_chosen_start_point_vertices_a_curve_and_the_two_end_styles(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes svg routed")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    block = {"x": 0, "y": 200, "width": 160, "height": 60}
    straight = {
        "kind": "point", "x": 700, "y": 300, "start_point": "right", "points": [{"x": 300, "y": 230}, {"x": 500, "y": 300}],
        "start_style": "dot", "end_style": "arrow",
    }
    saved = _save(client, token, p, diagram, boxes, [{"text": "Routed", "tone": "info", "leaders": [straight], **block}])
    svg = _svg(client, token, p, diagram["id"])
    # From the note's right middle (160, 230) through both vertices to the point.
    assert '<path d="M 160 230 L 300 230 L 500 300 L 700 300" fill="none" stroke="#2563EB" stroke-width="1.5"' in svg
    assert 'marker-start="url(#leader-dot-info)"' in svg and 'marker-end="url(#leader-arrow-info)"' in svg
    assert 'id="leader-dot-info"' in svg and 'id="leader-arrow-info"' in svg
    _save(client, token, p, saved, boxes, [{"text": "Routed", "tone": "info", "leaders": [{**straight, "line_shape": "spline"}], **block}])
    assert re.search(r'<path d="M 160 230 C [^"]+" fill="none" stroke="#2563EB"', _svg(client, token, p, diagram["id"]))


def test_an_element_leader_with_vertices_ends_at_the_box_point_nearest_the_last_vertex(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes svg vertex")
    p = project["id"]
    a, b, _link, diagram, boxes = _flow(client, token, p)
    block = {"x": 0, "y": 200, "width": 160, "height": 60}
    leader = {"kind": "element", "element_id": b["id"], "points": [{"x": 500, "y": 200}], "end_style": "none"}
    _save(client, token, p, diagram, boxes, [{"text": "To Bravo", "leaders": [leader], **block}])
    svg = _svg(client, token, p, diagram["id"])
    # Bravo is x 400-560, y 0-80; its bottom middle (480, 80) is nearest the vertex (500, 200); the note's nearest point to the
    # vertex is its top right corner (160, 200).
    assert '<path d="M 160 200 L 500 200 L 480 80"' in svg


def test_a_note_with_no_tone_is_stored_and_survives_a_bundle_round_trip(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch notes none")
    p = project["id"]
    _a, _b, _link, diagram, boxes = _flow(client, token, p)
    _save(client, token, p, diagram, boxes, [{"text": "Label", "tone": "none"}, {"text": "Boxed", "tone": "neutral"}])
    assert [n["tone"] for n in view(client, token, p, diagram["id"])["notes"]] == ["none", "neutral"]

    exported = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch notes none copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    listing = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    shown = view(client, token, copy["id"], listing[0]["id"])["notes"]
    assert [(n["text"], n["tone"]) for n in shown] == [("Label", "none"), ("Boxed", "neutral")]


def test_the_svg_draws_a_note_with_no_tone_as_text_alone_and_skips_an_empty_one(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes none svg")
    p = project["id"]
    a, _b, _link, diagram, boxes = _flow(client, token, p)
    block = {"x": 0, "y": 200, "width": 160, "height": 60}
    _save(client, token, p, diagram, boxes, [
        {"text": "Plain label", "tone": "none", "leaders": [{"kind": "element", "element_id": a["id"]}], **block},
        {"text": "  ", "tone": "none", "x": 400, "y": 400, "width": 160, "height": 60},
        {"text": "", "tone": "neutral", "x": 700, "y": 400, "width": 160, "height": 60},
    ])
    svg = _svg(client, token, p, diagram["id"])
    groups = re.findall(r'<g data-note="[^"]+">(.*?)</g>', svg)
    # The text-only note has no rectangle; the empty note with no tone is skipped; an empty neutral note keeps its block.
    assert len(groups) == 2
    assert "<rect" not in groups[0] and "Plain label" in groups[0]
    assert "<rect" in groups[1]
    # The leader of a text-only note is still drawn, in the neutral line colour.
    assert _leader_line(svg) == (80.0, 200.0, 80.0, 80.0)
    assert 'stroke="#64748B"' in svg
    # The skipped note takes no room: the drawing ends at the empty neutral note (x 700 + 160), not at a note beyond it.
    assert "viewBox" in svg


def test_a_leader_to_a_box_a_switch_hides_is_not_drawn_and_a_hidden_box_never_appears_in_mermaid(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch notes hidden")
    p = project["id"]
    a, b, _link, diagram, boxes = _flow(client, token, p)
    saved = _save(
        client, token, p, diagram, boxes,
        [{"text": "Look here", "leaders": [{"kind": "element", "element_id": b["id"]}], "x": 0, "y": 200}],
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
        {"text": "Careful <b>\"x\"</b>", "leaders": [{"kind": "element", "element_id": a["id"]}]},
        {"text": "Open end", "leaders": [{"kind": "element", "element_id": b["id"], "end_style": "none"}]},
        {"text": "On the line", "leaders": [{"kind": "connection", "connection_id": link["id"]}]},
        {"text": "Both ends", "leaders": [{"kind": "element", "element_id": a["id"], "start_style": "arrow"}]},
        {"text": "Start only", "leaders": [{"kind": "element", "element_id": b["id"], "start_style": "arrow", "end_style": "none"}]},
        {"text": "Two", "leaders": [{"kind": "element", "element_id": a["id"]}, {"kind": "element", "element_id": b["id"]}]},
        {"text": "   "},
    ])
    out = client.get(f"{project_base(p)}/diagrams/{diagram['id']}/mermaid", headers=auth_headers(token)).text
    assert out.count(">\"") == 6 and "<b>" not in out and '"x"' not in out
    assert "t1 -.-> n1" in out and "t2 -.- n2" in out and "t3 -." not in out
    assert "t4 <-.-> n1" in out and "n2 -.-> t5" in out
    assert "t6 -.-> n1" in out and "t6 -.-> n2" in out


def test_notes_with_tone_and_leaders_round_trip_through_the_project_bundle(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch notes bundle")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    _save(client, token, p, diagram, boxes, [
        {"text": "Box", "tone": "info", "leaders": [
            {"kind": "element", "element_id": a["id"], "end_style": "none", "start_point": "left"},
            {"kind": "point", "x": 1, "y": 2},
        ]},
        {"text": "Line", "tone": "warning", "leaders": [{"kind": "connection", "connection_id": link["id"], "line_shape": "spline",
                                                         "points": [{"x": 3, "y": 4}]}]},
        {"text": "Spot", "leaders": [{"kind": "point", "x": 5, "y": 6, "start_style": "dot", "end_style": "dot"}]},
        {"text": "Plain"},
    ])
    resp = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    assert resp.status_code == 200
    exported = json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))
    entry_notes = exported["architecture_diagrams"][0]["notes"]
    box_leader, spot_leader = entry_notes[0]["leaders"]
    assert box_leader == {
        "kind": "element", "start_point": "left", "points": [], "line_shape": None, "start_style": "none", "end_style": "none",
        "element": {"code": a["unique_code"]},
    }
    assert spot_leader["kind"] == "point" and (spot_leader["x"], spot_leader["y"]) == (1.0, 2.0)
    line_leader = entry_notes[1]["leaders"][0]
    assert line_leader["connection_code"] == link["unique_code"] and line_leader["points"] == [{"x": 3.0, "y": 4.0}]
    assert entry_notes[1]["tone"] == "warning" and entry_notes[3]["leaders"] == []
    assert "leader" not in entry_notes[0]

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
    assert [(n["text"], n["tone"], [leader["kind"] for leader in n["leaders"]]) for n in notes] == [
        ("Box", "info", ["element", "point"]), ("Line", "warning", ["connection"]), ("Spot", "neutral", ["point"]),
        ("Plain", "neutral", []),
    ]
    first = notes[0]["leaders"][0]
    assert first["element_id"] == names[a["unique_code"]] and first["end_style"] == "none" and first["start_point"] == "left"
    routed = notes[1]["leaders"][0]
    assert routed["connection_id"] is not None and routed["line_shape"] == "spline" and routed["points"] == [{"x": 3, "y": 4}]
    spot = notes[2]["leaders"][0]
    assert (spot["x"], spot["y"], spot["start_style"], spot["end_style"]) == (5, 6, "dot", "dot")


def test_a_bundle_written_with_the_single_leader_of_a_note_is_still_read(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch notes bundle legacy")
    p = project["id"]
    a, _b, link, diagram, boxes = _flow(client, token, p)
    _save(client, token, p, diagram, boxes, [{"text": "Box"}, {"text": "Line"}, {"text": "Spot"}, {"text": "Plain"}])
    resp = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    source = zipfile.ZipFile(io.BytesIO(resp.content))
    data = json.loads(source.read("project.json"))
    notes = data["architecture_diagrams"][0]["notes"]
    for note in notes:
        del note["leaders"]
    notes[0]["leader"] = {"kind": "element", "arrow": False, "element": {"code": a["unique_code"]}}
    notes[1]["leader"] = {"kind": "connection", "arrow": True, "connection_code": link["unique_code"]}
    notes[2]["leader"] = {"kind": "point", "arrow": True, "x": 5.0, "y": 6.0}
    notes[3]["leader"] = {"kind": "none", "arrow": True}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item, json.dumps(data) if item.filename == "project.json" else source.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch notes bundle legacy copy"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    listing = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    shown = view(client, token, copy["id"], listing[0]["id"])["notes"]
    assert [[(leader["kind"], leader["end_style"], leader["start_style"]) for leader in n["leaders"]] for n in shown] == [
        [("element", "none", "none")], [("connection", "arrow", "none")], [("point", "arrow", "none")], [],
    ]


def test_an_import_drops_a_leader_it_cannot_resolve_and_keeps_the_note_and_its_other_leaders(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch notes bundle bad")
    p = project["id"]
    a, b, link, diagram, boxes = _flow(client, token, p)
    _save(client, token, p, diagram, boxes, [
        {"text": "Box", "leaders": [{"kind": "element", "element_id": a["id"]}, {"kind": "point", "x": 1, "y": 1}]},
        {"text": "Spot", "leaders": [{"kind": "point", "x": 5, "y": 6, "points": [{"x": 2, "y": 2}]}]},
    ])
    resp = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    source = zipfile.ZipFile(io.BytesIO(resp.content))
    data = json.loads(source.read("project.json"))
    notes = data["architecture_diagrams"][0]["notes"]
    notes[0]["leaders"][0]["element"] = {"code": "ELM-999"}
    notes[1]["leaders"][0]["x"] = "far"
    notes[1]["tone"] = "purple"
    notes[0]["leaders"][1].update(start_point="middle", end_style="square", points=[{"x": "a", "y": 1}, {"x": 7, "y": 8}])
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
    assert [(n["text"], [leader["kind"] for leader in n["leaders"]], n["tone"]) for n in shown] == [
        ("Box", ["point"], "neutral"), ("Spot", [], "neutral"),
    ]
    # An unknown start point reads as automatic, an unknown end style as an arrow and a bad vertex is left out.
    (kept,) = shown[0]["leaders"]
    assert (kept["start_point"], kept["end_style"], kept["points"]) == (None, "arrow", [{"x": 7, "y": 8}])
    assert sum("leader could not be restored" in w for w in imported.json().get("warnings", [])) == 2
