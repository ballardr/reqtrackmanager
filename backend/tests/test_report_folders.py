"""Tests for the Reports picker's folder list: adding a folder before anything is filed in it, the union with folders in
use, nested projects (additive), rename and delete (what is filed moves, no report is deleted), ownership, audit and the
bundle round trip. Each test builds its own organisation.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.services.report_layout_tree import empty_tree
from app.services.report_pack_definition import PACK_SCHEMA_VERSION
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World

D1 = "report:decisions.d1"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Folders Org", decisions=True, context_strategy=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def org_url(world: World, suffix: str = "") -> str:
    return f"/api/v1/orgs/{world.org['id']}{suffix}"


def project_url(project: dict, suffix: str = "") -> str:
    return f"/api/v1/projects/{project['id']}{suffix}"


def new_layout(world: World, base: str, name: str, **extra: Any) -> dict:
    resp = world.client.post(
        f"{base}/report-layouts", json={"name": name, "family": "document", "tree": empty_tree("document"), **extra},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def new_pack(world: World, base: str, name: str, **extra: Any) -> dict:
    resp = world.client.post(
        f"{base}/report-packs", json={"name": name, "definition": {"schema_version": PACK_SCHEMA_VERSION, "entries": []}, **extra},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def folders(world: World, base: str, token: str | None = None) -> dict[str, bool]:
    resp = world.client.get(f"{base}/report-folders", headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return {f["path"]: f["own"] for f in resp.json()}


def add(world: World, base: str, path: str, token: str | None = None):
    return world.client.post(f"{base}/report-folders", json={"path": path}, headers=auth_headers(token or world.token))


def rename(world: World, base: str, path: str, name: str):
    return world.client.patch(f"{base}/report-folders", json={"path": path, "name": name}, headers=auth_headers(world.token))


def remove(world: World, base: str, path: str):
    return world.client.delete(f"{base}/report-folders", params={"path": path}, headers=auth_headers(world.token))


def layout_folder(world: World, base: str, layout_id: str) -> str:
    resp = world.client.get(f"{base}/report-layouts", headers=auth_headers(world.token))
    return next(x["folder"] for x in resp.json() if x["id"] == layout_id)


def test_an_added_folder_exists_with_nothing_filed_in_it_and_its_levels_are_listed(world):
    base = org_url(world)
    assert add(world, base, " Handover / Quarterly ").status_code == 201
    listed = folders(world, base)
    assert listed["Handover"] and listed["Handover/Quarterly"]  # own, with the level above


def test_a_folder_in_use_is_listed_without_being_added(world):
    new_layout(world, org_url(world), "L", folder="Archive/2026")
    assert folders(world, org_url(world))["Archive/2026"] is True


@pytest.mark.parametrize("path", ["", "   ", "a/b/c/d", "x" * 41])
def test_an_unusable_folder_is_a_422(world, path):
    assert add(world, org_url(world), path).status_code == 422


def test_a_duplicate_folder_is_refused_case_insensitively(world):
    base = org_url(world)
    assert add(world, base, "Handover").status_code == 201
    assert add(world, base, "handover").status_code == 422
    new_layout(world, base, "L", folder="Used")
    assert add(world, base, "USED").status_code == 422  # a folder in use counts


def test_a_project_sees_its_ancestors_and_the_organisations_folders_but_owns_only_its_own(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    add(world, org_url(world), "Org folder")
    add(world, project_url(parent), "Parent folder")
    add(world, project_url(child), "Child folder")
    seen = folders(world, project_url(child))
    assert seen == {"Org folder": False, "Parent folder": False, "Child folder": True}
    assert folders(world, project_url(parent)) == {"Org folder": False, "Parent folder": True}
    sibling = world.project("Sibling")
    assert folders(world, project_url(sibling)) == {"Org folder": False}


def test_a_scope_cannot_rename_or_delete_a_folder_it_does_not_own(world):
    project = world.project("P")
    add(world, org_url(world), "Org folder")
    assert rename(world, project_url(project), "Org folder", "Mine").status_code == 404
    assert remove(world, project_url(project), "Org folder").status_code == 404
    assert "Org folder" in folders(world, org_url(world))


def test_renaming_a_folder_moves_what_is_filed_in_it_and_below(world):
    base = org_url(world)
    layout = new_layout(world, base, "L", folder="Old/Sub")
    pack = new_pack(world, base, "P", folder="Old")
    world.client.put(f"{base}/report-placements", json={"report_key": D1, "folder": "Old/Sub/Deep"}, headers=auth_headers(world.token))
    add(world, base, "Old/Empty")

    resp = rename(world, base, "Old", "New")

    body = resp.json()
    assert resp.status_code == 200 and body["path"] == "New"
    assert (body["layouts"], body["packs"], body["placements"]) == (1, 1, 1)
    assert set(f["path"] for f in body["folders"]) == {"New", "New/Sub", "New/Sub/Deep", "New/Empty"}
    assert layout_folder(world, base, layout["id"]) == "New/Sub"
    packs = world.client.get(f"{base}/report-packs", headers=auth_headers(world.token)).json()
    assert next(p for p in packs if p["id"] == pack["id"])["folder"] == "New"


def test_renaming_to_a_name_a_sibling_has_is_refused_and_a_separator_is_not_a_name(world):
    base = org_url(world)
    add(world, base, "A")
    add(world, base, "B")
    assert rename(world, base, "A", "b").status_code == 422
    assert rename(world, base, "A", "x/y").status_code == 422
    assert rename(world, base, "A", "a").status_code == 200  # a change of case only


def test_deleting_a_folder_moves_its_contents_up_one_level_and_deletes_no_report(world):
    base = org_url(world)
    inside = new_layout(world, base, "Inside", folder="Top/Mid")
    below = new_layout(world, base, "Below", folder="Top/Mid/Leaf")
    beside = new_layout(world, base, "Beside", folder="Top")
    add(world, base, "Top/Mid/Empty")

    resp = remove(world, base, "Top/Mid")

    body = resp.json()
    assert resp.status_code == 200 and (body["layouts"], body["packs"], body["placements"]) == (2, 0, 0)
    assert layout_folder(world, base, inside["id"]) == "Top"
    assert layout_folder(world, base, below["id"]) == "Top/Leaf"
    assert layout_folder(world, base, beside["id"]) == "Top"
    assert set(f["path"] for f in body["folders"]) == {"Top", "Top/Leaf", "Top/Empty"}


def test_deleting_a_first_level_folder_files_its_contents_at_the_top_level(world):
    base = org_url(world)
    layout = new_layout(world, base, "L", folder="Only")
    pack = new_pack(world, base, "P", folder="Only/Sub")
    assert remove(world, base, "Only").status_code == 200
    assert layout_folder(world, base, layout["id"]) == ""
    packs = world.client.get(f"{base}/report-packs", headers=auth_headers(world.token)).json()
    assert next(p for p in packs if p["id"] == pack["id"])["folder"] == "Sub"
    assert "Only" not in folders(world, base)


def test_a_project_deleting_a_folder_moves_only_its_own_reports(world):
    project = world.project("P")
    shared = new_layout(world, org_url(world), "Shared", folder="Both")
    mine = new_layout(world, project_url(project), "Mine", folder="Both")
    assert remove(world, project_url(project), "Both").status_code == 200
    assert layout_folder(world, project_url(project), mine["id"]) == ""
    assert layout_folder(world, org_url(world), shared["id"]) == "Both"
    assert folders(world, project_url(project)) == {"Both": False}  # still offered: the organisation files under it


def test_only_a_manager_of_layouts_may_change_folders(world):
    project = world.project("Alpha")
    member_id = create_org_user(world.client, world.token, world.org["id"], "foldermember@example.com")
    world.client.post(project_url(project, "/roles"), json={"user_id": member_id, "role": "member"}, headers=auth_headers(world.token))
    token = login(world.client, "foldermember@example.com", "Password123!")
    assert add(world, project_url(project), "X", token=token).status_code == 403
    assert world.client.get(project_url(project, "/report-folders"), headers=auth_headers(token)).status_code == 403
    assert world.client.delete(project_url(project, "/report-folders"), params={"path": "X"}, headers=auth_headers(token)).status_code == 403


def test_a_folder_change_is_audited_with_paths_and_counts_only(world, db):
    base = org_url(world)
    new_layout(world, base, "Secret title", folder="A")
    add(world, base, "A/B")
    rename(world, base, "A", "C")
    remove(world, base, "C")
    events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "report_folder", AuditEvent.organization_id == world.org["id"])).all()
    assert sorted(e.action for e in events) == ["create", "delete", "rename"]
    assert all("Secret title" not in json.dumps(e.detail) for e in events)


def test_deleting_the_project_removes_its_folders(world, db):
    from sqlalchemy import delete, text

    from app.models.project import Project
    from app.models.report_folder import ReportFolder

    project = world.project("Gone")
    add(world, project_url(project), "Temp")
    assert db.scalars(select(ReportFolder).where(ReportFolder.project_id == project["id"])).first() is not None
    db.execute(text("SET session_replication_role = DEFAULT"))
    db.execute(delete(Project).where(Project.id == project["id"]))
    db.flush()
    assert db.scalars(select(ReportFolder).where(ReportFolder.project_id == project["id"])).first() is None


# ---- bundles --------------------------------------------------------------------------------------------------


def test_a_project_bundle_round_trips_added_folders_and_skips_ones_it_already_lists(world):
    source = world.project("Source")
    add(world, org_url(world), "Org folder")
    add(world, project_url(source), "Empty/Nested")
    add(world, project_url(source), "Second")
    bundle = world.client.get(project_url(source, "/export"), headers=auth_headers(world.token)).content

    def corrupt(data: dict) -> None:
        data["report_folders"] += ["a/b/c/d", 5, "org folder"]

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "project.json":
                parsed = json.loads(data)
                corrupt(parsed)
                data = json.dumps(parsed).encode()
            dst.writestr(item, data)
    resp = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Imported"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    copy = resp.json()
    assert len([w for w in copy["warnings"] if "folder" in w]) == 2  # the bad path and the non-string
    assert folders(world, project_url(copy["project"])) == {
        "Org folder": False, "Empty": True, "Empty/Nested": True, "Second": True,
    }


def test_an_organisation_bundle_round_trips_added_folders(client, admin_token):
    source = World(client, admin_token, "Folder Source")
    add(source, org_url(source), "Handover/Quarterly")
    bundle = client.get(org_url(source, "/export"), headers=auth_headers(source.token)).content
    resp = client.post(
        "/api/v1/orgs/import", data={"name": "Folder Copy"}, files={"file": ("bundle.zip", bundle, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    copy_id = resp.json()["organization"]["id"]
    listed = client.get(f"/api/v1/orgs/{copy_id}/report-folders", headers=auth_headers(source.token)).json()
    assert {f["path"] for f in listed} == {"Handover", "Handover/Quarterly"}
