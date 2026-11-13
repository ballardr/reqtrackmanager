"""Tests for folders (`folders.py`, `folder_routes.py`): the tree rules (unique names, no cycle, depth cap), a record in a
folder of its own kind and owner, deleting a folder moving its content up, the bulk move, the path a list returns, a
shared element showing its path but not its folder, the Folder column of the record tables with the list's folder
filter, and the project and organisation bundles. Every test builds its own organisation."""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.architecture import folders as folder_rules
from app.modules.architecture.export import FOLDERS_KEY, PROJECT_KEYS
from app.modules.architecture.models import ArchitectureElement, ArchitectureFolder
from app.modules.architecture.tests._helpers import (
    add_member,
    grant,
    make_collection,
    make_connection,
    make_diagram,
    make_element,
    make_org_element,
    org_base,
    project_base,
    put_element,
    setup,
)
from tests.conftest import auth_headers, create_project

ELEMENT = "architecture_element"


def _folder(client, token, base, kind, name, *, parent=None, expect=201) -> dict:
    body: dict = {"name": name}
    if parent is not None:
        body["parent_id"] = parent["id"] if isinstance(parent, dict) else parent
    resp = client.post(f"{base}/{kind}-folders", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _folders(client, token, base, kind) -> dict[str, dict]:
    resp = client.get(f"{base}/{kind}-folders", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {f["path"]: f for f in resp.json()}


def _element(client, token, project_id, element_id) -> dict:
    resp = client.get(f"{project_base(project_id)}/elements/{element_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Tree rules ------------------------------------------------------------


def test_a_folder_tree_gives_paths_and_counts_and_refuses_a_clash_a_slash_a_cycle_and_too_deep(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch folders tree")
    base = project_base(project["id"])
    software = _folder(client, token, base, "element", "Software")
    modules = _folder(client, token, base, "element", "Modules", parent=software)
    make_element(client, token, project["id"], "Auth", folder_id=modules["id"])
    listed = _folders(client, token, base, "element")
    assert set(listed) == {"Software", "Software/Modules"}
    assert (listed["Software/Modules"]["record_count"], listed["Software"]["record_count"]) == (1, 0)

    assert "already exists" in _folder(client, token, base, "element", "software", expect=400)["detail"]
    assert "'/'" in _folder(client, token, base, "element", "A/B", expect=400)["detail"]
    # The same name is allowed under another parent and in another kind's tree.
    _folder(client, token, base, "element", "Modules")
    _folder(client, token, base, "connection", "Software")

    moved = client.put(f"{base}/element-folders/{software['id']}", json={"parent_id": modules["id"]}, headers=auth_headers(token))
    assert moved.status_code == 400 and "into itself" in moved.json()["detail"]
    own = client.put(f"{base}/element-folders/{software['id']}", json={"parent_id": software["id"]}, headers=auth_headers(token))
    assert own.status_code == 400

    parent = None
    for depth in range(12):
        parent = _folder(client, token, base, "diagram", f"Level {depth}", parent=parent)
    assert "at most 12" in _folder(client, token, base, "diagram", "Too deep", parent=parent, expect=400)["detail"]


def test_renaming_and_moving_a_folder_changes_every_path_below_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch folders rename")
    base = project_base(project["id"])
    hardware = _folder(client, token, base, "element", "Hardware")
    boards = _folder(client, token, base, "element", "Boards", parent=hardware)
    element = make_element(client, token, project["id"], "Main board", folder_id=boards["id"])
    assert _element(client, token, project["id"], element["id"])["folder_path"] == "Hardware/Boards"

    renamed = client.put(f"{base}/element-folders/{hardware['id']}", json={"name": "Devices"}, headers=auth_headers(token))
    assert renamed.status_code == 200 and renamed.json()["path"] == "Devices"
    assert _element(client, token, project["id"], element["id"])["folder_path"] == "Devices/Boards"
    top = client.put(f"{base}/element-folders/{boards['id']}", json={"parent_id": None}, headers=auth_headers(token))
    assert top.status_code == 200 and top.json()["path"] == "Boards"
    assert _element(client, token, project["id"], element["id"])["folder_path"] == "Boards"


def test_a_record_may_only_use_its_own_owners_folder_of_its_own_kind(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch folders kinds")
    other = create_project(client, token, org["id"], "Other")
    base = project_base(project["id"])
    connection_folder = _folder(client, token, base, "connection", "Links")
    element_folder = _folder(client, token, base, "element", "Parts")
    foreign = _folder(client, token, project_base(other["id"]), "element", "Foreign")
    org_folder = _folder(client, token, org_base(org["id"]), "element", "Platform parts")

    make_element(client, token, project["id"], "Wrong kind", folder_id=connection_folder["id"], expect=400)
    make_element(client, token, project["id"], "Foreign", folder_id=foreign["id"], expect=400)
    make_element(client, token, project["id"], "Organisation's", folder_id=org_folder["id"], expect=400)
    make_diagram(client, token, project["id"], "Wrong", folder_id=element_folder["id"], expect=400)
    make_element(client, token, project["id"], "Right", folder_id=element_folder["id"])
    ids = [make_element(client, token, project["id"], n)["id"] for n in ("A", "B")]
    make_connection(client, token, project["id"], ids[0], ids[1], folder_id=element_folder["id"], expect=400)
    # Another project's folder looks absent, so cannot be changed through this project.
    missing = client.put(f"{base}/element-folders/{foreign['id']}", json={"name": "Hijack"}, headers=auth_headers(token))
    assert missing.status_code == 404
    assert client.delete(f"{base}/element-folders/{foreign['id']}", headers=auth_headers(token)).status_code == 404


def test_deleting_a_folder_moves_its_records_and_sub_folders_up_and_deletes_nothing_else(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch folders delete")
    base = project_base(project["id"])
    top = _folder(client, token, base, "element", "Top")
    middle = _folder(client, token, base, "element", "Middle", parent=top)
    _folder(client, token, base, "element", "Leaf", parent=middle)
    in_middle = make_element(client, token, project["id"], "In middle", folder_id=middle["id"])
    deleted = client.delete(f"{base}/element-folders/{middle['id']}", headers=auth_headers(token))
    assert deleted.status_code == 204
    after = _element(client, token, project["id"], in_middle["id"])
    assert after["folder_id"] == top["id"] and after["folder_path"] == "Top" and after["version"] == in_middle["version"] + 1
    assert set(_folders(client, token, base, "element")) == {"Top", "Top/Leaf"}

    # A sub-folder whose name the parent already has stops the delete rather than merging or renaming.
    clash = _folder(client, token, base, "element", "Clash", parent=top)
    _folder(client, token, base, "element", "Leaf", parent=clash)
    refused = client.delete(f"{base}/element-folders/{clash['id']}", headers=auth_headers(token))
    assert refused.status_code == 400 and "rename" in refused.json()["detail"]
    assert "Top/Clash/Leaf" in _folders(client, token, base, "element")


# --- Records ---------------------------------------------------------------


def test_every_kind_of_record_carries_its_folder_and_clears_it_with_null(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch folders records")
    base = project_base(project["id"])
    h = auth_headers(token)
    folders = {kind: _folder(client, token, base, kind, f"{kind.title()} folder") for kind in ("element", "connection", "diagram")}
    a = make_element(client, token, project["id"], "A", folder_id=folders["element"]["id"])
    b = make_element(client, token, project["id"], "B")
    connection = make_connection(client, token, project["id"], a["id"], b["id"], folder_id=folders["connection"]["id"])
    diagram = make_diagram(client, token, project["id"], "Context", folder_id=folders["diagram"]["id"])
    assert b["folder_id"] is None and b["folder_path"] is None
    for kind, record, collection in (("element", a, "elements"), ("connection", connection, "connections"), ("diagram", diagram, "diagrams")):
        assert record["folder_path"] == f"{kind.title()} folder"
        listed = {r["id"]: r for r in client.get(f"{base}/{collection}", headers=h).json()}
        assert listed[record["id"]]["folder_path"] == record["folder_path"]
        cleared = client.put(
            f"{base}/{collection}/{record['id']}", json={"version": record["version"], "folder_id": None}, headers=h,
        )
        assert cleared.status_code == 200 and cleared.json()["folder_id"] is None and cleared.json()["folder_path"] is None
        back = client.put(
            f"{base}/{collection}/{record['id']}", json={"version": cleared.json()["version"], "folder_id": folders[kind]["id"]}, headers=h,
        )
        assert back.status_code == 200 and back.json()["folder_id"] == folders[kind]["id"]


def test_the_bulk_move_changes_only_the_records_named_and_never_a_foreign_one(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch folders move")
    other = create_project(client, token, org["id"], "Other")
    base = project_base(project["id"])
    h = auth_headers(token)
    target = _folder(client, token, base, "element", "Target")
    first, second, untouched = (make_element(client, token, project["id"], n) for n in ("First", "Second", "Untouched"))
    foreign = make_element(client, token, other["id"], "Foreign")

    both = {"record_ids": [first["id"], second["id"]], "folder_id": target["id"]}
    moved = client.post(f"{base}/element-folders/move-records", json=both, headers=h)
    assert moved.status_code == 200 and moved.json() == {"moved": 2}
    assert _element(client, token, project["id"], first["id"])["folder_path"] == "Target"
    assert _element(client, token, project["id"], untouched["id"])["folder_id"] is None
    again = client.post(f"{base}/element-folders/move-records", json={"record_ids": [first["id"]], "folder_id": target["id"]}, headers=h)
    assert again.json() == {"moved": 0}
    refused = client.post(f"{base}/element-folders/move-records", json={"record_ids": [foreign["id"]], "folder_id": target["id"]}, headers=h)
    assert refused.status_code == 404
    assert _element(client, token, other["id"], foreign["id"])["folder_id"] is None
    top = client.post(f"{base}/element-folders/move-records", json={"record_ids": [first["id"]], "folder_id": None}, headers=h)
    assert top.json() == {"moved": 1} and _element(client, token, project["id"], first["id"])["folder_id"] is None
    # A folder of another kind is not a destination.
    wrong = _folder(client, token, base, "diagram", "Diagrams")
    bad = client.post(f"{base}/element-folders/move-records", json={"record_ids": [first["id"]], "folder_id": wrong["id"]}, headers=h)
    assert bad.status_code == 400


def test_only_an_architect_changes_folders_but_any_member_reads_them(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch folders gate")
    base = project_base(project["id"])
    _folder(client, token, base, "element", "Visible")
    _user_id, member = add_member(client, token, org["id"], project["id"], "arch.folders.member@example.com")
    assert set(_folders(client, member, base, "element")) == {"Visible"}
    denied = client.post(f"{base}/element-folders", json={"name": "Sneaky"}, headers=auth_headers(member))
    assert denied.status_code == 403
    folder_id = next(iter(_folders(client, member, base, "element").values()))["id"]
    assert client.put(f"{base}/element-folders/{folder_id}", json={"name": "X"}, headers=auth_headers(member)).status_code == 403
    assert client.delete(f"{base}/element-folders/{folder_id}", headers=auth_headers(member)).status_code == 403


# --- Organisation and sharing ----------------------------------------------


def test_organisation_element_folders_are_the_organisations_own_and_a_shared_element_shows_its_path_only(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch folders org")
    h = auth_headers(token)
    parts = _folder(client, token, org_base(org["id"]), "element", "Platform")
    sub = _folder(client, token, org_base(org["id"]), "element", "Services", parent=parts)
    _folder(client, token, org_base(org["id"]), "element", "Hidden sibling")
    shared = make_org_element(client, token, org["id"], "Gateway", folder_id=sub["id"])
    assert shared["folder_path"] == "Platform/Services" and shared["folder_id"] == sub["id"]
    # The organisation has element folders only.
    assert client.post(f"{org_base(org['id'])}/connection-folders", json={"name": "Nope"}, headers=h).status_code in (404, 405)

    collection = make_collection(client, token, org_base(org["id"]), "Everyone", members=[shared["id"]])
    grant(client, token, org_base(org["id"]), collection["id"], project_id=project["id"])
    seen = client.get(f"{project_base(project['id'])}/elements/shared", headers=h).json()
    assert [(e["name"], e["folder_path"], e["folder_id"]) for e in seen] == [("Gateway", "Platform/Services", None)]
    assert "Hidden sibling" not in json.dumps(seen)
    # The project cannot put its own element in the organisation's folder.
    make_element(client, token, project["id"], "Own", folder_id=sub["id"], expect=400)


# --- Record tables ---------------------------------------------------------


def _csv_rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def test_the_tables_export_the_folder_path_filter_by_it_and_import_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch folders tables")
    base = project_base(project["id"])
    h = auth_headers(token)
    software = _folder(client, token, base, "element", "Software")
    modules = _folder(client, token, base, "element", "Modules", parent=software)
    make_element(client, token, project["id"], "Top level")
    make_element(client, token, project["id"], "In software", folder_id=software["id"])
    make_element(client, token, project["id"], "In modules", folder_id=modules["id"])
    tier = f"/api/v1/projects/{project['id']}/records/{ELEMENT}"

    rows = {r["name"]: r for r in _csv_rows(client.get(f"{tier}/export", headers=h))}
    assert (rows["In modules"]["folder"], rows["In software"]["folder"], rows["Top level"]["folder"]) == ("Software/Modules", "Software", "")
    exact = {r["name"] for r in _csv_rows(client.get(f"{tier}/export", params={"folder": "Software"}, headers=h))}
    below = {r["name"] for r in _csv_rows(client.get(f"{tier}/export", params={"folder": "software", "subfolders": "true"}, headers=h))}
    nothing = _csv_rows(client.get(f"{tier}/export", params={"folder": "Nowhere"}, headers=h))
    assert exact == {"In software"} and below == {"In software", "In modules"} and nothing == []

    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(["code", "name", "type", "folder"])
    writer.writerow(["", "Imported", "Component", "Software/Modules"])
    writer.writerow(["", "Lost", "Component", "Software/Missing"])
    writer.writerow([rows["Top level"]["code"], "Top level", "Component", "Software"])
    imported = client.post(
        f"{tier}/import", params={"dry_run": "false"}, files={"file": ("e.csv", text.getvalue().encode(), "text/csv")}, headers=h,
    )
    assert imported.status_code == 200, imported.text
    assert (imported.json()["created"], imported.json()["updated"], imported.json()["failed"]) == (1, 1, 1)
    listed = {e["name"]: e["folder_path"] for e in client.get(f"{base}/elements", headers=h).json()}
    assert listed["Imported"] == "Software/Modules" and listed["Top level"] == "Software" and "Lost" not in listed


# --- Bundles ---------------------------------------------------------------


def _bundle(client, token, url) -> tuple[bytes, dict]:
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    name = next(n for n in archive.namelist() if n in ("project.json", "org.json"))
    return resp.content, json.loads(archive.read(name))


def test_the_project_bundle_carries_the_folders_and_each_records_path(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch folders bundle")
    base = project_base(project["id"])
    h = auth_headers(token)
    software = _folder(client, token, base, "element", "Software")
    modules = _folder(client, token, base, "element", "Modules", parent=software)
    _folder(client, token, base, "element", "Empty")
    link_folder = _folder(client, token, base, "connection", "Buses")
    diagram_folder = _folder(client, token, base, "diagram", "Overviews")
    a = make_element(client, token, project["id"], "A", folder_id=modules["id"])
    b = make_element(client, token, project["id"], "B")
    make_connection(client, token, project["id"], a["id"], b["id"], name="Bus", folder_id=link_folder["id"])
    make_diagram(client, token, project["id"], "Context", folder_id=diagram_folder["id"])

    content, data = _bundle(client, token, f"/api/v1/projects/{project['id']}/export")
    assert FOLDERS_KEY in PROJECT_KEYS
    assert [(f["kind"], f["path"]) for f in data[FOLDERS_KEY]] == [
        ("connection", "Buses"), ("diagram", "Overviews"), ("element", "Empty"), ("element", "Software"), ("element", "Software/Modules"),
    ]
    assert {e["name"]: e["folder"] for e in data["architecture_elements"]} == {"A": "Software/Modules", "B": None}
    assert data["architecture_connections"][0]["folder"] == "Buses" and data["architecture_diagrams"][0]["folder"] == "Overviews"
    assert "id" not in data[FOLDERS_KEY][0]

    copy = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch folders bundle copy"},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=h,
    ).json()["project"]
    copy_base = project_base(copy["id"])
    assert set(_folders(client, token, copy_base, "element")) == {"Software", "Software/Modules", "Empty"}
    assert set(_folders(client, token, copy_base, "connection")) == {"Buses"}
    assert {e["name"]: e["folder_path"] for e in client.get(f"{copy_base}/elements", headers=h).json()} == {"A": "Software/Modules", "B": None}
    assert client.get(f"{copy_base}/connections", headers=h).json()[0]["folder_path"] == "Buses"
    assert client.get(f"{copy_base}/diagrams", headers=h).json()[0]["folder_path"] == "Overviews"


def test_a_record_whose_folder_the_bundle_lacks_creates_it_rather_than_being_dropped(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch folders bundle missing")
    base = project_base(project["id"])
    h = auth_headers(token)
    make_element(client, token, project["id"], "A", folder_id=_folder(client, token, base, "element", "Kept")["id"])
    content, data = _bundle(client, token, f"/api/v1/projects/{project['id']}/export")
    data.pop(FOLDERS_KEY)
    data["architecture_elements"][0]["folder"] = "Made/Up"
    patched = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as src, zipfile.ZipFile(patched, "w") as out:
        for item in src.infolist():
            out.writestr(item, json.dumps(data) if item.filename == "project.json" else src.read(item.filename))
    copy = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch folders bundle missing copy"},
        files={"file": ("bundle.zip", patched.getvalue(), "application/zip")}, headers=h,
    ).json()["project"]
    assert {e["name"]: e["folder_path"] for e in client.get(f"{project_base(copy['id'])}/elements", headers=h).json()} == {"A": "Made/Up"}


def test_the_organisation_bundle_carries_element_folders(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch folders org bundle")
    parts = _folder(client, token, org_base(org["id"]), "element", "Platform")
    sub = _folder(client, token, org_base(org["id"]), "element", "Services", parent=parts)
    make_org_element(client, token, org["id"], "Gateway", folder_id=sub["id"])
    content, data = _bundle(client, token, f"/api/v1/orgs/{org['id']}/export")
    assert [(f["kind"], f["path"]) for f in data["architecture_org_folders"]] == [("element", "Platform"), ("element", "Platform/Services")]
    assert data["architecture_org_elements"][0]["folder"] == "Platform/Services"

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Arch folders org bundle copy"},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org_id = uuid.UUID(imported.json()["organization"]["id"])
    with SessionLocal() as db:
        folders = list(db.scalars(select(ArchitectureFolder).where(ArchitectureFolder.organization_id == new_org_id)))
        paths = folder_rules.paths_for(db, [f.id for f in folders])
        elements = list(db.scalars(select(ArchitectureElement).where(ArchitectureElement.organization_id == new_org_id)))
        assert sorted(paths.values()) == ["Platform", "Platform/Services"]
        assert [(e.name, e.folder_id and paths[e.folder_id]) for e in elements] == [("Gateway", "Platform/Services")]


def test_an_element_edit_that_names_no_folder_keeps_the_folder(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch folders keep")
    base = project_base(project["id"])
    folder = _folder(client, token, base, "element", "Kept")
    element = make_element(client, token, project["id"], "A", folder_id=folder["id"])
    renamed = put_element(client, token, project["id"], element, name="A renamed")
    assert renamed["folder_id"] == folder["id"]
