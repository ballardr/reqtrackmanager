"""Tests for duplicating one report layout or pack (`routers.report_duplicate`, `services.report_duplicate`): sources (own,
inherited, hidden, built-in starter), what is copied (latest version as version 1, independent, always editable), names
(suggested, taken, shadowing), tiers (project, copy up to the organisation) with the picture rule, folders, packs without
saved sets, the dry run, the gates (manage here, manage the organisation to copy up, one organisation, archived), the
audit event and the bundle. Each test builds its own organisation.
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
from app.services.report_layout_tree import empty_tree
from app.services.report_starters import STARTERS
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Duplicate Org")


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


def base(owner: dict | World) -> str:
    return f"/api/v1/orgs/{owner.org['id']}" if isinstance(owner, World) else f"/api/v1/projects/{owner['id']}"


def new_layout(world: World, owner: dict | World, name: str, body: dict | None = None, folder: str = "") -> dict:
    resp = world.client.post(
        f"{base(owner)}/report-layouts",
        json={"name": name, "description": "about " + name, "family": "document", "folder": folder, "tree": body or tree(name)},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def new_pack(world: World, owner: dict | World, name: str, *layout_names: str) -> dict:
    definition: dict[str, Any] = {"schema_version": 1, "entries": [{"kind": "layout", "name": n, "format": "pdf"} for n in layout_names]}
    resp = world.client.post(
        f"{base(owner)}/report-packs", json={"name": name, "description": "d", "definition": definition}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def do_dup(world: World, owner: dict | World, *, token: str | None = None, **body: Any):
    body.setdefault("target", "organization" if isinstance(owner, World) else "project")
    return world.client.post(f"{base(owner)}/report-duplicate", json=body, headers=auth_headers(token or world.token))


def duplicated(world: World, owner: dict | World, **body: Any) -> dict:
    resp = do_dup(world, owner, **body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def listed(world: World, owner: dict | World, kind: str = "layouts") -> dict[str, dict]:
    resp = world.client.get(f"{base(owner)}/report-{kind}", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return {row["name"]: row for row in resp.json()}


def detail(world: World, owner: dict | World, layout_id: str) -> dict:
    return world.client.get(f"{base(owner)}/report-layouts/{layout_id}", headers=auth_headers(world.token)).json()


def user_with_role(world: World, project: dict, role: str) -> str:
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


def upload(world: World, url: str, name: str, colour: str) -> dict:
    return world.client.post(url, files={"file": (name, png(colour), "image/png")}, headers=auth_headers(world.token)).json()


def picture(file_id: str) -> dict:
    return {"type": "image", "file": file_id, "alt": "A picture"}


# ---- what is copied ------------------------------------------------------------------------------------------------


def test_a_shared_layout_becomes_the_projects_own_editable_copy_of_its_latest_version(world):
    project = world.project("Work")
    shared = new_layout(world, world, "Handover", body=tree("First"), folder="Board")
    world.client.put(
        f"{base(world)}/report-layouts/{shared['id']}/tree", json={"tree": tree("Second"), "base_version": 1, "comment": "retitle"},
        headers=auth_headers(world.token),
    )

    plan = duplicated(world, project, kind="layout", source_id=shared["id"], dry_run=True)
    assert plan["suggested_name"] == "Handover (copy)" and plan["name"] == "Handover (copy)" and plan["new_id"] is None
    assert plan["origin"] == "organization" and "Handover (copy)" not in listed(world, project)

    result = duplicated(world, project, kind="layout", source_id=shared["id"])

    made = listed(world, project)["Handover (copy)"]
    assert result["new_id"] == made["id"] and made["origin"] == "project" and made["editable"] is True
    assert made["current_version"] == 1 and made["description"] == "about Handover" and made["folder"] == "Board"
    got = detail(world, project, made["id"])
    assert got["current"]["tree"] == tree("Second") and got["current"]["comment"] == "Copied from Handover, version 2"
    # independent both ways
    world.client.put(
        f"{base(project)}/report-layouts/{made['id']}/tree", json={"tree": tree("Edited"), "base_version": 1},
        headers=auth_headers(world.token),
    )
    assert detail(world, world, shared["id"])["current"]["tree"] == tree("Second")


def test_the_variables_and_default_file_name_travel_with_the_tree(world):
    project = world.project("Work")
    variables = [{"name": "who", "type": "text", "label": "Who", "default": "Everyone"}]
    body = {**tree("T"), "variables": variables, "file_name": "{{project_name}}-report"}
    shared = new_layout(world, world, "Parametrised", body=body)
    made = duplicated(world, project, kind="layout", source_id=shared["id"], name="Mine")
    got = detail(world, project, made["new_id"])["current"]["tree"]
    assert got["variables"] == variables and got["file_name"] == "{{project_name}}-report"


def test_an_inherited_layout_from_a_parent_project_and_a_hidden_one_can_be_duplicated(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    inherited = new_layout(world, parent, "From parent")
    hidden = new_layout(world, world, "Hidden one")
    world.client.put(f"{base(child)}/report-layouts/{hidden['id']}/visibility", json={"hidden": True}, headers=auth_headers(world.token))

    assert duplicated(world, child, kind="layout", source_id=inherited["id"])["name"] == "From parent (copy)"
    assert duplicated(world, child, kind="layout", source_id=hidden["id"])["name"] == "Hidden one (copy)"
    assert listed(world, child)["From parent (copy)"]["origin"] == "project"


def test_a_built_in_starter_is_a_source_even_after_the_organisations_own_copy_is_gone(client, admin_token):
    world = World(client, admin_token, "Starter Org")  # starters are removed from the organisation
    project = world.project("Work")
    keys = {s["key"]: s for s in client.get(f"{base(project)}/report-duplicate/starters", headers=auth_headers(world.token)).json()}
    assert {s.key for s in STARTERS} == set(keys)
    key = STARTERS[0].key
    assert STARTERS[0].name not in listed(world, project)

    plan = duplicated(world, project, kind="starter", starter_key=key, dry_run=True)
    assert plan["name"] == STARTERS[0].name and plan["origin"] == "starter"
    result = duplicated(world, project, kind="starter", starter_key=key, name="Our BRD")

    made = listed(world, project)["Our BRD"]
    assert made["origin"] == "project" and made["family"] == "document" and made["current_version"] == 1
    got = detail(world, project, result["new_id"])
    assert got["current"]["tree"]["nodes"] and "Copied from the built-in starter" in got["current"]["comment"]
    assert do_dup(world, project, kind="starter", starter_key="nope").status_code == 404
    assert do_dup(world, project, kind="starter").status_code == 422


def test_a_starter_can_be_copied_into_the_organisation_too(client, admin_token):
    world = World(client, admin_token, "Starter Org 2")
    result = duplicated(world, world, kind="starter", starter_key=STARTERS[1].key)
    assert result["name"] == STARTERS[1].name and result["new_id"] in {r["id"] for r in listed(world, world).values()}


# ---- names ---------------------------------------------------------------------------------------------------------


def test_names_count_up_a_name_the_project_owns_is_refused_and_one_it_inherits_is_a_shadow(world):
    project = world.project("Work")
    shared = new_layout(world, world, "Report")
    own = new_layout(world, project, "Mine")

    assert duplicated(world, project, kind="layout", source_id=shared["id"])["name"] == "Report (copy)"
    assert duplicated(world, project, kind="layout", source_id=shared["id"])["name"] == "Report (copy 2)"
    taken = do_dup(world, project, kind="layout", source_id=own["id"], name="mine")
    assert taken.status_code == 409
    plan = duplicated(world, project, kind="layout", source_id=own["id"], name="report", dry_run=True)
    assert plan["shadows"] is True and plan["name_taken"] is False and any("shadow" in w for w in plan["warnings"])
    assert duplicated(world, project, kind="layout", source_id=own["id"], name="Report")["shadows"] is True
    assert listed(world, project)["Report"]["origin"] == "project"
    assert do_dup(world, project, kind="layout", source_id=own["id"], name=" ").status_code == 200  # blank = suggestion
    assert do_dup(world, project, kind="layout", source_id=own["id"], name="x" * 201).status_code == 422


# ---- tiers, pictures and folders -----------------------------------------------------------------------------------


def test_copying_up_needs_the_organisation_right_and_a_project_picture_blocks_it(world, db):
    project = world.project("Work")
    other = world.project("Other")
    org_picture = upload(world, f"{base(world)}/report-images", "shared.png", "blue")
    own_picture = upload(world, f"{base(project)}/report-images", "own.png", "red")
    plain = new_layout(world, project, "Plain", body=tree("p", picture(org_picture["id"])), folder="Local")
    with_own = new_layout(world, project, "With own", body=tree("q", picture(own_picture["id"])))
    manager = user_with_role(world, project, "project_manager")
    assert other

    assert do_dup(world, project, token=manager, kind="layout", source_id=plain["id"], target="organization").status_code == 403
    assert do_dup(world, project, token=manager, kind="layout", source_id=plain["id"], target="project").status_code == 200

    blocked_plan = duplicated(world, project, kind="layout", source_id=with_own["id"], target="organization", dry_run=True)
    assert blocked_plan["blocked_images"] == ["own.png"]
    blocked = do_dup(world, project, kind="layout", source_id=with_own["id"], target="organization")
    assert blocked.status_code == 409 and blocked.json()["detail"]["images"] == ["own.png"]
    assert "With own (copy)" not in listed(world, world)

    up = duplicated(world, project, kind="layout", source_id=plain["id"], target="organization")
    org_row = listed(world, world)[up["name"]]
    assert org_row["project_id"] is None and org_row["origin"] == "organization"
    assert detail(world, world, org_row["id"])["current"]["tree"]["nodes"][1]["file"] == org_picture["id"]
    assert org_row["folder"] == "" and any("folder" in w for w in up["warnings"])  # "Local" is the project's own folder


def test_a_project_picture_is_reused_in_the_same_project_and_copied_into_a_child_projects_library(world, db):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    pic = upload(world, f"{base(parent)}/report-images", "p.png", "green")
    shared_pic = upload(world, f"{base(world)}/report-images", "s.png", "blue")
    layout = new_layout(world, parent, "Has pictures", body=tree("t", picture(pic["id"]), picture(shared_pic["id"])))

    same = duplicated(world, parent, kind="layout", source_id=layout["id"])
    files = [n["file"] for n in detail(world, parent, same["new_id"])["current"]["tree"]["nodes"] if n["type"] == "image"]
    assert files == [pic["id"], shared_pic["id"]] and not any("picture" in w for w in same["warnings"])

    plan = duplicated(world, child, kind="layout", source_id=layout["id"], dry_run=True)
    assert any("1 picture" in w for w in plan["warnings"])
    down = duplicated(world, child, kind="layout", source_id=layout["id"])
    files = [n["file"] for n in detail(world, child, down["new_id"])["current"]["tree"]["nodes"] if n["type"] == "image"]
    assert files[1] == shared_pic["id"] and files[0] != pic["id"]
    copy_asset = db.get(FileAsset, uuid.UUID(files[0]))
    assert copy_asset is not None and copy_asset.project_id == uuid.UUID(child["id"])
    assert db.get(FileAsset, uuid.UUID(pic["id"])).project_id == uuid.UUID(parent["id"])


def test_an_organisation_layout_is_duplicated_on_the_organisation_page(world):
    shared = new_layout(world, world, "Org report")
    result = duplicated(world, world, kind="layout", source_id=shared["id"])
    assert result["name"] == "Org report (copy)" and result["target"] == "organization"
    assert do_dup(world, world, kind="layout", source_id=shared["id"], target="project").status_code == 422
    project = world.project("Work")
    in_project = new_layout(world, project, "Project one")
    assert do_dup(world, world, kind="layout", source_id=in_project["id"]).status_code == 404  # not the organisation's own


# ---- packs ---------------------------------------------------------------------------------------------------------


def test_a_pack_is_copied_without_its_saved_sets_and_warns_when_a_copy_up_loses_its_layouts(world):
    project = world.project("Work")
    new_layout(world, project, "Monthly")
    pack = new_pack(world, project, "Board pack", "Monthly")
    world.client.post(
        f"{base(project)}/report-packs/{pack['id']}/sets", json={"name": "Q1", "values": {}}, headers=auth_headers(world.token),
    )

    same = duplicated(world, project, kind="pack", source_id=pack["id"])
    made = listed(world, project, "packs")[same["name"]]
    got = world.client.get(f"{base(project)}/report-packs/{made['id']}", headers=auth_headers(world.token)).json()
    assert same["name"] == "Board pack (copy)" and [e["name"] for e in got["current"]["definition"]["entries"]] == ["Monthly"]
    assert world.client.get(f"{base(project)}/report-packs/{made['id']}/sets", headers=auth_headers(world.token)).json() == []
    assert same["warnings"] == []

    up = duplicated(world, project, kind="pack", source_id=pack["id"], target="organization")
    assert any("Monthly" in w for w in up["warnings"])
    assert up["name"] in listed(world, world, "packs")


# ---- gates and audit -----------------------------------------------------------------------------------------------


def test_the_duplicate_needs_manage_and_reaches_only_what_the_scope_sees(client, admin_token, world, db):
    project, elsewhere = world.project("Work"), world.project("Elsewhere")
    layout = new_layout(world, project, "Report")
    foreign_layout = new_layout(world, elsewhere, "Not reachable")
    member = user_with_role(world, project, "member")
    manager = user_with_role(world, project, "project_manager")

    assert do_dup(world, project, token=member, kind="layout", source_id=layout["id"]).status_code == 403
    assert do_dup(world, project, token=manager, kind="layout", source_id=layout["id"]).status_code == 200
    assert do_dup(world, project, kind="layout", source_id=foreign_layout["id"]).status_code == 404
    assert do_dup(world, project, kind="layout", source_id=str(uuid.uuid4())).status_code == 404
    assert do_dup(world, project, kind="layout").status_code == 404

    other = World(client, admin_token, "Other Org")
    foreign = other.project("Foreign")
    secret = new_layout(other, foreign, "Secret")
    cross = do_dup(world, project, kind="layout", source_id=secret["id"])
    assert cross.status_code == 404 and "Secret" not in cross.text

    row = db.get(Project, uuid.UUID(project["id"]))
    row.is_archived = True
    db.commit()
    assert do_dup(world, project, kind="layout", source_id=layout["id"]).status_code == 409
    row.is_archived = False
    db.commit()


def test_one_audit_event_names_ids_and_the_tier_but_never_names_or_text(world, db):
    project = world.project("Work")
    layout = new_layout(world, project, "Confidential name", body=tree("Secret text"))

    result = duplicated(world, project, kind="layout", source_id=layout["id"])

    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "duplicated", AuditEvent.entity_id == result["new_id"])).all()
    (event,) = events
    assert event.detail["source_id"] == layout["id"] and event.detail["tier"] == "project"
    assert "Confidential" not in json.dumps(event.detail) and "Secret" not in json.dumps(event.detail)


def test_the_duplicate_exports_and_imports_like_any_layout(world):
    project = world.project("Work")
    layout = new_layout(world, project, "Handover")
    duplicated(world, project, kind="layout", source_id=layout["id"], name="Handover two")
    bundle = world.client.get(f"{base(project)}/export", headers=auth_headers(world.token))
    assert bundle.status_code == 200
    data = json.loads(zipfile.ZipFile(io.BytesIO(bundle.content)).read("project.json"))
    assert {"Handover", "Handover two"} <= {entry["name"] for entry in data["report_layouts"]}
