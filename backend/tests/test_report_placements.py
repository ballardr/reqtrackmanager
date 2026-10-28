"""Tests for the Reports picker's organisation: author folders on layouts and packs (nested paths), placement overrides
(a folder and, for a module report, a hide) at the organisation and project tiers with nearest-wins resolution, the
catalogue they shape, the portable bundle form, and the sub-component gate for reports that span several sub-components.
Each test builds its own organisation.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest

from app.database import SessionLocal
from app.models.report_placement import ReportPlacement
from app.services.report_folders import MAX_FOLDER_DEPTH, clean_folder, imported_folder
from app.services.report_layout_tree import empty_tree
from app.services.report_pack_definition import PACK_SCHEMA_VERSION
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World

D1 = "report:decisions.d1"
SUMMARY = "report:context_strategy.r8"
CHANGE_HISTORY = "report:context_strategy.r7"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Placements Org", decisions=True, context_strategy=True)


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


def place(world: World, base: str, key: str, token: str | None = None, **body: Any):
    return world.client.put(f"{base}/report-placements", json={"report_key": key, **body}, headers=auth_headers(token or world.token))


def catalogue(world: World, base: str, token: str | None = None) -> dict[str, dict]:
    resp = world.client.get(f"{base}/report-catalogue", headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return {e["placement_key"]: e for e in resp.json()}


def by_key(world: World, base: str) -> dict[str, dict]:
    resp = world.client.get(f"{base}/report-placements", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return {row["report_key"]: row for row in resp.json()}


# ---- the folder rule ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [
    ("", ""), (None, ""), ("  Handover ", "Handover"), ("Handover / Quarterly", "Handover/Quarterly"),
    ("a//b/", "a/b"), ("Two   spaces", "Two spaces"), ("/".join(["x"] * MAX_FOLDER_DEPTH), "/".join(["x"] * MAX_FOLDER_DEPTH)),
])
def test_a_folder_path_is_tidied(raw, expected):
    assert clean_folder(raw) == expected


@pytest.mark.parametrize("raw", ["a/b/c/d", "x" * 41, "/".join(["x" * 40] * 3) + "/", "bad\x00name", "bad\x07name"])
def test_an_unusable_folder_is_refused(raw):
    if raw.endswith("/") and len(raw) < 120:
        pytest.skip("tidies to a valid path")
    with pytest.raises(ValueError):
        clean_folder(raw)


def test_an_imported_folder_that_is_invalid_is_dropped():
    assert imported_folder("a/b/c/d") == "" and imported_folder(5) == "" and imported_folder("Ok") == "Ok"


# ---- author folders on layouts and packs ----------------------------------------------------------------------


def test_a_layout_and_a_pack_keep_a_nested_folder_and_can_be_refiled(world):
    layout = new_layout(world, org_url(world), "L", folder="Handover / Quarterly")
    pack = new_pack(world, org_url(world), "P", folder="Handover")
    assert layout["folder"] == "Handover/Quarterly" and pack["folder"] == "Handover"
    h = auth_headers(world.token)
    moved = world.client.patch(org_url(world, f"/report-layouts/{layout['id']}"), json={"folder": "Archive"}, headers=h)
    assert moved.status_code == 200 and moved.json()["folder"] == "Archive"
    cleared = world.client.patch(org_url(world, f"/report-packs/{pack['id']}"), json={"folder": ""}, headers=h)
    assert cleared.json()["folder"] == ""
    untouched = world.client.patch(org_url(world, f"/report-layouts/{layout['id']}"), json={"name": "L2"}, headers=h)
    assert untouched.json()["folder"] == "Archive"  # a field left out is unchanged


def test_a_bad_folder_is_a_422(world):
    resp = world.client.post(
        org_url(world, "/report-layouts"),
        json={"name": "L", "family": "document", "tree": empty_tree("document"), "folder": "a/b/c/d"},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 422


def test_the_catalogue_files_a_custom_report_by_its_folder_and_tells_a_sheet_from_a_report(world):
    project = world.project("Alpha")
    new_layout(world, org_url(world), "Filed", folder="Handover/Quarterly")
    new_layout(world, org_url(world), "Loose")
    sheet = world.client.post(
        org_url(world, "/report-layouts"), json={"name": "Rows", "family": "table", "tree": empty_tree("table")},
        headers=auth_headers(world.token),
    )
    assert sheet.status_code == 201, sheet.text
    entries = {e["title"]: e for e in catalogue(world, project_url(project)).values()}
    assert entries["Filed"]["folder"] == "Handover/Quarterly" and entries["Filed"]["kind"] == "report"
    assert entries["Loose"]["folder"] == "Custom reports"
    assert entries["Rows"]["kind"] == "sheet"
    assert entries["Decision register"]["folder"] == entries["Decision register"]["module_name"]


# ---- placements -----------------------------------------------------------------------------------------------


def test_an_organisation_placement_moves_and_hides_a_module_report_for_its_projects(world):
    project = world.project("Alpha")
    assert place(world, org_url(world), D1, folder="Governance/Decisions", hidden=None).status_code == 200
    assert catalogue(world, project_url(project))[D1]["folder"] == "Governance/Decisions"

    assert place(world, org_url(world), D1, hidden=True).status_code == 200
    assert D1 not in catalogue(world, project_url(project))
    listed = by_key(world, org_url(world))[D1]
    assert listed["hidden"] is True and listed["own_hidden"] is True and listed["folder"] == "Governance/Decisions"

    assert place(world, org_url(world), D1, hidden=None, folder=None).status_code == 200  # both cleared: back to default
    restored = catalogue(world, project_url(project))[D1]
    assert restored["folder"] == restored["module_name"]


def test_a_project_overrides_what_its_ancestors_and_the_organisation_set_nearest_first(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    place(world, org_url(world), D1, folder="Org folder", hidden=True)
    assert D1 not in catalogue(world, project_url(child))

    assert place(world, project_url(parent), D1, folder="Parent folder").status_code == 200
    seen = by_key(world, project_url(child))[D1]
    assert (seen["folder"], seen["folder_from"], seen["hidden"], seen["hidden_from"]) == ("Parent folder", "ancestor", True, "organization")

    assert place(world, project_url(child), D1, hidden=False, folder="Own folder").status_code == 200
    shown = catalogue(world, project_url(child))[D1]
    assert shown["folder"] == "Own folder"  # the project shows what the organisation hid
    sibling = world.project("Sibling")
    assert D1 not in catalogue(world, project_url(sibling))  # another project still follows the organisation


def test_the_requirements_report_and_the_record_list_can_be_placed(world):
    project = world.project("Alpha")
    assert place(world, project_url(project), "report:platform.requirements", folder="Core").status_code == 200
    resolved = world.client.get(project_url(project, "/report-placements/resolved"), headers=auth_headers(world.token)).json()
    assert resolved == [{"report_key": "report:platform.requirements", "folder": "Core", "hidden": False}]


def test_a_layout_or_pack_can_be_moved_but_not_hidden_by_a_placement(world):
    project = world.project("Alpha")
    layout = new_layout(world, org_url(world), "L")
    pack = new_pack(world, org_url(world), "P")
    key = f"layout:{layout['id']}"
    assert place(world, project_url(project), key, folder="Mine").status_code == 200
    assert catalogue(world, project_url(project))[key]["folder"] == "Mine"
    assert place(world, project_url(project), key, hidden=True).status_code == 422
    assert place(world, project_url(project), f"pack:{pack['id']}", folder="Mine").status_code == 200
    resolved = {r["report_key"]: r for r in world.client.get(project_url(project, "/report-placements/resolved"), headers=auth_headers(world.token)).json()}
    assert resolved[f"pack:{pack['id']}"]["folder"] == "Mine"


def test_an_unknown_report_or_a_bad_folder_is_a_422_and_nothing_is_stored(world, db):
    assert place(world, org_url(world), "report:nope.x", folder="A").status_code == 422
    assert place(world, org_url(world), D1, folder="a/b/c/d").status_code == 422
    assert db.query(ReportPlacement).filter(ReportPlacement.organization_id == world.org["id"]).count() == 0


def test_only_a_manager_of_layouts_may_place_but_a_member_reads_the_result(world):
    project = world.project("Alpha")
    member_id = create_org_user(world.client, world.token, world.org["id"], "placemember@example.com")
    world.client.post(project_url(project, "/roles"), json={"user_id": member_id, "role": "member"}, headers=auth_headers(world.token))
    token = login(world.client, "placemember@example.com", "Password123!")
    assert place(world, project_url(project), D1, token=token, folder="X").status_code == 403
    assert world.client.get(project_url(project, "/report-placements"), headers=auth_headers(token)).status_code == 403
    place(world, project_url(project), D1, folder="Seen")
    assert catalogue(world, project_url(project), token)[D1]["folder"] == "Seen"
    assert world.client.get(project_url(project, "/report-placements/resolved"), headers=auth_headers(token)).status_code == 200


def test_a_placement_is_audited_without_anything_but_the_key_and_values(world, db):
    from app.models.audit import AuditEvent

    place(world, org_url(world), D1, folder="Audit", hidden=True)
    event = db.query(AuditEvent).filter(AuditEvent.entity_type == "report_placement").order_by(AuditEvent.created_at.desc()).first()
    assert event is not None and event.action == "set"
    assert event.detail == {"report_key": D1, "folder": "Audit", "hidden": True}


def test_deleting_a_layout_or_a_pack_removes_its_placements(world, db):
    project = world.project("Alpha")
    layout = new_layout(world, org_url(world), "L")
    pack = new_pack(world, org_url(world), "P")
    place(world, project_url(project), f"layout:{layout['id']}", folder="A")
    place(world, project_url(project), f"pack:{pack['id']}", folder="A")
    h = auth_headers(world.token)
    assert world.client.delete(org_url(world, f"/report-layouts/{layout['id']}"), headers=h).status_code == 204
    assert world.client.delete(org_url(world, f"/report-packs/{pack['id']}"), headers=h).status_code == 204
    assert db.query(ReportPlacement).filter(ReportPlacement.organization_id == world.org["id"]).count() == 0


def test_a_hidden_module_report_still_runs_on_its_route(world):
    project = world.project("Alpha")
    path = catalogue(world, project_url(project))[D1]["path"]
    place(world, org_url(world), D1, hidden=True)
    assert D1 not in catalogue(world, project_url(project))
    run = world.client.get(f"{path}?format=json", headers=auth_headers(world.token))
    assert run.status_code == 200, run.text  # tidying, not access


# ---- reports that span sub-components -------------------------------------------------------------------------


def test_a_report_spanning_sub_components_is_offered_until_all_of_them_are_off(world, client):
    project = world.project("Alpha")
    before = catalogue(world, project_url(project))
    assert {SUMMARY, CHANGE_HISTORY} <= set(before)
    history_path = before[CHANGE_HISTORY]["path"]

    def switch(key: str, enabled: bool) -> None:
        resp = client.put(
            org_url(world, f"/modules/context_strategy/subcomponents/{key}"), json={"enabled": enabled},
            headers=auth_headers(world.token),
        )
        assert resp.status_code == 200, resp.text

    for key in ("strategy", "future_state"):
        switch(key, False)
    seen = catalogue(world, project_url(project))
    assert CHANGE_HISTORY in seen and SUMMARY in seen  # one sub-component it spans is still on
    switch("guiding_principle", False)
    seen = catalogue(world, project_url(project))
    assert CHANGE_HISTORY not in seen and SUMMARY in seen  # change history spans only those three
    for key in ("pain_point", "open_question"):
        switch(key, False)
    assert SUMMARY not in catalogue(world, project_url(project))
    gone = world.client.get(f"{history_path}?format=json", headers=auth_headers(world.token))
    assert gone.status_code == 404


# ---- bundles --------------------------------------------------------------------------------------------------


def rewrite(bundle: bytes, member: str, edit) -> bytes:
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


def import_project(world: World, bundle: bytes) -> dict:
    resp = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Imported"},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_project_bundle_round_trips_folders_and_placements_by_name(world):
    source = world.project("Source")
    h = auth_headers(world.token)
    own = new_layout(world, project_url(source), "Own layout", folder="Handover/Quarterly")
    inherited = new_layout(world, org_url(world), "Shared layout")
    pack = new_pack(world, project_url(source), "Own pack", folder="Packs")
    place(world, project_url(source), D1, folder="Governance", hidden=True)
    place(world, project_url(source), f"layout:{inherited['id']}", folder="Moved")
    place(world, project_url(source), f"pack:{pack['id']}", folder="Elsewhere")
    bundle = world.client.get(project_url(source, "/export"), headers=h).content

    result = import_project(world, bundle)

    assert result["warnings"] == []
    copy = result["project"]
    entries = catalogue(world, project_url(copy))
    assert D1 not in entries  # the hide travelled
    resolved = {r["report_key"]: r for r in world.client.get(project_url(copy, "/report-placements/resolved"), headers=h).json()}
    assert resolved[D1] == {"report_key": D1, "folder": "Governance", "hidden": True}
    assert resolved[f"layout:{inherited['id']}"]["folder"] == "Moved"  # an inherited layout, found by name
    imported_pack = next(p for p in world.client.get(project_url(copy, "/report-packs"), headers=h).json() if p["name"] == "Own pack")
    assert imported_pack["folder"] == "Packs"
    assert resolved[f"pack:{imported_pack['id']}"]["folder"] == "Elsewhere"
    layouts = {x["name"]: x for x in world.client.get(project_url(copy, "/report-layouts"), headers=h).json()}
    assert layouts["Own layout"]["folder"] == "Handover/Quarterly" and layouts["Own layout"]["id"] != own["id"]


def test_a_bundle_placement_that_names_nothing_here_is_reported_and_a_bad_folder_is_dropped(world):
    source = world.project("Source")
    place(world, project_url(source), D1, folder="Fine")
    bundle = world.client.get(project_url(source, "/export"), headers=auth_headers(world.token)).content

    def corrupt(data: dict) -> None:
        data["report_placements"] = [
            {"report": "decisions.d1", "folder": "a/b/c/d", "hidden": None},
            {"report": "no_module.x", "folder": "X"},
            {"layout": "Missing layout", "folder": "X"},
            {"report": "decisions.d1", "folder": "Kept", "hidden": None},
        ]

    result = import_project(world, rewrite(bundle, "project.json", corrupt))

    assert len([w for w in result["warnings"] if "placement" in w]) == 2
    resolved = {r["report_key"]: r for r in world.client.get(
        project_url(result["project"], "/report-placements/resolved"), headers=auth_headers(world.token)).json()}
    assert resolved[D1]["folder"] == "Kept"


def test_an_organisation_bundle_round_trips_folders_and_placements(client, admin_token):
    source = World(client, admin_token, "Placement Source", decisions=True)
    h = auth_headers(source.token)
    new_layout(source, org_url(source), "Org layout", folder="A/B")
    pack = new_pack(source, org_url(source), "Org pack", folder="C")
    place(source, org_url(source), D1, folder="Gov", hidden=True)
    place(source, org_url(source), f"pack:{pack['id']}", folder="D")
    bundle = client.get(org_url(source, "/export"), headers=h).content

    resp = client.post(
        "/api/v1/orgs/import", data={"name": "Placement Copy"}, files={"file": ("bundle.zip", bundle, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    copy_id = resp.json()["organization"]["id"]
    copy_headers = h
    placements = {r["report_key"]: r for r in client.get(f"/api/v1/orgs/{copy_id}/report-placements/resolved", headers=copy_headers).json()}
    assert placements[D1]["folder"] == "Gov" and placements[D1]["hidden"] is True
    layouts = client.get(f"/api/v1/orgs/{copy_id}/report-layouts", headers=copy_headers).json()
    assert [(x["name"], x["folder"]) for x in layouts] == [("Org layout", "A/B")]
    copied_pack = client.get(f"/api/v1/orgs/{copy_id}/report-packs", headers=copy_headers).json()[0]
    assert placements[f"pack:{copied_pack['id']}"]["folder"] == "D"
