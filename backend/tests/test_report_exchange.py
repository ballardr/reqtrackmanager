"""Tests for exporting and importing report layouts and packs as a file (`routers.report_exchange`,
`services.report_exchange`): what the file holds (current version or history, packs with their layouts and sets,
pictures, no author emails), importing it into a project, another project of another organisation and the organisation,
name conflicts (rename or skip, never replace), the preview, the safety checks on an untrusted file, the gates and the
audit events. Each test builds its own organisation.
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
from app.services import report_exchange
from app.services.files import read_file
from app.services.report_layout_tree import empty_tree
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Exchange Org")


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


def resave(world: World, owner: dict | World, layout: dict, body: dict, base_version: int) -> None:
    resp = world.client.put(
        f"{base(owner)}/report-layouts/{layout['id']}/tree", json={"tree": body, "base_version": base_version, "comment": "edit"},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text


def new_pack(world: World, owner: dict | World, name: str, *layout_names: str) -> dict:
    definition: dict[str, Any] = {
        "schema_version": 1, "entries": [{"kind": "layout", "name": n, "format": "pdf"} for n in layout_names],
        "variables": [{"name": "title", "type": "text", "label": "Title", "default": "x"}],
    }
    resp = world.client.post(
        f"{base(owner)}/report-packs", json={"name": name, "description": "d", "definition": definition},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def export(world: World, owner: dict | World, *, token: str | None = None, **body: Any):
    return world.client.post(f"{base(owner)}/report-file/export", json=body, headers=auth_headers(token or world.token))


def exported(world: World, owner: dict | World, **body: Any) -> bytes:
    resp = export(world, owner, **body)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    return resp.content


def do_import(
    world: World, owner: dict | World, data: bytes, *, token: str | None = None, dry_run: bool = False, **form: str,
):
    return world.client.post(
        f"{base(owner)}/report-file/import", params={"dry_run": str(dry_run).lower()}, data=form,
        files={"file": ("reports.zip", data, "application/zip")}, headers=auth_headers(token or world.token),
    )


def imported(world: World, owner: dict | World, data: bytes, **form: str) -> dict:
    resp = do_import(world, owner, data, **form)
    assert resp.status_code == 200, resp.text
    return resp.json()


def listed(world: World, owner: dict | World, kind: str = "layouts") -> dict[str, dict]:
    resp = world.client.get(f"{base(owner)}/report-{kind}", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return {row["name"]: row for row in resp.json()}


def detail(world: World, owner: dict | World, row: dict, kind: str = "layouts") -> dict:
    return world.client.get(f"{base(owner)}/report-{kind}/{row['id']}", headers=auth_headers(world.token)).json()


def parts(data: bytes) -> tuple[dict, dict, zipfile.ZipFile]:
    zf = zipfile.ZipFile(io.BytesIO(data))
    return json.loads(zf.read("manifest.json")), json.loads(zf.read("reports.json")), zf


def build(manifest: dict | None = None, reports: dict | None = None, extra: dict[str, bytes] | None = None) -> bytes:
    """A hand-made report file, for the safety tests."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest or {"kind": report_exchange.FILE_KIND, "format_version": 1}))
        zf.writestr("reports.json", json.dumps(reports or {"layouts": [], "packs": [], "images": []}))
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return out.getvalue()


def entry(name: str, *trees: dict, family: str = "document") -> dict:
    return {
        "name": name, "description": "", "folder": "", "family": family,
        "versions": [{"version": i + 1, "schema_version": 1, "tree": t, "comment": ""} for i, t in enumerate(trees)],
    }


def user_with_role(world: World, project: dict, role: str) -> str:
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


# ---- the file ------------------------------------------------------------------------------------------------------


def test_the_file_is_a_zip_of_the_current_version_with_no_author_emails(world):
    project = world.project("Source")
    layout = new_layout(world, project, "Handover", folder="Board")
    resave(world, project, layout, tree("Second"), 1)

    manifest, reports, zf = parts(exported(world, project, layout_ids=[layout["id"]]))

    assert manifest["kind"] == report_exchange.FILE_KIND and manifest["history"] is False
    assert (manifest["layouts"], manifest["packs"], manifest["pictures"]) == (1, 0, 0)
    (item,) = reports["layouts"]
    assert item["name"] == "Handover" and item["folder"] == "Board"
    assert [v["tree"] for v in item["versions"]] == [tree("Second")]
    assert item["versions"][0]["comment"] == "Imported from file: Handover, version 2"
    assert "created_by_email" not in json.dumps(reports) and "@" not in zf.read("reports.json").decode()


def test_history_is_carried_only_when_asked(world):
    project = world.project("Source")
    layout = new_layout(world, project, "Handover")
    resave(world, project, layout, tree("Second"), 1)

    _, reports, _ = parts(exported(world, project, layout_ids=[layout["id"]], include_history=True))

    assert [v["version"] for v in reports["layouts"][0]["versions"]] == [1, 2]
    target = world.project("Target")
    imported(world, target, exported(world, project, layout_ids=[layout["id"]], include_history=True))
    versions = world.client.get(
        f"{base(target)}/report-layouts/{listed(world, target)['Handover']['id']}/versions", headers=auth_headers(world.token),
    ).json()
    assert [v["version"] for v in versions] == [2, 1]


def test_a_layout_round_trips_into_another_project_as_version_one_authored_by_the_importer(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Handover", body=tree("Round trip", {"type": "text", "text": "Body"}), folder="Board")
    resave(world, source, layout, tree("Latest"), 1)

    result = imported(world, target, exported(world, source, layout_ids=[layout["id"]]))

    assert [(i["kind"], i["action"], i["new_name"]) for i in result["items"]] == [("layout", "create", "Handover")]
    made = listed(world, target)["Handover"]
    assert made["origin"] == "project" and made["id"] != layout["id"] and made["current_version"] == 1
    assert made["folder"] == "Board" and made["description"] == "about Handover"
    assert detail(world, target, made)["current"]["tree"] == tree("Latest")
    assert detail(world, target, made)["current"]["comment"].startswith("Imported from file")
    assert listed(world, source)["Handover"]["current_version"] == 2  # the source is untouched


def test_an_inherited_organisation_layout_can_be_exported_from_a_project(world):
    project, target = world.project("Source"), world.project("Target")
    shared = new_layout(world, world, "Org wide")

    imported(world, target, exported(world, project, layout_ids=[shared["id"]]))

    assert listed(world, target)["Org wide"]["origin"] == "project"


# ---- packs ---------------------------------------------------------------------------------------------------------


def test_a_pack_travels_with_its_layouts_and_sets_and_follows_a_renamed_layout(world):
    source, target = world.project("Source"), world.project("Target")
    new_layout(world, source, "Monthly")
    new_layout(world, target, "Monthly")  # taken in the target, so the imported layout is renamed
    pack = new_pack(world, source, "Board pack", "Monthly")
    made_set = world.client.post(
        f"{base(source)}/report-packs/{pack['id']}/sets", json={"name": "Q1", "values": {"title": "First quarter"}},
        headers=auth_headers(world.token),
    )
    assert made_set.status_code in (200, 201), made_set.text

    data = exported(world, source, pack_ids=[pack["id"]])
    manifest, reports, _ = parts(data)
    assert (manifest["layouts"], manifest["packs"]) == (1, 1) and reports["packs"][0]["sets"][0]["name"] == "Q1"

    result = imported(world, target, data)

    assert [(i["kind"], i["action"], i["new_name"]) for i in result["items"]] == [
        ("layout", "rename", "Monthly (copy)"), ("pack", "create", "Board pack"),
    ]
    made = listed(world, target, "packs")["Board pack"]
    entries = detail(world, target, made, "packs")["current"]["definition"]["entries"]
    assert [e["name"] for e in entries] == ["Monthly (copy)"]
    sets = world.client.get(f"{base(target)}/report-packs/{made['id']}/sets", headers=auth_headers(world.token)).json()
    assert [(s["name"], s["effective"]) for s in sets] == [("Q1", {"title": "First quarter"})]


def test_a_pack_can_be_exported_without_its_layouts_and_the_import_warns(world):
    source, target = world.project("Source"), world.project("Target")
    new_layout(world, source, "Monthly")
    pack = new_pack(world, source, "Board pack", "Monthly")

    data = exported(world, source, pack_ids=[pack["id"]], include_pack_layouts=False)
    result = imported(world, target, data)

    assert parts(data)[0]["layouts"] == 0
    (item,) = result["items"]
    assert item["kind"] == "pack" and any("Monthly" in w for w in item["warnings"])


# ---- pictures ------------------------------------------------------------------------------------------------------


def test_pictures_are_stored_in_the_target_library_even_in_another_organisation(client, admin_token, world, db):
    source = world.project("Source")
    h = auth_headers(world.token)
    own = world.client.post(f"{base(source)}/report-images", files={"file": ("own.png", png("red"), "image/png")}, headers=h).json()
    shared = world.client.post(f"{base(world)}/report-images", files={"file": ("shared.png", png("blue"), "image/png")}, headers=h).json()
    pic = lambda file_id: {"type": "image", "file": file_id, "alt": "A picture"}  # noqa: E731
    layout = new_layout(world, source, "Pictures", body=tree("p", pic(own["id"]), pic(shared["id"])))

    data = exported(world, source, layout_ids=[layout["id"]])
    manifest, _, zf = parts(data)
    assert manifest["pictures"] == 2
    assert sorted(n for n in zf.namelist() if n.startswith("files/")) == ["files/0_own.png", "files/1_shared.png"]

    other = World(client, admin_token, "Other Org")
    target = other.project("Target")
    result = imported(other, target, data)

    assert result["pictures"] == 2
    made = listed(other, target)["Pictures"]
    nodes = detail(other, target, made)["current"]["tree"]["nodes"]
    files = [n["file"] for n in nodes if n["type"] == "image"]
    assert not {own["id"], shared["id"]} & set(files)
    for file_id in files:
        asset = db.get(FileAsset, uuid.UUID(file_id))
        assert asset is not None and str(asset.organization_id) == other.org["id"]
        assert str(asset.project_id) == target["id"] and asset.is_org_resource is False


def test_an_organisation_import_stores_pictures_in_the_organisation_library(client, admin_token, world, db):
    h = auth_headers(world.token)
    shared = world.client.post(f"{base(world)}/report-images", files={"file": ("logo.png", png("blue"), "image/png")}, headers=h).json()
    layout = new_layout(world, world, "Org picture", body=tree("p", {"type": "image", "file": shared["id"], "alt": "Logo"}))
    data = exported(world, world, layout_ids=[layout["id"]])

    other = World(client, admin_token, "Other Org")
    imported(other, other, data)

    made = listed(other, other)["Org picture"]
    file_id = detail(other, other, made)["current"]["tree"]["nodes"][1]["file"]
    asset = db.get(FileAsset, uuid.UUID(file_id))
    assert asset is not None and asset.is_org_resource is True and asset.project_id is None


def test_a_picture_that_is_not_an_image_is_refused_whatever_the_file_says(world):
    target = world.project("Target")
    picture = {"id": str(uuid.uuid4()), "file_ref": "files/0_x.png", "filename": "x.png", "content_type": "image/png", "tier": "project"}
    layout = entry("Fake", tree("t", {"type": "image", "file": picture["id"], "alt": "x"}))

    result = imported(world, target, build(
        reports={"layouts": [layout], "packs": [], "images": [picture]}, extra={"files/0_x.png": b"<html>not an image</html>"},
    ))

    assert any("not imported" in w for w in result["warnings"] + result["items"][0]["warnings"])
    assert result["items"][0]["action"] == "left_out" and "Fake" not in listed(world, target)


def test_an_svg_with_a_script_is_not_stored(world):
    target = world.project("Target")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>alert(1)</script><rect width="10" height="10"/></svg>'
    picture = {"id": str(uuid.uuid4()), "file_ref": "files/0_x.svg", "filename": "x.svg", "content_type": "image/svg+xml", "tier": "project"}
    layout = entry("Svg", tree("t", {"type": "image", "file": picture["id"], "alt": "x"}))

    result = imported(world, target, build(reports={"layouts": [layout], "packs": [], "images": [picture]}, extra={"files/0_x.svg": svg}))

    # Either the picture is refused (the layout is left out) or it is stored allow-listed, never as uploaded.
    assert result["items"][0]["action"] in ("left_out", "create")
    for asset in SessionLocal().scalars(select(FileAsset).where(FileAsset.organization_id == uuid.UUID(world.org["id"]))):
        if asset.content_type == "image/svg+xml":
            assert b"<script" not in read_file(asset)


# ---- names, preview, the organisation ----------------------------------------------------------------------------


def test_a_name_the_target_owns_is_renamed_or_skipped_and_never_replaced(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report", body=tree("From source"))
    new_layout(world, target, "Report", body=tree("Already here"))
    data = exported(world, source, layout_ids=[layout["id"]])

    renamed = imported(world, target, data)
    skipped = imported(world, target, data, on_conflict="skip")

    assert renamed["items"][0]["action"] == "rename" and renamed["items"][0]["new_name"] == "Report (copy)"
    assert skipped["items"][0]["action"] == "skip"
    rows = listed(world, target)
    assert set(rows) == {"Report", "Report (copy)"}
    assert detail(world, target, rows["Report"])["current"]["tree"] == tree("Already here")


def test_a_preview_writes_nothing(world, db):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report")
    data = exported(world, source, layout_ids=[layout["id"]])

    resp = do_import(world, target, data, dry_run=True)

    assert resp.status_code == 200 and resp.json()["dry_run"] is True
    assert resp.json()["items"][0]["action"] == "create" and resp.json()["items"][0]["new_id"] is None
    assert "Report" not in listed(world, target)


def test_a_folder_chosen_at_import_files_every_report(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report", folder="Elsewhere")

    imported(world, target, exported(world, source, layout_ids=[layout["id"]]), folder="Board/Q1")

    assert listed(world, target)["Report"]["folder"] == "Board/Q1"


def test_a_layout_with_no_valid_version_is_left_out_with_the_reason(world):
    target = world.project("Target")
    bad = entry("Broken", {"schema_version": 1, "nodes": [{"type": "no-such-block"}]})
    good = entry("Fine", tree("ok"))

    preview = do_import(world, target, build(reports={"layouts": [bad, good], "packs": [], "images": []}), dry_run=True).json()
    applied = imported(world, target, build(reports={"layouts": [bad, good], "packs": [], "images": []}))

    assert [i["action"] for i in preview["items"]] == ["left_out", "create"] and preview["items"][0]["warnings"]
    assert set(listed(world, target)) == {"Fine"}
    assert [i["action"] for i in applied["items"]] == ["left_out", "create"]


def test_the_organisation_can_export_and_import_its_own_reports(client, admin_token, world):
    layout = new_layout(world, world, "Org report")
    pack = new_pack(world, world, "Org pack", "Org report")
    data = exported(world, world, pack_ids=[pack["id"]])
    other = World(client, admin_token, "Other Org")

    result = imported(other, other, data)

    assert sorted((i["kind"], i["action"]) for i in result["items"]) == [("layout", "create"), ("pack", "create")]
    assert set(listed(other, other)) == {"Org report"} and set(listed(other, other, "packs")) == {"Org pack"}
    assert layout["id"] not in {r["id"] for r in listed(other, other).values()}


# ---- the file is untrusted -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"not a zip", 400),
        (build(manifest={"kind": "something-else", "format_version": 1}), 400),
        (build(manifest={"kind": report_exchange.FILE_KIND, "format_version": 99}), 400),
        (build(manifest={"kind": report_exchange.FILE_KIND}), 400),
        (build(extra={"../evil.txt": b"x"}), 400),
        (build(extra={"/abs.txt": b"x"}), 400),
        (build(extra={"files/..\\evil": b"x"}), 400),
        (build(extra={"other.json": b"{}"}), 400),
        (build(reports={"layouts": "nope", "packs": [], "images": []}), 400),
        (build(reports={"layouts": [entry(f"L{i}", tree()) for i in range(101)], "packs": [], "images": []}), 413),
    ],
)
def test_a_file_that_is_not_a_report_file_is_refused_and_nothing_is_stored(world, data, status):
    target = world.project("Target")

    resp = do_import(world, target, data)

    assert resp.status_code == status, resp.text
    assert listed(world, target) == {}


def test_an_entry_that_inflates_far_beyond_its_size_is_refused(world):
    target = world.project("Target")
    data = build(extra={"files/0_zeros.png": b"\0" * (8 * 1024 * 1024)})

    resp = do_import(world, target, data)

    assert resp.status_code == 413 and listed(world, target) == {}


def test_the_text_of_a_file_is_not_logged_or_audited(world, db):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Confidential name", body=tree("Secret wording"))
    imported(world, target, exported(world, source, layout_ids=[layout["id"]]))

    events = db.scalars(select(AuditEvent).where(AuditEvent.action.in_(["report_file_exported", "report_file_imported"]))).all()
    kinds = {e.action: e for e in events if str(e.organization_id) == world.org["id"]}
    assert set(kinds) == {"report_file_exported", "report_file_imported"}
    assert kinds["report_file_imported"].detail["layouts"] == 1
    for event in kinds.values():
        assert "Secret wording" not in json.dumps(event.detail) and "Confidential name" not in json.dumps(event.detail)


# ---- gates ---------------------------------------------------------------------------------------------------------


def test_exporting_and_importing_need_the_manage_right_and_a_report_the_tier_can_reach(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report")
    data = exported(world, source, layout_ids=[layout["id"]])
    member = user_with_role(world, source, "member")
    manager = user_with_role(world, source, "project_manager")

    assert export(world, source, token=member, layout_ids=[layout["id"]]).status_code == 403
    assert do_import(world, source, data, token=member).status_code == 403
    assert export(world, source, token=manager, layout_ids=[layout["id"]]).status_code == 200
    assert export(world, target, layout_ids=[layout["id"]]).status_code == 404  # not reachable from the other project
    assert export(world, source, layout_ids=[str(uuid.uuid4())]).status_code == 404
    assert export(world, source).status_code == 422
    assert do_import(world, source, data, token=manager).status_code == 200


def test_the_organisation_tier_needs_the_organisation_right(world):
    project = world.project("Source")
    layout = new_layout(world, world, "Org report")
    manager = user_with_role(world, project, "project_manager")

    assert export(world, world, token=manager, layout_ids=[layout["id"]]).status_code == 403
    assert do_import(world, world, build(), token=manager).status_code == 403


def test_an_archived_project_refuses_an_import(world):
    source, target = world.project("Source"), world.project("Target")
    layout = new_layout(world, source, "Report")
    data = exported(world, source, layout_ids=[layout["id"]])
    archived = world.client.post(f"{base(target)}/archive", headers=auth_headers(world.token))
    assert archived.status_code in (200, 204), archived.text

    assert do_import(world, target, data).status_code == 409
