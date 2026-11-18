"""Tests for the links between a layer and the layer above it: boundary boxes in a scoped diagram and the "realises"
link between connections.

Covers the realisation rules (ends inside one end of the outer connection, no cycle, same project, open connections),
their removal when an edit makes them invalid, the layout save of boundary boxes (new boxes must be outer connections of
the scope, stale boxes are kept, a scope change clears them), the resolved view (a box with its shape and coverage, a line
to it, a locked box), the model endpoint, the server SVG and Mermaid drawings, the permission and the project bundle
round trip. Every test builds its own organisation.
"""

from __future__ import annotations

import io
import json
import zipfile

from app.modules.architecture.tests._helpers import (
    connection_types,
    make_connection,
    make_diagram,
    make_element,
    project_base,
    put_element,
    setup,
    view,
)
from tests.conftest import auth_headers


def _build(client, token, project_id, *, type_name="REST API"):
    """A scope element with two inner elements and one element outside it, an outer connection (scope to outside) and
    a diagram of the scope: `(scope, a, b, outside, outer, diagram)`."""
    scope = make_element(client, token, project_id, "Scope")
    a = make_element(client, token, project_id, "Inner A", parent_id=scope["id"])
    b = make_element(client, token, project_id, "Inner B", parent_id=scope["id"])
    outside = make_element(client, token, project_id, "Outside")
    outer = make_connection(client, token, project_id, scope["id"], outside["id"], type_name=type_name)
    diagram = make_diagram(client, token, project_id, "Inside", scope_element_id=scope["id"])
    return scope, a, b, outside, outer, diagram


def _realise(client, token, project_id, inner, outer_ids, *, expect=200):
    resp = client.put(
        f"{project_base(project_id)}/connections/{inner['id']}/realisations",
        json={"version": inner["version"], "outer_connection_ids": outer_ids}, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _layout(client, token, project_id, diagram, placements, boundaries=None, *, expect=200):
    body: dict = {"version": diagram["version"], "placements": placements}
    if boundaries is not None:
        body["boundaries"] = boundaries
    resp = client.put(f"{project_base(project_id)}/diagrams/{diagram['id']}/layout", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _boxes(*elements):
    return [{"element_id": e["id"], "x": i * 200, "y": 0} for i, e in enumerate(elements)]


def _box(outer, x=-240, y=0):
    return {"connection_id": outer["id"], "x": x, "y": y}


def _get_connection(client, token, project_id, connection):
    resp = client.get(f"{project_base(project_id)}/connections/{connection['id']}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Realisations -------------------------------------------------------------------------------------------------


def test_a_connection_ending_at_the_outer_end_realises_it_and_both_pages_show_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise basic")
    scope, a, _b, _outside, outer, _diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    updated = _realise(client, token, project["id"], inner, [outer["id"]])
    assert updated["version"] == inner["version"] + 1
    assert [r["unique_code"] for r in updated["realises"]] == [outer["unique_code"]]
    shown = _get_connection(client, token, project["id"], outer)
    assert [r["unique_code"] for r in shown["realised_by"]] == [inner["unique_code"]]


def test_a_connection_wholly_inside_the_outer_end_realises_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise inside")
    _scope, a, b, _outside, outer, _diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], b["id"])
    assert len(_realise(client, token, project["id"], inner, [outer["id"]])["realises"]) == 1


def test_a_connection_outside_the_outer_connection_cannot_realise_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise outside")
    _scope, _a, _b, outside, outer, _diagram = _build(client, token, project["id"])
    other = make_element(client, token, project["id"], "Other")
    stranger = make_connection(client, token, project["id"], other["id"], outside["id"])
    refusal = _realise(client, token, project["id"], stranger, [outer["id"]], expect=400)
    assert "interface" in refusal["detail"]


def test_a_connection_between_parts_of_the_two_ends_realises_the_outer_one(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise refine")
    scope, a, _b, outside, outer, _diagram = _build(client, token, project["id"])
    far = make_element(client, token, project["id"], "Far", parent_id=outside["id"])
    refined = make_connection(client, token, project["id"], a["id"], far["id"])
    assert len(_realise(client, token, project["id"], refined, [outer["id"]])["realises"]) == 1
    crosswise = make_connection(client, token, project["id"], far["id"], a["id"])
    assert len(_realise(client, token, project["id"], crosswise, [outer["id"]])["realises"]) == 1
    assert scope


def test_a_connection_cannot_realise_itself_and_a_cycle_is_refused(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise cycle")
    a = make_element(client, token, project["id"], "Alpha")
    b = make_element(client, token, project["id"], "Bravo")
    first = make_connection(client, token, project["id"], a["id"], b["id"])
    second = make_connection(client, token, project["id"], a["id"], b["id"])
    _realise(client, token, project["id"], first, [first["id"]], expect=400)
    first = _realise(client, token, project["id"], first, [second["id"]])
    refusal = _realise(client, token, project["id"], second, [first["id"]], expect=400)
    assert "realises it" in refusal["detail"]


def test_setting_the_list_again_replaces_it_and_an_unchanged_list_keeps_the_version(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise replace")
    scope, a, _b, _outside, outer, _diagram = _build(client, token, project["id"])
    other = make_element(client, token, project["id"], "Other")
    second = make_connection(client, token, project["id"], scope["id"], other["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    inner = _realise(client, token, project["id"], inner, [outer["id"], second["id"], outer["id"]])
    assert len(inner["realises"]) == 2
    same = _realise(client, token, project["id"], inner, [second["id"], outer["id"]])
    assert same["version"] == inner["version"]
    inner = _realise(client, token, project["id"], inner, [second["id"]])
    assert [r["unique_code"] for r in inner["realises"]] == [second["unique_code"]]
    assert _get_connection(client, token, project["id"], outer)["realised_by"] == []


def test_a_stale_version_is_refused(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise stale")
    scope, a, _b, _outside, outer, _diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    _realise(client, token, project["id"], inner, [outer["id"]])
    _realise(client, token, project["id"], inner, [], expect=409)


def test_an_archived_or_another_projects_connection_cannot_be_realised(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch realise archived")
    scope, a, _b, _outside, outer, _diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    archived = client.post(f"{project_base(project['id'])}/connections/{outer['id']}/archive", headers=auth_headers(token))
    assert archived.status_code == 200
    _realise(client, token, project["id"], inner, [outer["id"]], expect=400)
    _realise(client, token, project["id"], inner, ["00000000-0000-0000-0000-000000000001"], expect=400)


def test_editing_an_end_so_the_rule_fails_removes_the_realisation(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise edit")
    scope, a, _b, outside, outer, _diagram = _build(client, token, project["id"])
    other = make_element(client, token, project["id"], "Other")
    inner = _realise(client, token, project["id"], make_connection(client, token, project["id"], a["id"], scope["id"]), [outer["id"]])
    resp = client.put(
        f"{project_base(project['id'])}/connections/{inner['id']}",
        json={"version": inner["version"], "source_element_id": other["id"], "target_element_id": outside["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert _get_connection(client, token, project["id"], inner)["realises"] == []


def test_moving_an_element_out_of_the_outer_end_removes_the_realisation(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise move")
    _scope, a, b, _outside, outer, _diagram = _build(client, token, project["id"])
    inner = _realise(client, token, project["id"], make_connection(client, token, project["id"], a["id"], b["id"]), [outer["id"]])
    put_element(client, token, project["id"], a, parent_id=None)
    assert _get_connection(client, token, project["id"], inner)["realises"] == []


def test_deleting_a_connection_removes_its_realisations(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch realise delete")
    scope, a, _b, _outside, outer, _diagram = _build(client, token, project["id"])
    inner = _realise(client, token, project["id"], make_connection(client, token, project["id"], a["id"], scope["id"]), [outer["id"]])
    assert client.delete(f"{project_base(project['id'])}/connections/{inner['id']}", headers=auth_headers(token)).status_code == 204
    assert _get_connection(client, token, project["id"], outer)["realised_by"] == []


def test_a_member_without_the_architect_role_cannot_set_realisations(client, admin_token):
    from app.modules.architecture.tests._helpers import add_member

    org, project, token = setup(client, admin_token, "Arch realise role")
    scope, a, _b, _outside, outer, _diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    _user, member = add_member(client, token, org["id"], project["id"], "member-realise@example.com")
    _realise(client, member, project["id"], inner, [outer["id"]], expect=403)


# --- Boundary boxes in the layout save ---------------------------------------------------------------------------


def test_a_boundary_box_is_stored_and_drawn_with_its_shape_and_coverage(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary store")
    scope, a, b, outside, outer, diagram = _build(client, token, project["id"])
    saved = _layout(client, token, project["id"], diagram, _boxes(a, b), [_box(outer)])
    assert saved["version"] == diagram["version"] + 1
    (box,) = view(client, token, project["id"], diagram["id"])["boundaries"]
    assert (box["connection_id"], box["shape"], box["covered"], box["locked"]) == (outer["id"], "output", False, False)
    assert (box["outside_element_code"], box["outside_element_name"], box["scope_end_element_id"]) == (
        outside["unique_code"], "Outside", scope["id"],
    )
    assert (box["x"], box["width"]) == (-240, 120)


def test_the_shape_follows_the_direction_of_the_outer_connection(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary shapes")
    scope = make_element(client, token, project["id"], "Scope")
    a = make_element(client, token, project["id"], "Inner", parent_id=scope["id"])
    outside = make_element(client, token, project["id"], "Outside")
    incoming = make_connection(client, token, project["id"], outside["id"], scope["id"])
    # An inner element's own connection to the outside is outer for the scope too (a descendant is inside the scope).
    two_way_type = next(n for n in connection_types(client, token, project["id"]) if n in ("Ethernet", "USB", "I2C"))
    two_way = make_connection(client, token, project["id"], a["id"], outside["id"], type_name=two_way_type)
    diagram = make_diagram(client, token, project["id"], "Inside", scope_element_id=scope["id"])
    _layout(client, token, project["id"], diagram, _boxes(a), [_box(incoming), _box(two_way, y=100)])
    shapes = {b["connection_id"]: b["shape"] for b in view(client, token, project["id"], diagram["id"])["boundaries"]}
    assert shapes[incoming["id"]] == "input"
    assert shapes[two_way["id"]] in ("bidirectional", "output")


def test_a_new_box_must_be_an_outer_connection_of_the_scope(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary refuse")
    scope, a, b, outside, outer, diagram = _build(client, token, project["id"])
    inside = make_connection(client, token, project["id"], a["id"], b["id"])
    unrelated = make_connection(client, token, project["id"], outside["id"], make_element(client, token, project["id"], "Far")["id"])
    for bad in (inside, unrelated):
        _layout(client, token, project["id"], diagram, _boxes(a), [_box(bad)], expect=400)
    _layout(client, token, project["id"], diagram, _boxes(a), [_box(outer), _box(outer, x=0)], expect=400)
    _layout(client, token, project["id"], diagram, _boxes(a), [_box(outer)])
    assert scope  # the scope exists


def test_a_diagram_without_a_scope_takes_no_boundary_boxes(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary context")
    _scope, a, _b, _outside, outer, _diagram = _build(client, token, project["id"])
    context = make_diagram(client, token, project["id"], "Context")
    _layout(client, token, project["id"], context, _boxes(a), [_box(outer)], expect=400)


def test_leaving_the_boundaries_out_keeps_them_and_an_empty_list_clears_them(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary keep")
    _scope, a, b, _outside, outer, diagram = _build(client, token, project["id"])
    saved = _layout(client, token, project["id"], diagram, _boxes(a), [_box(outer)])
    moved = _layout(client, token, project["id"], saved, _boxes(a, b))
    assert len(view(client, token, project["id"], diagram["id"])["boundaries"]) == 1
    again = _layout(client, token, project["id"], moved, _boxes(a, b), [_box(outer)])
    assert again["version"] == moved["version"]  # the same lists change nothing
    _layout(client, token, project["id"], again, _boxes(a, b), [])
    assert view(client, token, project["id"], diagram["id"])["boundaries"] == []


def test_a_box_that_stops_being_outer_is_kept_but_not_drawn(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary stale")
    _scope, a, _b, outside, outer, diagram = _build(client, token, project["id"])
    _layout(client, token, project["id"], diagram, _boxes(a), [_box(outer)])
    # Move the outside element under the scope: the connection is then wholly inside.
    put_element(client, token, project["id"], outside, parent_id=_scope["id"])
    assert view(client, token, project["id"], diagram["id"])["boundaries"] == []
    moved = client.get(f"{project_base(project['id'])}/elements/{outside['id']}", headers=auth_headers(token)).json()
    put_element(client, token, project["id"], moved, parent_id=None)
    assert len(view(client, token, project["id"], diagram["id"])["boundaries"]) == 1


def test_changing_the_scope_clears_the_boxes(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary scope")
    _scope, a, _b, _outside, outer, diagram = _build(client, token, project["id"])
    saved = _layout(client, token, project["id"], diagram, _boxes(a), [_box(outer)])
    resp = client.put(
        f"{project_base(project['id'])}/diagrams/{diagram['id']}",
        json={"version": saved["version"], "scope_element_id": None}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert view(client, token, project["id"], diagram["id"])["boundaries"] == []
    resp = client.put(
        f"{project_base(project['id'])}/diagrams/{diagram['id']}",
        json={"version": resp.json()["version"], "scope_element_id": _scope["id"]}, headers=auth_headers(token),
    )
    assert view(client, token, project["id"], diagram["id"])["boundaries"] == []


def test_deleting_the_outer_connection_removes_its_box(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary delete")
    _scope, a, _b, _outside, outer, diagram = _build(client, token, project["id"])
    _layout(client, token, project["id"], diagram, _boxes(a), [_box(outer)])
    assert client.delete(f"{project_base(project['id'])}/connections/{outer['id']}", headers=auth_headers(token)).status_code == 204
    assert view(client, token, project["id"], diagram["id"])["boundaries"] == []


# --- The resolved view, the model and the drawings -------------------------------------------------------------------


def test_a_realising_connection_is_drawn_to_the_box_and_covers_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary line")
    scope, a, b, _outside, outer, diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    _realise(client, token, project["id"], inner, [outer["id"]])
    _layout(client, token, project["id"], diagram, _boxes(a, b), [_box(outer)])
    resolved = view(client, token, project["id"], diagram["id"])
    (box,) = resolved["boundaries"]
    assert (box["covered"], box["realised_by_count"]) == (True, 1)
    (edge,) = (e for e in resolved["edges"] if e["target_is_boundary"])
    assert (edge["source_element_id"], edge["target_element_id"], edge["source_is_boundary"]) == (a["id"], box["id"], False)
    assert [c["id"] for c in edge["connections"]] == [inner["id"]]


def test_without_a_realisation_the_box_is_not_covered_and_has_no_line(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary open")
    _scope, a, b, _outside, outer, diagram = _build(client, token, project["id"])
    _layout(client, token, project["id"], diagram, _boxes(a, b), [_box(outer)])
    resolved = view(client, token, project["id"], diagram["id"])
    assert resolved["boundaries"][0]["covered"] is False
    assert not any(e["source_is_boundary"] or e["target_is_boundary"] for e in resolved["edges"])


def test_the_model_lists_the_realisations(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary model")
    scope, a, _b, _outside, outer, diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    _realise(client, token, project["id"], inner, [outer["id"]])
    model = client.get(f"{project_base(project['id'])}/diagrams/{diagram['id']}/model", headers=auth_headers(token)).json()
    assert model["realisations"] == [{"inner_connection_id": inner["id"], "outer_connection_id": outer["id"]}]
    assert {c["id"] for c in model["connections"]} >= {inner["id"], outer["id"]}


def test_the_server_drawings_show_the_box_with_its_shape_and_the_line_to_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch boundary draw")
    scope, a, b, outside, outer, diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    _realise(client, token, project["id"], inner, [outer["id"]])
    _layout(client, token, project["id"], diagram, _boxes(a, b), [_box(outer)])
    base = f"{project_base(project['id'])}/diagrams/{diagram['id']}"
    svg = client.get(f"{base}/svg", headers=auth_headers(token)).text
    assert 'data-boundary="' in svg and outer["unique_code"] in svg and outside["unique_code"] in svg
    assert "<polygon" in svg and svg.count("<line") == 1
    mermaid = client.get(f"{base}/mermaid", headers=auth_headers(token)).text
    assert outer["unique_code"] in mermaid and '[\\"' in mermaid
    assert mermaid.count("-->") == 1


# --- Bundles --------------------------------------------------------------------------------------------------------


def test_boxes_and_realisations_round_trip_through_the_project_bundle(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch boundary bundle")
    scope, a, b, _outside, outer, diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    _realise(client, token, project["id"], inner, [outer["id"]])
    _layout(client, token, project["id"], diagram, _boxes(a, b), [_box(outer, x=-300, y=40)])
    resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    data = json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))
    (entry,) = data["architecture_diagrams"]
    assert entry["boundaries"] == [{"connection_code": outer["unique_code"], "x": -300, "y": 40, "width": 120, "height": 48}]
    assert {c["unique_code"]: c["realises"] for c in data["architecture_connections"]}[inner["unique_code"]] == [outer["unique_code"]]
    assert str(outer["id"]) not in json.dumps(entry)

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch boundary bundle copy"},
        files={"file": ("bundle.zip", resp.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    assert not [w for w in imported.json().get("warnings", []) if "boundary" in w or "realisation" in w]
    (diagram_copy,) = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    (box,) = view(client, token, copy["id"], diagram_copy["id"])["boundaries"]
    assert (box["x"], box["y"], box["covered"], box["realised_by_count"]) == (-300, 40, True, 1)


def test_an_import_drops_a_box_and_a_realisation_it_cannot_restore_with_a_warning(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch boundary bad bundle")
    scope, a, b, _outside, outer, diagram = _build(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    _realise(client, token, project["id"], inner, [outer["id"]])
    _layout(client, token, project["id"], diagram, _boxes(a, b), [_box(outer)])
    resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    data = json.loads(archive.read("project.json"))
    data["architecture_diagrams"][0]["boundaries"].append({"connection_code": "CON-999", "x": 0, "y": 0})
    inside = next(c for c in data["architecture_connections"] if c["unique_code"] == inner["unique_code"])
    inside["realises"].append("CON-999")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as rewritten:
        for item in archive.infolist():
            rewritten.writestr(item, json.dumps(data) if item.filename == "project.json" else archive.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch boundary bad bundle copy"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    warnings = imported.json().get("warnings", [])
    assert sum("boundary box" in w for w in warnings) == 1 and sum("realisation" in w for w in warnings) == 1
