"""Tests for record comments on the architecture types (the generic comments API, `routers.record_comments`): ordinary
comments, pinned threads on a diagram (free spot, box, line), replies, resolve and reopen, edit and delete rights, anchor
validation, isolation between records and organisations, the module's own `/comments` routes and the audit events (ids,
never text). Every test builds its own organisation."""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.architecture.tests._helpers import (
    add_member,
    make_connection,
    make_diagram,
    make_element,
    place_all,
    project_base,
    setup,
)
from tests.conftest import auth_headers


def _base(project_id, artefact_type, record_id) -> str:
    return f"/api/v1/projects/{project_id}/artefacts/{artefact_type}/{record_id}"


def _post(client, token, base, body, *, expect=201):
    resp = client.post(f"{base}/comments", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _get(client, token, base) -> dict:
    resp = client.get(f"{base}/comments", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _world(client, admin_token, name):
    """A project with two placed elements, a connection between them and a diagram: the diagram's generic path."""
    org, project, token = setup(client, admin_token, name)
    p = project["id"]
    a = make_element(client, token, p, "Alpha")
    b = make_element(client, token, p, "Bravo")
    link = make_connection(client, token, p, a["id"], b["id"])
    diagram = place_all(client, token, p, make_diagram(client, token, p, "Flow"), a["id"], b["id"])
    return org, p, token, a, b, link, diagram, _base(p, "architecture_diagram", diagram["id"])


def test_an_ordinary_comment_is_listed_with_its_author_and_the_viewers_rights(client, admin_token):
    org, p, token, _a, _b, _link, _diagram, base = _world(client, admin_token, "Arch cmt plain")
    thread = _post(client, token, base, {"body": "  Needs a second look  "})
    (comment,) = thread["comments"]
    assert comment["body"] == "Needs a second look" and comment["pin_id"] is None
    assert comment["can_edit"] and comment["can_delete"] and comment["edited_at"] is None
    assert thread["pins"] == [] and thread["can_pin"] is True
    _uid, other = add_member(client, token, org["id"], p, "cmt.plain.o@example.com")
    seen = _get(client, other, base)["comments"][0]
    assert seen["author_display_name"] == comment["author_display_name"] and not seen["can_edit"] and not seen["can_delete"]


def test_a_blank_comment_is_refused(client, admin_token):
    _org, _p, token, *_rest, base = _world(client, admin_token, "Arch cmt blank")
    _post(client, token, base, {"body": "   "}, expect=422)


def test_a_pinned_thread_on_a_free_spot_a_box_and_a_line_with_replies(client, admin_token):
    _org, _p, token, a, _b, link, _diagram, base = _world(client, admin_token, "Arch cmt pins")
    spot = _post(client, token, base, {"body": "A gap here", "pin": {"anchor_kind": "none", "x": 10.5, "y": -3}})
    on_box = _post(client, token, base, {"body": "Box note", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 1, "y": 2}})
    on_line = _post(client, token, base, {"body": "Line note", "pin": {"anchor_kind": "edge", "anchor_key": link["id"], "x": 3, "y": 4}})
    assert [(p["anchor_kind"], p["comment_count"]) for p in on_line["pins"]] == [("none", 1), ("node", 1), ("edge", 1)]
    assert spot["pins"][0]["anchor_key"] is None and on_box["pins"][1]["anchor_key"] == a["id"]
    pin_id = on_line["pins"][0]["id"]
    replied = _post(client, token, base, {"body": "Agreed", "pin_id": pin_id})
    assert [c["body"] for c in replied["comments"] if c["pin_id"] == pin_id] == ["A gap here", "Agreed"]
    assert next(p for p in replied["pins"] if p["id"] == pin_id)["comment_count"] == 2


def test_a_pin_needs_a_valid_anchor(client, admin_token):
    _org, p, token, a, _b, link, _diagram, base = _world(client, admin_token, "Arch cmt anchors")
    stranger = make_element(client, token, p, "Not placed")
    cases = [
        {"anchor_kind": "node", "anchor_key": stranger["id"], "x": 0, "y": 0},   # not on this diagram
        {"anchor_kind": "node", "anchor_key": "not-a-uuid", "x": 0, "y": 0},
        {"anchor_kind": "node", "x": 0, "y": 0},                                # a box without its key
        {"anchor_kind": "none", "anchor_key": a["id"], "x": 0, "y": 0},         # a free spot with a key
        {"anchor_kind": "edge", "anchor_key": a["id"], "x": 0, "y": 0},         # an element is not a line
        {"anchor_kind": "node", "anchor_key": link["id"], "x": 0, "y": 0},      # a connection is not a box
    ]
    for pin in cases:
        _post(client, token, base, {"body": "x", "pin": pin}, expect=422)
    assert _get(client, token, base)["comments"] == []


def test_an_element_takes_ordinary_comments_but_no_pins(client, admin_token):
    _org, p, token, a, *_rest = _world(client, admin_token, "Arch cmt element")
    element_base = _base(p, "architecture_element", a["id"])
    thread = _post(client, token, element_base, {"body": "About the box"})
    assert thread["can_pin"] is False and len(thread["comments"]) == 1
    _post(client, token, element_base, {"body": "x", "pin": {"anchor_kind": "none", "x": 0, "y": 0}}, expect=422)


def test_resolve_reopen_move_and_the_rights_around_them(client, admin_token):
    org, p, token, a, b, _link, _diagram, base = _world(client, admin_token, "Arch cmt resolve")
    thread = _post(client, token, base, {"body": "Open", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 1, "y": 1}})
    pin_id = thread["pins"][0]["id"]
    _uid, other = add_member(client, token, org["id"], p, "cmt.resolve.o@example.com")

    resolved = client.patch(f"{base}/comment-pins/{pin_id}", json={"resolved": True}, headers=auth_headers(other))
    assert resolved.status_code == 200, resolved.text
    pin = resolved.json()["pins"][0]
    assert pin["resolved"] is True and pin["resolved_at"] is not None and pin["resolved_by_display_name"]
    assert not pin["can_move"]

    refused = client.patch(
        f"{base}/comment-pins/{pin_id}", json={"pin": {"anchor_kind": "none", "x": 9, "y": 9}}, headers=auth_headers(other),
    )
    assert refused.status_code == 403

    moved = client.patch(
        f"{base}/comment-pins/{pin_id}",
        json={"pin": {"anchor_kind": "node", "anchor_key": b["id"], "x": 50, "y": 60}, "resolved": False},
        headers=auth_headers(token),
    )
    pin = moved.json()["pins"][0]
    assert (pin["anchor_key"], pin["x"], pin["y"], pin["resolved"]) == (b["id"], 50, 60, False)


def test_only_the_author_edits_and_the_author_or_a_manager_deletes(client, admin_token):
    org, p, token, _a, _b, _link, _diagram, base = _world(client, admin_token, "Arch cmt rights")
    _uid, other = add_member(client, token, org["id"], p, "cmt.rights.o@example.com")
    mine = _post(client, token, base, {"body": "Mine"})["comments"][0]["id"]
    theirs = _post(client, other, base, {"body": "Theirs"})["comments"][1]["id"]

    assert client.patch(f"{base}/comments/{mine}", json={"body": "Hijack"}, headers=auth_headers(other)).status_code == 403
    edited = client.patch(f"{base}/comments/{mine}", json={"body": "Mine, edited"}, headers=auth_headers(token)).json()
    assert next(c for c in edited["comments"] if c["id"] == mine)["edited_at"] is not None
    assert client.delete(f"{base}/comments/{mine}", headers=auth_headers(other)).status_code == 403
    # The organisation admin holds manage on the type through the architect role of the project's creator.
    assert client.delete(f"{base}/comments/{theirs}", headers=auth_headers(token)).status_code == 200
    assert [c["body"] for c in _get(client, token, base)["comments"]] == ["Mine, edited"]


def test_deleting_the_last_comment_removes_the_thread_and_a_thread_can_be_deleted_whole(client, admin_token):
    _org, _p, token, a, _b, _link, _diagram, base = _world(client, admin_token, "Arch cmt delete")
    first = _post(client, token, base, {"body": "Only", "pin": {"anchor_kind": "none", "x": 0, "y": 0}})
    only = first["comments"][0]["id"]
    after = client.delete(f"{base}/comments/{only}", headers=auth_headers(token)).json()
    assert after["comments"] == [] and after["pins"] == []

    thread = _post(client, token, base, {"body": "One", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 0, "y": 0}})
    pin_id = thread["pins"][0]["id"]
    _post(client, token, base, {"body": "Two", "pin_id": pin_id})
    gone = client.delete(f"{base}/comment-pins/{pin_id}", headers=auth_headers(token)).json()
    assert gone["comments"] == [] and gone["pins"] == []


def test_an_ordinary_comment_can_be_placed_on_the_drawing_later_once(client, admin_token):
    _org, _p, token, a, _b, _link, _diagram, base = _world(client, admin_token, "Arch cmt late pin")
    cid = _post(client, token, base, {"body": "Written on the page"})["comments"][0]["id"]
    pinned = client.post(
        f"{base}/comments/{cid}/pin", json={"pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 5, "y": 6}},
        headers=auth_headers(token),
    )
    assert pinned.status_code == 200, pinned.text
    body = pinned.json()
    assert body["comments"][0]["pin_id"] == body["pins"][0]["id"] and body["pins"][0]["comment_count"] == 1
    again = client.post(
        f"{base}/comments/{cid}/pin", json={"pin": {"anchor_kind": "none", "x": 0, "y": 0}}, headers=auth_headers(token),
    )
    assert again.status_code == 422


def test_comments_stay_with_their_record_and_their_organisation(client, admin_token):
    _org, p, token, a, _b, _link, diagram, base = _world(client, admin_token, "Arch cmt iso one")
    other_diagram = make_diagram(client, token, p, "Second")
    thread = _post(client, token, base, {"body": "Here", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 0, "y": 0}})
    comment_id, pin_id = thread["comments"][0]["id"], thread["pins"][0]["id"]
    other_base = _base(p, "architecture_diagram", other_diagram["id"])
    assert _get(client, token, other_base)["comments"] == []
    assert client.patch(f"{other_base}/comments/{comment_id}", json={"body": "x"}, headers=auth_headers(token)).status_code == 404
    assert client.patch(f"{other_base}/comment-pins/{pin_id}", json={"resolved": True}, headers=auth_headers(token)).status_code == 404

    _o2, p2, token2, *_ = _world(client, admin_token, "Arch cmt iso two")
    assert client.get(f"{base}/comments".replace(p, p2), headers=auth_headers(token2)).status_code == 404
    foreign = client.get(f"{base}/comments", headers=auth_headers(token2))
    assert foreign.status_code in (403, 404)


def test_an_unknown_type_and_a_type_with_its_own_comments_answer_404(client, admin_token):
    _org, p, token, a, *_rest = _world(client, admin_token, "Arch cmt types")
    for artefact_type in ("nonsense", "requirement", "architecture_symbol"):
        resp = client.get(f"/api/v1/projects/{p}/artefacts/{artefact_type}/{a['id']}/comments", headers=auth_headers(token))
        assert resp.status_code == 404, artefact_type


def test_the_modules_own_routes_read_and_write_the_same_thread(client, admin_token):
    _org, p, token, a, _b, _link, diagram, base = _world(client, admin_token, "Arch cmt routes")
    own = f"{project_base(p)}/diagrams/{diagram['id']}/comments"
    resp = client.post(own, json={"body": "Via the module path"}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    assert [c["body"] for c in _get(client, token, base)["comments"]] == ["Via the module path"]
    assert [c["body"] for c in client.get(own, headers=auth_headers(token)).json()["comments"]] == ["Via the module path"]
    element_own = f"{project_base(p)}/elements/{a['id']}/comments"
    assert client.post(element_own, json={"body": "On a box"}, headers=auth_headers(token)).status_code == 201
    assert client.get(f"{project_base(p)}/connections/{a['id']}/comments", headers=auth_headers(token)).status_code == 404


def test_every_mutation_is_audited_by_id_and_never_by_text(client, admin_token):
    _org, _p, token, a, _b, _link, diagram, base = _world(client, admin_token, "Arch cmt audit")
    secret = "the launch code is 12345"
    thread = _post(client, token, base, {"body": secret, "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 0, "y": 0}})
    cid, pin_id = thread["comments"][0]["id"], thread["pins"][0]["id"]
    client.patch(f"{base}/comments/{cid}", json={"body": secret + " changed"}, headers=auth_headers(token))
    client.patch(f"{base}/comment-pins/{pin_id}", json={"resolved": True}, headers=auth_headers(token))
    client.patch(f"{base}/comment-pins/{pin_id}", json={"resolved": False}, headers=auth_headers(token))
    client.delete(f"{base}/comment-pins/{pin_id}", headers=auth_headers(token))
    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "architecture_diagram", AuditEvent.entity_id == diagram["id"])
            .order_by(AuditEvent.created_at)
        ).all()
        actions = [e.action for e in events]
        for wanted in ("comment_added", "comment_edited", "comment_thread_resolved", "comment_thread_reopened", "comment_thread_deleted"):
            assert wanted in actions, actions
        assert all("12345" not in str(e.detail) for e in events)


def test_the_comment_limit_and_length_are_enforced(client, admin_token):
    _org, _p, token, *_rest, base = _world(client, admin_token, "Arch cmt limits")
    _post(client, token, base, {"body": "x" * 5001}, expect=422)
    _post(client, token, base, {"body": "x" * 5000})


# --- bundles, template, search, anchored threads, deletion ------------------------------------------------------


def _export(client, token, project_id):
    import io
    import json
    import zipfile

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


def test_comments_and_pins_round_trip_through_the_project_bundle(client, admin_token):
    org, p, token, a, _b, link, diagram, base = _world(client, admin_token, "Arch cmt bundle")
    on_box = _post(client, token, base, {"body": "On the box", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 11, "y": 12}})
    pin_id = on_box["pins"][0]["id"]
    _post(client, token, base, {"body": "A reply", "pin_id": pin_id})
    _post(client, token, base, {"body": "On the line", "pin": {"anchor_kind": "edge", "anchor_key": link["id"], "x": 1, "y": 2}})
    _post(client, token, base, {"body": "Free spot", "pin": {"anchor_kind": "none", "x": -4, "y": 8}})
    client.patch(f"{base}/comment-pins/{pin_id}", json={"resolved": True}, headers=auth_headers(token))
    _post(client, token, base, {"body": "Ordinary"})
    element_base = _base(p, "architecture_element", a["id"])
    _post(client, token, element_base, {"body": "About Alpha"})

    content, bundle = _export(client, token, p)
    (entry,) = bundle["architecture_diagrams"]
    assert len(entry["comments"]) == 5 and len(entry["comment_pins"]) == 3
    anchors = sorted((pin["anchor"] or {}).get("kind", "none") for pin in entry["comment_pins"])
    assert anchors == ["edge", "node", "none"]
    assert all("id" not in pin for pin in entry["comment_pins"])  # portable refs, never ids
    assert any(pin["resolved_at"] for pin in entry["comment_pins"])

    copy = _import(client, token, org["id"], content, "Arch cmt bundle copy")["project"]
    diagrams = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    new_base = _base(copy["id"], "architecture_diagram", diagrams[0]["id"])
    thread = _get(client, token, new_base)
    assert [c["body"] for c in thread["comments"] if c["pin_id"] is None] == ["Ordinary"]
    kinds = sorted(pin["anchor_kind"] for pin in thread["pins"])
    assert kinds == ["edge", "node", "none"]
    boxed = next(pin for pin in thread["pins"] if pin["anchor_kind"] == "node")
    assert boxed["resolved"] is True and boxed["comment_count"] == 2 and (boxed["x"], boxed["y"]) == (11, 12)
    assert boxed["anchor_key"] != a["id"]  # the new project's own element
    elements = client.get(f"{project_base(copy['id'])}/elements", headers=auth_headers(token)).json()
    alpha = next(e for e in elements if e["name"] == "Alpha")
    assert boxed["anchor_key"] == alpha["id"]
    assert [c["body"] for c in _get(client, token, _base(copy["id"], "architecture_element", alpha["id"]))["comments"]] == ["About Alpha"]


def test_a_pin_whose_box_is_missing_from_the_bundle_comes_back_as_a_free_marker(client, admin_token):
    org, p, token, a, _b, _link, _diagram, base = _world(client, admin_token, "Arch cmt degrade")
    _post(client, token, base, {"body": "On the box", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 5, "y": 6}})
    content, bundle = _export(client, token, p)
    import io
    import json
    import zipfile

    bundle["architecture_diagrams"][0]["comment_pins"][0]["anchor"]["code"] = "ELM-404"
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item, json.dumps(bundle) if item.filename == "project.json" else source.read(item.filename))
    copy = _import(client, token, org["id"], out.getvalue(), "Arch cmt degrade copy")["project"]
    diagrams = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    (pin,) = _get(client, token, _base(copy["id"], "architecture_diagram", diagrams[0]["id"]))["pins"]
    assert (pin["anchor_kind"], pin["anchor_key"], pin["x"], pin["y"]) == ("none", None, 5, 6)


def test_a_template_copies_no_comments():
    from app.modules.architecture.export import reset_for_template

    data = {
        "architecture_elements": [{"unique_code": "ELM-001", "status": "active", "comments": [{"body": "x"}], "comment_pins": []}],
        "architecture_connections": [],
        "architecture_diagrams": [{
            "unique_code": "DGM-001", "name": "D", "status": "active", "boxes": [], "notes": [], "toggles": [],
            "comments": [{"body": "x"}], "comment_pins": [{"ref": "p1"}],
        }],
        "architecture_links": [], "architecture_collections": [],
    }
    reset_for_template(data)
    for row in (*data["architecture_elements"], *data["architecture_diagrams"]):
        assert "comments" not in row and "comment_pins" not in row


def test_comment_text_is_searched_only_when_asked_for(client, admin_token):
    _org, p, token, _a, _b, _link, diagram, base = _world(client, admin_token, "Arch cmt search")
    _post(client, token, base, {"body": "needle about archcommentzq"})
    h = auth_headers(token)
    plain = client.post("/api/v1/search", json={"q": "archcommentzq", "scope": "all", "fields": ["id", "title"]}, headers=h).json()
    assert plain["hits"] == []
    asked = client.post(
        "/api/v1/search", json={"q": "archcommentzq", "scope": "all", "fields": ["id", "title", "comments"]}, headers=h,
    ).json()
    assert [hit["id"] for hit in asked["hits"]] == [diagram["id"]]
    assert asked["hits"][0]["snippet"]["field_key"] == "comments"


def test_a_box_and_a_line_list_the_threads_pinned_to_them_across_diagrams(client, admin_token):
    _org, p, token, a, b, link, diagram, base = _world(client, admin_token, "Arch cmt anchored")
    second = place_all(client, token, p, make_diagram(client, token, p, "Second"), a["id"], b["id"])
    second_base = _base(p, "architecture_diagram", second["id"])
    _post(client, token, base, {"body": "On Alpha here", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 0, "y": 0}})
    _post(client, token, second_base, {"body": "On Alpha there", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 0, "y": 0}})
    _post(client, token, base, {"body": "On Bravo", "pin": {"anchor_kind": "node", "anchor_key": b["id"], "x": 0, "y": 0}})
    _post(client, token, base, {"body": "On the line", "pin": {"anchor_kind": "edge", "anchor_key": link["id"], "x": 0, "y": 0}})
    _post(client, token, base, {"body": "Free", "pin": {"anchor_kind": "none", "x": 0, "y": 0}})

    def threads(artefact_type, record_id):
        resp = client.get(f"{_base(p, artefact_type, record_id)}/anchored-comments", headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        return resp.json()["threads"]

    alpha = threads("architecture_element", a["id"])
    assert sorted(t["comments"][0]["body"] for t in alpha) == ["On Alpha here", "On Alpha there"]
    assert {t["record_id"] for t in alpha} == {diagram["id"], second["id"]}
    assert all(t["record_label"].startswith("DGM-") and not t["comments"][0]["can_edit"] for t in alpha)
    assert [t["comments"][0]["body"] for t in threads("architecture_connection", link["id"])] == ["On the line"]
    assert threads("architecture_diagram", diagram["id"]) == []


def test_a_member_who_cannot_open_the_diagram_sees_none_of_its_threads(client, admin_token):
    org, p, token, a, _b, _link, _diagram, base = _world(client, admin_token, "Arch cmt hidden")
    _post(client, token, base, {"body": "Private note", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 0, "y": 0}})
    from tests.conftest import create_org_user, login

    create_org_user(client, token, org["id"], "cmt.hidden.o@example.com")
    outsider_token = login(client, "cmt.hidden.o@example.com", "Password123!")
    resp = client.get(f"{_base(p, 'architecture_element', a['id'])}/anchored-comments", headers=auth_headers(outsider_token))
    assert resp.status_code in (403, 404)


def test_deleting_a_record_removes_its_comments_and_pins(client, admin_token):
    from app.models.record_comment import RecordComment, RecordCommentPin

    _org, p, token, a, _b, _link, diagram, base = _world(client, admin_token, "Arch cmt forget")
    _post(client, token, base, {"body": "Gone soon", "pin": {"anchor_kind": "node", "anchor_key": a["id"], "x": 0, "y": 0}})
    _post(client, token, base, {"body": "Ordinary too"})
    deleted = client.delete(f"{project_base(p)}/diagrams/{diagram['id']}", headers=auth_headers(token))
    assert deleted.status_code in (200, 204), deleted.text
    with SessionLocal() as db:
        assert db.scalars(select(RecordComment).where(RecordComment.record_id == diagram["id"])).all() == []
        assert db.scalars(select(RecordCommentPin).where(RecordCommentPin.record_id == diagram["id"])).all() == []


def test_a_module_that_is_switched_off_answers_404(client, admin_token):
    org, p, token, _a, _b, _link, _diagram, base = _world(client, admin_token, "Arch cmt off")
    from app.modules.architecture.tests._helpers import MODULE_KEY

    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}", json={"enabled": False}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert client.get(f"{base}/comments", headers=auth_headers(token)).status_code == 404


def test_comments_on_an_element_another_owner_shares_follow_the_visibility_rule(client, admin_token):
    from app.modules.architecture.tests._helpers import grant, make_collection, make_org_element, org_base
    from tests.conftest import create_project

    org, p, token, *_rest = _world(client, admin_token, "Arch cmt shared")
    consumer = create_project(client, token, org["id"], "Arch cmt shared consumer")
    _uid, member = add_member(client, token, org["id"], consumer["id"], "cmt.shared.m@example.com")
    platform = make_org_element(client, token, org["id"], "Platform")
    path = f"/api/v1/projects/{consumer['id']}/artefacts/architecture_element/{platform['id']}/comments"

    # Not in a granted collection: indistinguishable from a missing element, for reading and writing.
    assert client.get(path, headers=auth_headers(member)).status_code == 404
    assert client.post(path, json={"body": "Can I see this?"}, headers=auth_headers(member)).status_code == 404

    collection = make_collection(client, token, org_base(org["id"]), "Shared platform", members=[platform["id"]])
    grant(client, token, org_base(org["id"]), collection["id"], project_id=consumer["id"])
    posted = client.post(path, json={"body": "Now I can."}, headers=auth_headers(member))
    assert posted.status_code == 201, posted.text
    # The comment belongs to the organisation-owned record, not to the consumer project.
    from app.models.record_comment import RecordComment

    with SessionLocal() as db:
        row = db.scalars(select(RecordComment).where(RecordComment.record_id == platform["id"])).one()
        assert row.project_id is None and str(row.organization_id) == org["id"]

    # Revoking the grant hides the thread again.
    revoked = client.delete(f"{org_base(org['id'])}/collections/{collection['id']}", headers=auth_headers(token))
    assert revoked.status_code == 204
    assert client.get(path, headers=auth_headers(member)).status_code == 404


def test_comments_on_an_organisation_element_travel_in_the_organisation_bundle(client, admin_token):
    import io
    import json
    import uuid
    import zipfile

    from app.models.record_comment import RecordComment
    from app.modules.architecture.models import ArchitectureElement
    from app.modules.architecture.tests._helpers import grant, make_collection, make_org_element, org_base

    org, p, token, *_rest = _world(client, admin_token, "Arch cmt orgbundle")
    platform = make_org_element(client, token, org["id"], "Platform", activate=True)
    collection = make_collection(client, token, org_base(org["id"]), "Org infra", members=[platform["id"]])
    grant(client, token, org_base(org["id"]), collection["id"], project_id=p)
    path = f"/api/v1/projects/{p}/artefacts/architecture_element/{platform['id']}/comments"
    assert client.post(path, json={"body": "Org-level review note"}, headers=auth_headers(token)).status_code == 201

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert export.status_code == 200, export.text
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))
    (entry,) = org_json["architecture_org_elements"]
    assert [c["body"] for c in entry["comments"]] == ["Org-level review note"] and entry["comment_pins"] == []

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Arch cmt orgbundle copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org = uuid.UUID(imported.json()["organization"]["id"])
    with SessionLocal() as db:
        element = db.scalars(select(ArchitectureElement).where(ArchitectureElement.organization_id == new_org)).one()
        row = db.scalars(select(RecordComment).where(RecordComment.record_id == element.id)).one()
        assert (row.body, row.project_id, row.organization_id) == ("Org-level review note", None, new_org)
