"""Tests for copying reports between projects (`routers.report_copy`, `services.report_copy`): what is copied and how
(latest version as version 1, inherited reports as the project's own, packs re-pointed at renamed layouts, sets,
folders, placements, pictures, favourites), name conflicts (rename or skip, never replace), the dry-run, both gates
(manage in the target, manage in the source, one organisation, archived), the audit event, nested projects and the
bundle round trip. Each test builds its own organisation.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

import pytest
from PIL import Image as PilImage
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.file import FileAsset
from app.models.project import Project
from app.models.report_layout import ReportLayout
from app.services.report_layout_tree import empty_tree
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World

PLATFORM_KEY = "report:platform.requirements"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Copy Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def tree(text: str = "Hello", *extra: dict) -> dict:
    return {**empty_tree("document"), "nodes": [{"type": "heading", "text": text}, *extra]}


def png(colour: str = "red") -> bytes:
    out = io.BytesIO()
    PilImage.new("RGB", (40, 20), colour).save(out, "PNG")
    return out.getvalue()


def layouts_url(owner: dict | World, suffix: str = "") -> str:
    base = f"/api/v1/orgs/{owner.org['id']}" if isinstance(owner, World) else f"/api/v1/projects/{owner['id']}"
    return f"{base}/report-layouts{suffix}"


def packs_url(owner: dict | World, suffix: str = "") -> str:
    base = f"/api/v1/orgs/{owner.org['id']}" if isinstance(owner, World) else f"/api/v1/projects/{owner['id']}"
    return f"{base}/report-packs{suffix}"


def new_layout(world: World, owner: dict | World, name: str, body: dict | None = None, folder: str = "") -> dict:
    resp = world.client.post(
        layouts_url(owner), json={"name": name, "description": "about " + name, "family": "document", "folder": folder, "tree": body or tree(name)},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def new_pack(world: World, owner: dict | World, name: str, *layout_names: str, variables: list[dict] | None = None) -> dict:
    definition: dict[str, Any] = {
        "schema_version": 1, "entries": [{"kind": "layout", "name": n, "format": "pdf"} for n in layout_names],
    }
    if variables:
        definition["variables"] = variables
    resp = world.client.post(
        packs_url(owner), json={"name": name, "description": "d", "definition": definition}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def copy_url(target: dict) -> str:
    return f"/api/v1/projects/{target['id']}/report-copy"


def do_copy(world: World, source: dict, target: dict, *, token: str | None = None, **body: Any):
    return world.client.post(
        copy_url(target), json={"source_project_id": source["id"], **body}, headers=auth_headers(token or world.token),
    )


def copied(world: World, source: dict, target: dict, **body: Any) -> dict:
    resp = do_copy(world, source, target, **body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def listed(world: World, project: dict, kind: str = "layouts") -> dict[str, dict]:
    url = layouts_url(project) if kind == "layouts" else packs_url(project)
    resp = world.client.get(url, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return {row["name"]: row for row in resp.json()}


def user_with_role(world: World, project: dict, role: str) -> str:
    """A fresh organisation member holding `role` in `project`; returns their token."""
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


# ---- what is copied -----------------------------------------------------------------------------------------------


def test_the_latest_version_becomes_version_one_of_an_independent_copy(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Handover", folder="Board")
    saved = world.client.put(
        layouts_url(source, f"/{layout['id']}/tree"), json={"tree": tree("Second"), "base_version": 1, "comment": "retitle"},
        headers=auth_headers(world.token),
    )
    assert saved.status_code == 200

    result = copied(world, source, target, layout_ids=[layout["id"]])

    assert [(i["kind"], i["action"], i["new_name"]) for i in result["items"]] == [("layout", "create", "Handover")]
    made = listed(world, target)["Handover"]
    assert made["origin"] == "project" and made["id"] != layout["id"] and made["current_version"] == 1
    assert made["folder"] == "Board" and made["description"] == "about Handover"
    detail = world.client.get(layouts_url(target, f"/{made['id']}"), headers=auth_headers(world.token)).json()
    assert detail["current"]["tree"] == tree("Second")
    assert detail["current"]["comment"] == "Copied from Handover, version 2"
    versions = world.client.get(layouts_url(target, f"/{made['id']}/versions"), headers=auth_headers(world.token)).json()
    assert [v["version"] for v in versions] == [1]
    # The source keeps its history and is untouched.
    assert listed(world, source)["Handover"]["current_version"] == 2
    world.client.put(
        layouts_url(target, f"/{made['id']}/tree"), json={"tree": tree("Only target"), "base_version": 1},
        headers=auth_headers(world.token),
    )
    own = world.client.get(layouts_url(source, f"/{layout['id']}"), headers=auth_headers(world.token)).json()
    assert own["current"]["tree"] == tree("Second")


def test_an_inherited_organisation_layout_is_copied_as_the_projects_own_editable_layout(world):
    source, target = world.project("Source"), world.project("Target")
    shared = new_layout(world, world, "Org wide")

    copied(world, source, target, layout_ids=[shared["id"]])

    made = listed(world, target)["Org wide"]
    assert made["origin"] == "project" and made["editable"] is True
    assert listed(world, source)["Org wide"]["origin"] == "organization"  # the source is unchanged


def test_a_pack_is_copied_with_its_sets_and_follows_a_renamed_layout(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Monthly")
    new_layout(world, target, "Monthly")  # the name is taken in the target, so the copy is renamed
    pack = new_pack(
        world, source, "Board pack", "Monthly",
        variables=[{"name": "title", "type": "text", "label": "Title", "default": "x"}],
    )
    made_set = world.client.post(
        packs_url(source, f"/{pack['id']}/sets"), json={"name": "Q1", "values": {"title": "First quarter"}},
        headers=auth_headers(world.token),
    )
    assert made_set.status_code in (200, 201), made_set.text

    result = copied(world, source, target, layout_ids=[layout["id"]], pack_ids=[pack["id"]])

    assert [(i["kind"], i["action"], i["new_name"]) for i in result["items"]] == [
        ("layout", "rename", "Monthly (copy)"), ("pack", "create", "Board pack"),
    ]
    assert set(listed(world, target)) == {"Monthly", "Monthly (copy)"}
    made = listed(world, target, "packs")["Board pack"]
    detail = world.client.get(packs_url(target, f"/{made['id']}"), headers=auth_headers(world.token)).json()
    assert [e["name"] for e in detail["current"]["definition"]["entries"]] == ["Monthly (copy)"]
    sets = world.client.get(packs_url(target, f"/{made['id']}/sets"), headers=auth_headers(world.token)).json()
    assert [(s["name"], s["effective"]) for s in sets] == [("Q1", {"title": "First quarter"})]


def test_a_pack_naming_a_project_layout_that_is_not_copied_says_so(world):
    source, target = world.project("Source"), world.project("Target")
    new_layout(world, source, "Monthly")
    pack = new_pack(world, source, "Board pack", "Monthly")

    result = copied(world, source, target, pack_ids=[pack["id"]])

    (item,) = result["items"]
    assert item["action"] == "create" and "Monthly" in item["warnings"][0] and "not part of this copy" in item["warnings"][0]


def test_folders_and_module_report_placements_are_copied_and_existing_ones_left_alone(world):
    source, target = world.project("Source"), world.project("Target")
    h = auth_headers(world.token)
    for path in ("Board", "Board/Monthly"):
        assert world.client.post(f"/api/v1/projects/{source['id']}/report-folders", json={"path": path}, headers=h).status_code in (200, 201)
    assert world.client.post(f"/api/v1/projects/{target['id']}/report-folders", json={"path": "Board"}, headers=h).status_code in (200, 201)
    assert world.client.put(
        f"/api/v1/projects/{source['id']}/report-placements", json={"report_key": PLATFORM_KEY, "folder": "Board"}, headers=h,
    ).status_code == 200

    result = copied(world, source, target, folders=["Board", "Board/Monthly"], placement_keys=[PLATFORM_KEY])

    assert [(i["kind"], i["name"], i["action"]) for i in result["items"]] == [
        ("folder", "Board", "exists"), ("folder", "Board/Monthly", "create"), ("placement", PLATFORM_KEY, "create"),
    ]
    placed = world.client.get(f"/api/v1/projects/{target['id']}/report-placements/resolved", headers=h).json()
    assert placed == [{"report_key": PLATFORM_KEY, "folder": "Board", "hidden": False}]
    again = copied(world, source, target, placement_keys=[PLATFORM_KEY])
    assert again["items"][0]["action"] == "exists"  # never replaced


def test_a_placement_the_source_does_not_hold_is_refused_and_a_folder_it_did_not_add_needs_no_copy(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Keep out")
    assert do_copy(world, source, target, layout_ids=[layout["id"]], placement_keys=[PLATFORM_KEY]).status_code == 404
    assert do_copy(world, source, target, layout_ids=[layout["id"]], placement_keys=["layout:" + layout["id"]]).status_code == 404
    assert "Keep out" not in listed(world, target)

    assert copied(world, source, target, folders=["Nope"])["items"] == []  # a folder name no folder row backs: nothing to copy


def test_the_callers_own_favourites_are_carried_to_the_copies(world):
    source, target = world.project("Source"), world.project("Target")
    starred, plain = new_layout(world, source, "Starred"), new_layout(world, source, "Plain")
    h = auth_headers(world.token)
    assert world.client.patch(
        "/api/v1/auth/me/preferences", json={"ui_preferences": {"report_favourites": [f"layout:{starred['id']}"]}}, headers=h,
    ).status_code == 200

    result = copied(world, source, target, layout_ids=[starred["id"], plain["id"]])

    assert result["favourites_carried"] == 1
    made = listed(world, target)
    favourites = world.client.get("/api/v1/auth/me", headers=h).json()["ui_preferences"]["report_favourites"]
    assert favourites == [f"layout:{starred['id']}", f"layout:{made['Starred']['id']}"]

    off = copied(world, source, world.project("Third"), layout_ids=[starred["id"]], favourites=False)
    assert off["favourites_carried"] == 0


# ---- names, preview and no replace -----------------------------------------------------------------------------------


def test_a_taken_name_is_renamed_each_time_or_skipped_and_never_replaced(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report", body=tree("Source text"))
    new_layout(world, target, "Report", body=tree("Target text"))

    first = copied(world, source, target, layout_ids=[layout["id"]])
    second = copied(world, source, target, layout_ids=[layout["id"]])
    skipped = copied(world, source, target, layout_ids=[layout["id"]], on_conflict="skip")

    assert [r["items"][0]["new_name"] for r in (first, second)] == ["Report (copy)", "Report (copy 2)"]
    assert skipped["items"][0]["action"] == "skip" and skipped["items"][0]["new_id"] is None
    names = listed(world, target)
    assert set(names) == {"Report", "Report (copy)", "Report (copy 2)"}
    original = world.client.get(layouts_url(target, f"/{names['Report']['id']}"), headers=auth_headers(world.token)).json()
    assert original["current"]["tree"] == tree("Target text")


def test_a_dry_run_plans_the_copy_and_writes_nothing(world, db):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report")
    new_layout(world, target, "Report")

    plan = copied(world, source, target, layout_ids=[layout["id"]], dry_run=True)

    assert plan["dry_run"] is True
    assert [(i["action"], i["new_name"], i["new_id"]) for i in plan["items"]] == [("rename", "Report (copy)", None)]
    assert set(listed(world, target)) == {"Report"}
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "reports_copied", AuditEvent.project_id == uuid.UUID(target["id"]))).all()
    assert events == []


def test_a_copy_that_shadows_an_inherited_layout_says_so(world):
    source, target = world.project("Source"), world.project("Target")
    new_layout(world, world, "Shared")
    own = new_layout(world, source, "Shared")  # the source's own layout shadows the organisation's

    result = copied(world, source, target, layout_ids=[own["id"]])

    assert any("shadow" in w for w in result["items"][0]["warnings"])


def test_a_copy_into_a_child_project_is_the_childs_own_and_shadows_the_inherited_one(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    source = world.project("Source")
    in_parent = new_layout(world, parent, "Report", body=tree("Parent text"))
    own = new_layout(world, source, "Report", body=tree("Source text"))
    assert listed(world, child)["Report"]["origin"] == "ancestor" and in_parent

    copied(world, source, child, layout_ids=[own["id"]])

    seen = listed(world, child)["Report"]
    assert seen["origin"] == "project"
    detail = world.client.get(layouts_url(child, f"/{seen['id']}"), headers=auth_headers(world.token)).json()
    assert detail["current"]["tree"] == tree("Source text")


# ---- pictures --------------------------------------------------------------------------------------------------------


def test_a_project_picture_is_copied_into_the_target_library_once_and_an_organisation_picture_stays_a_reference(world, db):
    source, target = world.project("Source"), world.project("Target")
    h = auth_headers(world.token)
    def upload(url: str, name: str, colour: str) -> dict:
        return world.client.post(url, files={"file": (name, png(colour), "image/png")}, headers=h).json()

    own = upload(f"/api/v1/projects/{source['id']}/report-images", "own.png", "red")
    shared = upload(f"/api/v1/orgs/{world.org['id']}/report-images", "shared.png", "blue")

    def picture(file_id: str) -> dict:
        return {"type": "image", "file": file_id, "alt": "A picture"}

    first = new_layout(world, source, "First", body=tree("a", picture(own["id"]), picture(shared["id"])))
    second = new_layout(world, source, "Second", body=tree("b", picture(own["id"])))

    result = copied(world, source, target, layout_ids=[first["id"], second["id"]])

    assert any("picture" in w for w in result["items"][0]["warnings"])
    used = []
    for name in ("First", "Second"):
        made = listed(world, target)[name]
        nodes = world.client.get(layouts_url(target, f"/{made['id']}"), headers=h).json()["current"]["tree"]["nodes"]
        used.append([n["file"] for n in nodes if n["type"] == "image"])
    assert used[0][1] == shared["id"]  # the organisation picture is referenced
    assert used[0][0] != own["id"] and used[0][0] == used[1][0]  # one new picture, shared by both copies
    copy_asset = db.get(FileAsset, uuid.UUID(used[0][0]))
    assert copy_asset is not None and copy_asset.project_id == uuid.UUID(target["id"]) and copy_asset.is_org_resource is False
    assert db.get(FileAsset, uuid.UUID(own["id"])).project_id == uuid.UUID(source["id"])


# ---- gates -----------------------------------------------------------------------------------------------------------


def test_the_target_needs_manage_and_the_source_needs_manage_and_access(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report")
    only_target = user_with_role(world, target, "project_manager")
    only_source = user_with_role(world, source, "project_manager")
    reader_of_source = user_with_role(world, source, "member")
    both = user_with_role(world, source, "project_manager")
    assert world.client.post(
        f"/api/v1/projects/{target['id']}/roles", json={"user_id": _me(world, both), "role": "project_manager"}, headers=auth_headers(world.token),
    ).status_code in (200, 201, 204)

    assert do_copy(world, source, target, token=only_target, layout_ids=[layout["id"]]).status_code == 404  # no access to the source
    assert do_copy(world, source, target, token=only_source, layout_ids=[layout["id"]]).status_code == 403  # no right in the target
    assert do_copy(world, source, target, token=reader_of_source, layout_ids=[layout["id"]]).status_code == 403
    assert "Report" not in listed(world, target)

    assert do_copy(world, source, target, token=both, layout_ids=[layout["id"]]).status_code == 200
    assert "Report" in listed(world, target)


def _me(world: World, token: str) -> str:
    return world.client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]


def test_a_source_that_is_viewable_but_not_manageable_is_403_and_one_nobody_can_see_is_404(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report")
    target_manager = user_with_role(world, target, "project_manager")

    assert do_copy(world, source, target, token=target_manager, layout_ids=[layout["id"]]).status_code == 404
    viewer = user_with_role(world, source, "member")
    assert world.client.post(
        f"/api/v1/projects/{target['id']}/roles", json={"user_id": _me(world, viewer), "role": "project_manager"}, headers=auth_headers(world.token),
    ).status_code in (200, 201, 204)
    assert do_copy(world, source, target, token=viewer, layout_ids=[layout["id"]]).status_code == 403


def test_another_organisation_or_an_unknown_project_is_404_and_nothing_is_revealed(client, admin_token, world):
    target = world.project("Target")
    other = World(client, admin_token, "Other Org")
    foreign = other.project("Foreign")
    foreign_layout = new_layout(other, foreign, "Secret")

    cross = do_copy(world, foreign, target, layout_ids=[foreign_layout["id"]])
    missing = world.client.post(
        copy_url(target), json={"source_project_id": str(uuid.uuid4())}, headers=auth_headers(world.token),
    )

    assert cross.status_code == 404 and missing.status_code == 404
    assert cross.json() == missing.json() | {"detail": cross.json()["detail"]} and "Secret" not in cross.text
    assert "Secret" not in listed(world, target)


def test_a_layout_the_source_cannot_reach_or_has_hidden_is_not_copied(world):
    source, target, elsewhere = world.project("Source"), world.project("Target"), world.project("Elsewhere")
    foreign = new_layout(world, elsewhere, "Not reachable")
    shared = new_layout(world, world, "Org wide")
    world.client.put(layouts_url(source, f"/{shared['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))

    assert do_copy(world, source, target, layout_ids=[foreign["id"]]).status_code == 404
    assert do_copy(world, source, target, layout_ids=[shared["id"]]).status_code == 404
    assert [n for n, row in listed(world, target).items() if row["origin"] == "project"] == []  # the org layout is only inherited


def test_the_same_project_too_many_items_and_an_archived_project_are_refused(world, db):
    source, target = world.project("Source"), world.project("Target")
    assert do_copy(world, source, source).status_code == 422
    assert do_copy(world, source, target, folders=[f"F{i}" for i in range(101)]).status_code == 422

    for project in (source, target):
        row = db.get(Project, uuid.UUID(project["id"]))
        row.is_archived = True
        db.commit()
        assert do_copy(world, source, target).status_code == 409
        row.is_archived = False
        db.commit()
    assert do_copy(world, source, target).status_code == 200


def test_the_target_list_has_only_unarchived_projects_the_caller_manages(world, db):
    source = world.project("Source")
    manageable, other, archived = world.project("Manageable"), world.project("Other"), world.project("Archived")
    token = user_with_role(world, source, "project_manager")
    assert world.client.post(
        f"/api/v1/projects/{manageable['id']}/roles", json={"user_id": _me(world, token), "role": "project_manager"},
        headers=auth_headers(world.token),
    ).status_code in (200, 201, 204)
    assert other and archived
    row = db.get(Project, uuid.UUID(archived["id"]))
    row.is_archived = True
    db.commit()

    mine = world.client.get(f"{copy_url(source)}/targets", headers=auth_headers(token)).json()
    admin = world.client.get(f"{copy_url(source)}/targets", headers=auth_headers(world.token)).json()

    assert [t["name"] for t in mine] == ["Manageable"]
    assert {t["name"] for t in admin} == {"Manageable", "Other"}
    plain = user_with_role(world, source, "member")
    assert world.client.get(f"{copy_url(source)}/targets", headers=auth_headers(plain)).status_code == 403


# ---- audit and bundles -----------------------------------------------------------------------------------------------


def test_one_audit_event_records_counts_and_ids_and_never_names_or_text(world, db):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Confidential name", body=tree("Secret text"))
    pack = new_pack(world, source, "Secret pack", "Confidential name")

    copied(world, source, target, layout_ids=[layout["id"]], pack_ids=[pack["id"]])

    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "reports_copied")).all()
    (event,) = (e for e in events if e.project_id == uuid.UUID(target["id"]))
    assert event.detail["layouts"] == 1 and event.detail["packs"] == 1 and event.detail["source_project_id"] == source["id"]
    assert "Confidential" not in json.dumps(event.detail) and "Secret" not in json.dumps(event.detail)


def test_the_copied_reports_survive_a_project_bundle_round_trip(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Handover", folder="Board")
    pack = new_pack(world, source, "Board pack", "Handover")
    copied(world, source, target, layout_ids=[layout["id"]], pack_ids=[pack["id"]])
    h = auth_headers(world.token)

    bundle = world.client.get(f"/api/v1/projects/{target['id']}/export", headers=h)
    assert bundle.status_code == 200
    assert {"report_layouts", "report_packs"} <= set(json.loads(zipfile.ZipFile(io.BytesIO(bundle.content)).read("project.json")))
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Restored"},
        files={"file": ("bundle.zip", bundle.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text

    restored = imported.json()["project"]
    assert imported.json()["warnings"] == []
    assert listed(world, restored)["Handover"]["folder"] == "Board"
    assert [e["name"] for e in world.client.get(
        packs_url(restored, f"/{listed(world, restored, 'packs')['Board pack']['id']}"), headers=h,
    ).json()["current"]["definition"]["entries"]] == ["Handover"]


def test_layouts_are_stored_only_for_the_target_project(world, db):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report")
    copied(world, source, target, layout_ids=[layout["id"]])
    rows = db.scalars(select(ReportLayout).where(ReportLayout.name == "Report", ReportLayout.organization_id == uuid.UUID(world.org["id"]))).all()
    assert sorted(str(r.project_id) for r in rows) == sorted([source["id"], target["id"]])
