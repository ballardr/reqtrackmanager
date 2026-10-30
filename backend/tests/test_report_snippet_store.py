"""Author-saved report snippets: save a selection, tiers and inheritance, hide and restore, copy, the picture rule, apply.

Runs against the live API (organisation and project routes) with a fresh organisation per test.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

import pytest
from PIL import Image as PilImage

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.report_snippet import SavedReportSnippet
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import empty_tree, validate_tree
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login
from tests.link_world import World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Saved Snippets Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def png() -> bytes:
    out = io.BytesIO()
    PilImage.new("RGB", (200, 100), "red").save(out, "PNG")
    return out.getvalue()


def org_url(world: World, tail: str = "") -> str:
    return f"/api/v1/orgs/{world.org['id']}/report-snippets{tail}"


def project_url(project: dict, tail: str = "") -> str:
    return f"/api/v1/projects/{project['id']}/report-snippets{tail}"


def layouts_url(scope: str, tail: str = "") -> str:
    return f"{scope}/report-layouts{tail}"


def doc(*nodes: dict, **root: Any) -> dict:
    return {**empty_tree("document"), **root, "nodes": list(nodes)}


HEADING = {"type": "heading", "text": "House risk table"}
TEXT = {"type": "text", "text": "Body"}


def save(world: World, url: str, tree: dict, name: str = "House block", *, start: int = 0, count: int = 1, container: str = "nodes", **extra):
    body = {"name": name, "tree": tree, "selection": {"container": container, "start": start, "count": count}, **extra}
    return world.client.post(url, json=body, headers=auth_headers(world.token))


def upload_image(world: World, url: str) -> str:
    resp = world.client.post(url, files={"file": ("logo.png", png(), "image/png")}, headers=auth_headers(world.token))
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def listing(world: World, url: str, token: str | None = None) -> list[dict]:
    resp = world.client.get(url, headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def insertable(world: World, scope: str) -> list[dict]:
    return listing(world, layouts_url(scope, "/snippets"))


# ---- save -----------------------------------------------------------------------------------------------------


def test_saving_a_selection_stores_the_blocks_and_offers_them_in_the_insert_list(world):
    resp = save(world, org_url(world), doc(HEADING, TEXT), "Risk heading", description="A heading", category="House")

    assert resp.status_code == 201, resp.text
    saved = resp.json()
    assert saved["origin"] == "organization" and saved["editable"] and saved["blocks"] == 1
    offered = next(s for s in insertable(world, f"/api/v1/orgs/{world.org['id']}") if s["key"] == saved["key"])
    assert offered["name"] == "Risk heading" and offered["category"] == "House" and offered["parameters"] == []
    assert offered["saved_id"] == saved["id"] and offered["origin"] == "organization"
    assert offered["blocks"] == [HEADING]


def test_a_container_is_saved_with_everything_inside_it_and_counts_every_block(world):
    group = {"type": "each", "source": {"record_type": "requirement"}, "as": "req", "children": [{"type": "heading", "text": "{{req.title}}"}]}
    resp = save(world, org_url(world), doc(group), "Each requirement")

    assert resp.status_code == 201, resp.text
    assert resp.json()["blocks"] == 2


def test_a_selection_is_a_run_of_blocks_of_any_list_in_the_layout(world):
    texts = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    group = {"type": "each", "source": {"record_type": "requirement"}, "as": "req", "children": texts}
    both = save(world, org_url(world), doc(group), "Both texts", container="nodes[0].children", start=0, count=2)
    one = save(world, org_url(world), doc(group), "Second text", container="nodes[0].children", start=1, count=1)

    assert both.status_code == 201, both.text
    assert both.json()["blocks"] == 2
    assert one.status_code == 201, one.text
    assert one.json()["blocks"] == 1


@pytest.mark.parametrize("selection", [
    {"container": "nodes", "start": 5, "count": 1},
    {"container": "nodes", "start": 0, "count": 4},
    {"container": "nodes[9].children", "start": 0, "count": 1},
    {"container": "page_styles", "start": 0, "count": 1},
    {"container": "nodes[0]", "start": 0, "count": 1},
])
def test_a_selection_outside_the_layout_is_refused(world, selection):
    body = {"name": "x", "tree": doc(HEADING), "selection": selection}
    resp = world.client.post(org_url(world), json=body, headers=auth_headers(world.token))

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["errors"][0]["path"] == "selection"


def test_a_selection_that_needs_something_outside_it_is_refused_with_the_reason(world):
    inner = {"type": "heading", "text": "{{req.title}}"}
    group = {"type": "each", "source": {"record_type": "requirement"}, "as": "req", "children": [inner]}
    resp = save(world, org_url(world), doc(group), "Needs req", container="nodes[0].children", start=0, count=1)

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["errors"]


def test_page_styles_and_variables_the_blocks_use_are_carried(world):
    styles = [{"name": "Wide", "orientation": "landscape"}, {"name": "Unused", "orientation": "portrait"}]
    variables = [{"name": "audience", "type": "text", "label": "Audience"}, {"name": "unused", "type": "text", "label": "Unused"}]
    section = {"type": "section", "page_style": "Wide", "children": [{"type": "heading", "text": "For {{var.audience}}"}]}
    tree = doc(section, page_styles=styles, variables=variables)
    body = {"tree": tree, "selection": {"container": "nodes", "start": 0, "count": 1}}
    check = world.client.post(org_url(world, "/check"), json=body, headers=auth_headers(world.token))

    assert check.status_code == 200, check.text
    assert check.json() == {"ok": True, "errors": [], "blocks": 2, "page_styles": ["Wide"], "variables": ["audience"]}
    saved = save(world, org_url(world), tree, "Wide section").json()
    assert saved["page_styles"] == ["Wide"] and saved["variables"] == ["audience"]


def test_inserting_a_snippet_that_carries_a_page_style_adds_it_to_a_layout_without_it(world):
    section = {"type": "section", "page_style": "Wide", "children": [TEXT]}
    saved = save(world, org_url(world), doc(section, page_styles=[{"name": "Wide", "orientation": "landscape"}]), "Wide").json()
    base = layouts_url(f"/api/v1/orgs/{world.org['id']}")

    resp = world.client.post(f"{base}/snippets/{saved['key']}/apply", json={"tree": doc(HEADING)}, headers=auth_headers(world.token))

    body = resp.json()
    assert body["ok"], body
    assert [s["name"] for s in body["tree"]["page_styles"]] == ["Wide"] and body["tree"]["nodes"][1]["page_style"] == "Wide"
    assert validate_tree(body["tree"], family="document").ok
    assert parse_text(format_tree(body["tree"])).tree == body["tree"]


def test_a_table_snippet_is_for_table_layouts_only(world):
    sheet = {"type": "sheet", "name": "Reqs", "source": {"record_type": "requirement"}, "columns": [{"field": "title"}]}
    table_tree = {**empty_tree("table"), "nodes": [sheet]}
    saved = save(world, org_url(world), table_tree, "Req sheet").json()
    base = layouts_url(f"/api/v1/orgs/{world.org['id']}")

    assert saved["family"] == "table"
    resp = world.client.post(f"{base}/snippets/{saved['key']}/apply", json={"tree": doc()}, headers=auth_headers(world.token))
    assert not resp.json()["ok"] and "table layout" in resp.json()["errors"][0]["message"]


def test_names_are_unique_per_owner_ignoring_case_and_details_are_checked(world):
    assert save(world, org_url(world), doc(HEADING), "Same").status_code == 201

    assert save(world, org_url(world), doc(HEADING), "same").status_code == 409
    assert save(world, org_url(world), doc(HEADING), "x" * 201).status_code == 422
    assert save(world, org_url(world), doc(HEADING), "Cat", category="c" * 61).status_code == 422
    assert save(world, org_url(world), doc(HEADING), "  ", ).status_code == 422


def test_an_empty_category_is_filed_under_saved(world):
    assert save(world, org_url(world), doc(HEADING), "Plain").json()["category"] == "Saved"


# ---- the picture rule -------------------------------------------------------------------------------------------


def test_a_project_picture_can_be_saved_in_the_project_but_not_at_organisation_level(world):
    project = world.project("Pics")
    file_id = upload_image(world, f"/api/v1/projects/{project['id']}/report-images")
    tree = doc({"type": "image", "file": file_id, "alt": "Logo"})

    mine = save(world, project_url(project), tree, "Project logo")
    assert mine.status_code == 201, mine.text

    up = save(world, project_url(project, "/organization"), tree, "Org logo")
    assert up.status_code == 422, up.text
    assert any("logo.png" in e["message"] for e in up.json()["detail"]["errors"])
    body = {"tree": tree, "selection": {"container": "nodes", "start": 0, "count": 1}}
    check = world.client.post(project_url(project, "/check-organization"), json=body, headers=auth_headers(world.token))
    assert check.json()["ok"] is False and "logo.png" in check.json()["errors"][0]["message"]


def test_copying_a_snippet_with_a_project_picture_up_is_refused_and_an_organisation_picture_copies_down(world):
    project = world.project("Copies")
    project_file = upload_image(world, f"/api/v1/projects/{project['id']}/report-images")
    org_file = upload_image(world, f"/api/v1/orgs/{world.org['id']}/report-images")
    mine = save(world, project_url(project), doc({"type": "image", "file": project_file, "alt": "p"}), "Project pic").json()
    shared = save(world, org_url(world), doc({"type": "image", "file": org_file, "alt": "o"}), "Org pic").json()

    up = world.client.post(project_url(project, f"/{mine['id']}/copy"), json={"target": "organization"}, headers=auth_headers(world.token))
    down = world.client.post(project_url(project, f"/{shared['id']}/copy"), json={"target": "project"}, headers=auth_headers(world.token))

    assert up.status_code == 422 and "logo.png" in up.text
    assert down.status_code == 201 and down.json()["name"] == "Org pic (copy)" and down.json()["origin"] == "project"


def test_an_organisation_layout_cannot_take_a_project_picture_whoever_saved_the_snippet(world, db):
    project = world.project("Sneaky")
    file_id = upload_image(world, f"/api/v1/projects/{project['id']}/report-images")
    saved = save(world, project_url(project), doc({"type": "image", "file": file_id, "alt": "p"}), "Project pic").json()
    # a project snippet is not offered at the organisation, whatever its content
    org_keys = {s["key"] for s in insertable(world, f"/api/v1/orgs/{world.org['id']}")}
    assert saved["key"] not in org_keys
    # even a row that reached the organisation tier some other way is refused when it is inserted
    row = SavedReportSnippet(
        organization_id=world.org["id"], project_id=None, name="Planted", description="", category="Saved", family="document",
        blocks=[{"type": "image", "file": file_id, "alt": "p"}], root={},
    )
    db.add(row)
    db.commit()
    try:
        base = layouts_url(f"/api/v1/orgs/{world.org['id']}")
        resp = world.client.post(f"{base}/snippets/saved-{row.id}/apply", json={"tree": doc()}, headers=auth_headers(world.token))
        assert not resp.json()["ok"] and any("logo.png" in e["message"] for e in resp.json()["errors"])
    finally:
        db.delete(row)
        db.commit()


def test_the_image_library_lists_a_saved_snippet_as_a_user_of_its_picture(world):
    file_id = upload_image(world, f"/api/v1/orgs/{world.org['id']}/report-images")
    save(world, org_url(world), doc({"type": "image", "file": file_id, "alt": "Logo"}), "Logo block")

    images = world.client.get(f"/api/v1/orgs/{world.org['id']}/report-images", headers=auth_headers(world.token)).json()["images"]
    rows = {r["id"]: r for r in images}

    assert rows[file_id]["used_by"] == ["Logo block (snippet)"]


def test_a_saved_snippet_can_be_read_with_its_blocks_and_root(world):
    project = world.project("Reader")
    section = {"type": "section", "page_style": "Wide", "children": [TEXT]}
    mine = save(world, project_url(project), doc(section, page_styles=[{"name": "Wide", "orientation": "landscape"}]), "Wide block").json()
    inherited = save(world, org_url(world), doc(HEADING), "Org block").json()
    headers = auth_headers(world.token)

    own = world.client.get(project_url(project, f"/{mine['id']}"), headers=headers).json()
    shared = world.client.get(project_url(project, f"/{inherited['id']}"), headers=headers).json()

    assert own["nodes"] == [section] and own["root"] == {"page_styles": [{"name": "Wide", "orientation": "landscape"}]} and own["editable"]
    assert shared["nodes"] == [HEADING] and shared["origin"] == "organization" and not shared["editable"]
    assert world.client.get(org_url(world, f"/{inherited['id']}"), headers=headers).json()["nodes"] == [HEADING]
    assert world.client.get(org_url(world, f"/{mine['id']}"), headers=headers).status_code == 404


# ---- tiers, inheritance, hide and restore -------------------------------------------------------------------------


def test_a_project_sees_its_own_its_ancestors_and_the_organisations_snippets_nearest_name_wins(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    save(world, org_url(world), doc(HEADING), "Shared name")
    save(world, org_url(world), doc(HEADING), "Org only")
    save(world, project_url(parent), doc(TEXT), "Shared name")
    save(world, project_url(parent), doc(TEXT), "Parent only")
    save(world, project_url(child), doc(TEXT), "Child only")

    rows = {r["name"]: r for r in listing(world, project_url(child))}

    assert set(rows) == {"Shared name", "Org only", "Parent only", "Child only"}
    assert rows["Shared name"]["origin"] == "ancestor" and rows["Org only"]["origin"] == "organization"
    assert rows["Child only"]["origin"] == "project" and rows["Child only"]["editable"] and not rows["Parent only"]["editable"]
    offered = {s["name"]: s["origin"] for s in insertable(world, f"/api/v1/projects/{child['id']}") if s["saved_id"]}
    assert offered == {"Shared name": "ancestor", "Org only": "organization", "Parent only": "ancestor", "Child only": "project"}
    assert {r["name"] for r in listing(world, org_url(world))} == {"Shared name", "Org only"}


def test_hiding_an_inherited_snippet_removes_it_from_the_insert_list_and_restoring_brings_it_back(world):
    project = world.project("Hider")
    other = world.project("Other")
    saved = save(world, org_url(world), doc(HEADING), "Default").json()

    hide = world.client.put(project_url(project, f"/{saved['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    assert hide.status_code == 200 and hide.json()["hidden"] is True
    assert saved["key"] not in {s["key"] for s in insertable(world, f"/api/v1/projects/{project['id']}")}
    assert saved["key"] in {s["key"] for s in insertable(world, f"/api/v1/projects/{other['id']}")}
    assert next(r for r in listing(world, project_url(project)) if r["id"] == saved["id"])["hidden"] is True

    show = world.client.put(project_url(project, f"/{saved['id']}/visibility"), json={"hidden": False}, headers=auth_headers(world.token))
    assert show.status_code == 200 and show.json()["hidden"] is False
    assert saved["key"] in {s["key"] for s in insertable(world, f"/api/v1/projects/{project['id']}")}

    world.client.put(project_url(project, f"/{saved['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    restored = world.client.post(project_url(project, "/restore"), headers=auth_headers(world.token))
    assert restored.json() == {"restored": [saved["id"]]}


def test_a_project_cannot_hide_its_own_snippet_or_change_an_inherited_one(world):
    project = world.project("Owner")
    org_snippet = save(world, org_url(world), doc(HEADING), "Inherited").json()
    own = save(world, project_url(project), doc(TEXT), "Own").json()
    headers = auth_headers(world.token)

    assert world.client.put(project_url(project, f"/{own['id']}/visibility"), json={"hidden": True}, headers=headers).status_code == 404
    assert world.client.patch(project_url(project, f"/{org_snippet['id']}"), json={"name": "x"}, headers=headers).status_code == 403
    assert world.client.delete(project_url(project, f"/{org_snippet['id']}"), headers=headers).status_code == 403


def test_deleting_an_organisation_snippet_forgets_the_projects_that_hid_it(world, db):
    project = world.project("Forget")
    saved = save(world, org_url(world), doc(HEADING), "Gone").json()
    world.client.put(project_url(project, f"/{saved['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))

    assert world.client.delete(org_url(world, f"/{saved['id']}"), headers=auth_headers(world.token)).status_code == 204

    from app.models.definition_suppression import ProjectDefinitionSuppression
    assert db.query(ProjectDefinitionSuppression).filter_by(org_definition_id=saved["id"]).count() == 0
    assert listing(world, project_url(project)) == []


def test_a_snippet_of_another_organisation_is_a_404(world, client, admin_token):
    other = World(client, admin_token, "Other Org")
    theirs = save(other, org_url(other), doc(HEADING), "Theirs").json()
    headers = auth_headers(world.token)

    assert client.patch(org_url(world, f"/{theirs['id']}"), json={"name": "x"}, headers=headers).status_code == 404
    assert client.delete(org_url(world, f"/{theirs['id']}"), headers=headers).status_code == 404
    assert client.post(org_url(world, f"/{theirs['id']}/copy"), headers=headers).status_code == 404
    base = layouts_url(f"/api/v1/orgs/{world.org['id']}")
    assert client.post(f"{base}/snippets/{theirs['key']}/apply", json={"tree": doc()}, headers=headers).status_code == 404


# ---- manage, copy, audit --------------------------------------------------------------------------------------


def test_renaming_and_deleting_a_snippet_leaves_layouts_built_from_it_unchanged(world):
    saved = save(world, org_url(world), doc(HEADING), "Before").json()
    base = layouts_url(f"/api/v1/orgs/{world.org['id']}")
    built = world.client.post(f"{base}/snippets/{saved['key']}/apply", json={"tree": doc()}, headers=auth_headers(world.token)).json()["tree"]

    renamed = world.client.patch(org_url(world, f"/{saved['id']}"), json={"name": "After", "category": "Cats"}, headers=auth_headers(world.token))
    assert renamed.json()["name"] == "After" and renamed.json()["category"] == "Cats"
    assert world.client.delete(org_url(world, f"/{saved['id']}"), headers=auth_headers(world.token)).status_code == 204

    assert built["nodes"] == [HEADING]
    assert saved["key"] not in {s["key"] for s in insertable(world, f"/api/v1/orgs/{world.org['id']}")}
    gone = world.client.post(f"{base}/snippets/{saved['key']}/apply", json={"tree": doc()}, headers=auth_headers(world.token))
    assert gone.status_code == 404


def test_a_rename_to_a_taken_name_is_a_conflict(world):
    save(world, org_url(world), doc(HEADING), "One")
    two = save(world, org_url(world), doc(HEADING), "Two").json()

    assert world.client.patch(org_url(world, f"/{two['id']}"), json={"name": "ONE"}, headers=auth_headers(world.token)).status_code == 409


def test_copy_names_the_first_free_copy_and_copies_up_with_the_organisation_permission(world):
    project = world.project("Copier")
    mine = save(world, project_url(project), doc(HEADING), "Block").json()
    headers = auth_headers(world.token)

    first = world.client.post(project_url(project, f"/{mine['id']}/copy"), headers=headers).json()
    second = world.client.post(project_url(project, f"/{mine['id']}/copy"), headers=headers).json()
    up = world.client.post(project_url(project, f"/{mine['id']}/copy"), json={"target": "organization", "name": "Block"}, headers=headers)
    clash = world.client.post(project_url(project, f"/{mine['id']}/copy"), json={"target": "organization", "name": "block"}, headers=headers)

    assert (first["name"], second["name"]) == ("Block (copy)", "Block (copy 2)")
    assert up.status_code == 201 and up.json()["origin"] == "organization" and up.json()["project_id"] is None
    assert clash.status_code == 409


def test_a_person_without_the_manage_right_sees_and_changes_nothing(world):
    project = world.project("Locked")
    saved = save(world, org_url(world), doc(HEADING), "Locked").json()
    email = "snippet-member@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    member = login(world.client, email, "Password123!")
    headers = auth_headers(member)

    assert world.client.get(org_url(world), headers=headers).status_code == 403
    assert world.client.get(project_url(project), headers=headers).status_code == 403
    assert world.client.post(org_url(world), json={"name": "x", "tree": doc(HEADING), "selection": {"start": 0}}, headers=headers).status_code == 403
    assert world.client.delete(org_url(world, f"/{saved['id']}"), headers=headers).status_code == 403
    assert world.client.get(org_url(world)).status_code in (401, 403)


def test_audit_events_carry_counts_and_never_block_text(world, db):
    secret = {"type": "text", "text": "highly confidential wording"}
    saved = save(world, org_url(world), doc(secret), "Audited").json()
    world.client.patch(org_url(world, f"/{saved['id']}"), json={"description": "x"}, headers=auth_headers(world.token))
    world.client.delete(org_url(world, f"/{saved['id']}"), headers=auth_headers(world.token))

    events = db.query(AuditEvent).filter_by(entity_type="report_snippet", entity_id=saved["id"]).all()

    assert sorted(e.action for e in events) == ["created", "deleted", "updated"]
    assert all("confidential" not in str(e.detail) for e in events)
    assert next(e for e in events if e.action == "created").detail == {"family": "document", "blocks": 1}


# ---- the Text view ---------------------------------------------------------------------------------------------


def test_the_text_parse_reports_the_line_each_block_starts_on(world):
    text = "@layout document\n\n@heading One\n\n@group requirement by component as comp\n  @heading {{comp.value}}\n@end\n\nA line of text\n"
    resp = world.client.post(layouts_url(f"/api/v1/orgs/{world.org['id']}", "/text/parse"), json={"text": text}, headers=auth_headers(world.token))

    assert resp.status_code == 200, resp.text
    assert resp.json()["block_lines"] == {"nodes[0]": 3, "nodes[1]": 5, "nodes[1].children[0]": 6, "nodes[2]": 9}


def test_a_syntax_error_gives_no_block_lines(world):
    url = layouts_url(f"/api/v1/orgs/{world.org['id']}", "/text/parse")
    resp = world.client.post(url, json={"text": "@layout document\n@nonsense\n"}, headers=auth_headers(world.token))

    assert resp.json()["tree"] is None and resp.json()["block_lines"] == {}


# ---- bundles ---------------------------------------------------------------------------------------------------


def export_project(world: World, project: dict) -> bytes:
    resp = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.content


def import_project(world: World, bundle: bytes, name: str = "Imported") -> dict:
    resp = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def rewrite(bundle: bytes, member: str, edit) -> bytes:
    """The zip with `member` (a JSON file) passed through `edit`."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == member:
                parsed = json.loads(data)
                edit(parsed)
                data = json.dumps(parsed).encode()
            dst.writestr(item, data)
    return out.getvalue()


def test_a_project_bundle_round_trips_snippets_hides_and_pictures(world):
    source = world.project("Source")
    h = auth_headers(world.token)
    picture = upload_image(world, f"/api/v1/projects/{source['id']}/report-images")
    section = {"type": "section", "page_style": "Wide", "children": [{"type": "image", "file": picture, "alt": "Logo"}]}
    styled = doc(section, page_styles=[{"name": "Wide", "orientation": "landscape"}])
    save(world, project_url(source), styled, "With picture", description="D", category="House")
    inherited = save(world, org_url(world), doc(HEADING), "Org default").json()
    world.client.put(project_url(source, f"/{inherited['id']}/visibility"), json={"hidden": True}, headers=h)

    result = import_project(world, export_project(world, source))

    assert result["warnings"] == []
    copy = result["project"]
    rows = {r["name"]: r for r in listing(world, project_url(copy))}
    assert rows["Org default"]["hidden"] is True and rows["Org default"]["origin"] == "organization"
    mine = rows["With picture"]
    assert mine["origin"] == "project" and mine["id"] != "" and mine["category"] == "House" and mine["description"] == "D"
    assert mine["page_styles"] == ["Wide"]
    offered = next(s for s in insertable(world, f"/api/v1/projects/{copy['id']}") if s["saved_id"] == mine["id"])
    new_picture = offered["blocks"][0]["children"][0]["file"]
    assert new_picture != picture
    applied = world.client.post(
        layouts_url(f"/api/v1/projects/{copy['id']}", f"/snippets/{offered['key']}/apply"), json={"tree": doc()}, headers=h,
    ).json()
    assert applied["ok"], applied


def test_an_invalid_fragment_in_a_bundle_is_skipped_with_a_warning(world):
    source = world.project("Source")
    save(world, project_url(source), doc(HEADING), "Good")
    save(world, project_url(source), doc(HEADING), "Broken")

    def corrupt(data: dict) -> None:
        for entry in data["report_snippets"]:
            if entry["name"] == "Broken":
                entry["blocks"] = [{"type": "no_such_block"}]

    result = import_project(world, rewrite(export_project(world, source), "project.json", corrupt))

    assert any('"Broken"' in w and "skipped" in w for w in result["warnings"])
    assert [r["name"] for r in listing(world, project_url(result["project"]))] == ["Good"]


def test_a_hide_with_no_matching_inherited_snippet_is_reported(world):
    source = world.project("Source")
    inherited = save(world, org_url(world), doc(HEADING), "Org default").json()
    world.client.put(project_url(source, f"/{inherited['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    bundle = export_project(world, source)
    world.client.delete(org_url(world, f"/{inherited['id']}"), headers=auth_headers(world.token))

    warnings = import_project(world, bundle)["warnings"]

    assert any('Hidden report snippet "Org default"' in w for w in warnings)


def test_a_bundle_from_before_snippets_imports_unchanged(world):
    source = world.project("Source")

    def strip(data: dict) -> None:
        for key in ("report_snippets", "report_snippets_hidden", "report_snippet_images"):
            data.pop(key, None)

    result = import_project(world, rewrite(export_project(world, source), "project.json", strip))

    assert result["warnings"] == [] and listing(world, project_url(result["project"])) == []


def test_an_organisation_bundle_carries_snippets_and_a_merge_never_overwrites(client, admin_token, world):
    h = auth_headers(world.token)
    picture = upload_image(world, f"/api/v1/orgs/{world.org['id']}/report-images")
    save(world, org_url(world), doc({"type": "image", "file": picture, "alt": "Logo"}), "Shared name")
    save(world, org_url(world), doc(HEADING), "New one")
    bundle = client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=h).content

    created = client.post(
        "/api/v1/orgs/import", data={"name": f"Copy {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    new_org = created.json()["organization"]["id"]
    assert sorted(r["name"] for r in client.get(f"/api/v1/orgs/{new_org}/report-snippets", headers=h).json()) == ["New one", "Shared name"]

    target, target_token = create_org_admin_in(client, admin_token, "Merge Target")
    target_url = f"/api/v1/orgs/{target['id']}/report-snippets"
    kept = client.post(
        target_url, json={"name": "Shared name", "tree": doc(TEXT), "selection": {"start": 0}}, headers=auth_headers(target_token),
    )
    assert kept.status_code == 201, kept.text
    opened = client.put(
        f"/api/v1/orgs/{target['id']}/advanced-settings", json={"external_user_policy": "anyone"}, headers=auth_headers(target_token),
    )
    assert opened.status_code == 200, opened.text

    merged = client.post(
        f"/api/v1/orgs/{target['id']}/import/merge", files={"file": ("bundle.zip", bundle, "application/zip")},
        data={"resolutions": "{}"}, headers=auth_headers(target_token),
    )
    assert merged.status_code == 200, merged.text

    rows = client.get(target_url, headers=auth_headers(target_token)).json()
    assert sorted(r["name"] for r in rows) == ["New one", "Shared name", "Shared name (imported)"]
    imported = next(r for r in rows if r["name"] == "Shared name (imported)")
    base = f"/api/v1/orgs/{target['id']}/report-layouts"
    offered = next(s for s in client.get(f"{base}/snippets", headers=auth_headers(target_token)).json() if s["saved_id"] == imported["id"])
    assert offered["blocks"][0]["type"] == "image" and offered["blocks"][0]["file"] != picture
