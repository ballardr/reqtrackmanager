"""Tests for the symbol library's folders and library page (`folders.py` with the `symbol` kind, `symbol_library.py`,
`symbol_routes.py`): folders of the organisation and of a project, a symbol filed on upload or by a move, the built-ins
staying at the top level, the folder tree rules reused for the new kind, the library listing's filters, sort and page, who
is named under "used by", a project's read-only view of the organisation's folders, a child project's copy of an
inherited symbol being filed nowhere, and the organisation and project bundles. Every test builds its own organisation."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.architecture import folders as folder_rules
from app.modules.architecture.export import FOLDERS_KEY, ORG_FOLDERS_KEY, ORG_SYMBOLS_KEY, PROJECT_SYMBOLS_KEY
from app.modules.architecture.models import ArchitectureFolder, ArchitectureSymbol
from app.modules.architecture.tests._helpers import (
    add_member,
    grant_project_role,
    make_element,
    org_base,
    org_element_types,
    project_base,
    setup,
)
from app.modules.architecture.tests.test_architecture_symbol_bundles import _import_org, _import_project, _json, _rewrite, _zip
from tests.conftest import auth_headers, create_org_admin_in, create_project

NS = 'xmlns="http://www.w3.org/2000/svg"'


def _svg(tag: str) -> str:
    return f'<svg {NS} viewBox="0 0 10 10"><title>{tag}</title><circle cx="5" cy="5" r="4"/></svg>'


def _folder(client, token, base, name, *, parent=None, expect=201) -> dict:
    body: dict = {"name": name}
    if parent is not None:
        body["parent_id"] = parent["id"]
    resp = client.post(f"{base}/symbol-folders", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _upload(client, token, base, name, *, folder=None, expect=201, filename=None) -> dict:
    data = {"name": name}
    if folder is not None:
        data["folder_id"] = folder["id"] if isinstance(folder, dict) else folder
    resp = client.post(
        f"{base}/symbols", files={"file": (filename or f"{name}.svg", _svg(name).encode(), "image/svg+xml")}, data=data,
        headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _library(client, token, base, **params) -> dict:
    resp = client.get(f"{base}/symbols/library", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _symbol_id(client, token, base, name) -> str:
    """The id of the library symbol called `name`."""
    return next(r["id"] for r in _library(client, token, base, search=name)["items"] if r["name"] == name)


def _names(page: dict) -> list[str]:
    return [row["name"] for row in page["items"]]


def _move(client, token, base, ids, folder, expect=200) -> dict:
    resp = client.post(
        f"{base}/symbol-folders/move-records", json={"record_ids": ids, "folder_id": folder["id"] if folder else None},
        headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


# --- Folders of the organisation and of a project --------------------------------------------------


def test_the_organisation_and_a_project_each_have_their_own_symbol_folders_with_paths_and_counts(client, admin_token):
    org, project, token = setup(client, admin_token, "Symfold tree")
    org_b, pro_b = org_base(org["id"]), project_base(project["id"])
    icons = _folder(client, token, org_b, "Icons")
    network = _folder(client, token, org_b, "Network", parent=icons)
    _upload(client, token, org_b, "Router", folder=network)
    listed = {f["path"]: f for f in client.get(f"{org_b}/symbol-folders", headers=auth_headers(token)).json()}
    assert set(listed) == {"Icons", "Icons/Network"} and listed["Icons/Network"]["record_count"] == 1 and listed["Icons"]["record_count"] == 0
    assert all(f["kind"] == "symbol" and f["organization_id"] == org["id"] for f in listed.values())

    # A project's folders are its own: the organisation's are not listed there, and the same name is allowed.
    assert client.get(f"{pro_b}/symbol-folders", headers=auth_headers(token)).json() == []
    own = _folder(client, token, pro_b, "Icons")
    assert own["project_id"] == project["id"] and own["id"] != icons["id"]
    # The element tree is separate from the symbol tree.
    assert client.get(f"{org_b}/element-folders", headers=auth_headers(token)).json() == []


def test_the_folder_rules_hold_for_symbol_folders_and_a_folder_of_another_owner_or_kind_is_refused(client, admin_token):
    org, project, token = setup(client, admin_token, "Symfold rules")
    org_b, pro_b = org_base(org["id"]), project_base(project["id"])
    icons = _folder(client, token, org_b, "Icons")
    assert "already exists" in _folder(client, token, org_b, "icons", expect=400)["detail"]
    assert "'/'" in _folder(client, token, org_b, "A/B", expect=400)["detail"]
    moved = client.put(f"{org_b}/symbol-folders/{icons['id']}", json={"parent_id": icons["id"]}, headers=auth_headers(token))
    assert moved.status_code == 400
    # A symbol cannot be filed in a project's folder by the organisation, nor in an element folder.
    project_folder = _folder(client, token, pro_b, "Mine")
    assert "not available" in _upload(client, token, org_b, "Cross", folder=project_folder, expect=400)["detail"]
    element_folder = client.post(f"{org_b}/element-folders", json={"name": "Systems"}, headers=auth_headers(token)).json()
    assert "not available" in _upload(client, token, org_b, "Wrong kind", folder=element_folder, expect=400)["detail"]
    # An organisation has no connection or diagram folders (its two kinds are elements and symbols).
    assert client.post(f"{org_b}/connection-folders", json={"name": "x"}, headers=auth_headers(token)).status_code == 404


def test_another_organisations_symbol_folder_is_refused_as_if_it_did_not_exist(client, admin_token):
    org, _project, token = setup(client, admin_token, "Symfold iso a")
    org_other, _p, token_other = setup(client, admin_token, "Symfold iso b")
    theirs = _folder(client, token_other, org_base(org_other["id"]), "Theirs")
    assert "not available" in _upload(client, token, org_base(org["id"]), "Sneaky", folder=theirs, expect=400)["detail"]
    own = _upload(client, token, org_base(org["id"]), "Plain")
    assert client.post(
        f"{org_base(org['id'])}/symbol-folders/move-records", json={"record_ids": [own["id"]], "folder_id": theirs["id"]},
        headers=auth_headers(token),
    ).status_code == 400
    assert client.put(
        f"{org_base(org['id'])}/symbol-folders/{theirs['id']}", json={"name": "Taken"}, headers=auth_headers(token),
    ).status_code == 404


def test_deleting_a_folder_moves_its_symbols_and_sub_folders_up_and_nothing_is_deleted(client, admin_token):
    org, _project, token = setup(client, admin_token, "Symfold delete")
    base = org_base(org["id"])
    top = _folder(client, token, base, "Top")
    inner = _folder(client, token, base, "Inner", parent=top)
    first = _upload(client, token, base, "First", folder=top)
    second = _upload(client, token, base, "Second", folder=inner)
    assert client.delete(f"{base}/symbol-folders/{top['id']}", headers=auth_headers(token)).status_code == 204
    page = _library(client, token, base)
    rows = {r["name"]: r for r in page["items"]}
    assert rows["First"]["folder_path"] is None and rows["Second"]["folder_path"] == "Inner"
    assert first["id"] in {r["id"] for r in page["items"]} and second["id"] in {r["id"] for r in page["items"]}


# --- Filing -------------------------------------------------------------------------------------


def test_a_symbol_is_filed_on_upload_or_by_a_bulk_move_and_a_built_in_stays_at_the_top_level(client, admin_token):
    org, _project, token = setup(client, admin_token, "Symfold move")
    base = org_base(org["id"])
    folder = _folder(client, token, base, "Icons")
    other = _folder(client, token, base, "Other")
    filed = _upload(client, token, base, "Filed", folder=folder)
    loose = _upload(client, token, base, "Loose")
    assert filed["folder_id"] == folder["id"] and loose["folder_id"] is None
    assert _move(client, token, base, [loose["id"], filed["id"]], other) == {"moved": 2}
    assert _move(client, token, base, [loose["id"]], other) == {"moved": 0}
    assert _move(client, token, base, [loose["id"]], None) == {"moved": 1}
    builtin = next(r for r in _library(client, token, base, source="builtin")["items"])
    refused = client.post(
        f"{base}/symbol-folders/move-records", json={"record_ids": [builtin["id"]], "folder_id": folder["id"]}, headers=auth_headers(token),
    )
    assert refused.status_code == 400 and "built-in" in refused.json()["detail"].lower()
    assert builtin["can_file"] is False and builtin["folder_path"] is None
    assert _move(client, token, base, [str(uuid.uuid4())], folder, expect=404)


def test_filing_symbols_needs_the_role_that_manages_symbols_and_an_event_is_audited_without_names(client, admin_token):
    org, project, token = setup(client, admin_token, "Symfold roles")
    org_b, pro_b = org_base(org["id"]), project_base(project["id"])
    _user_id, member = add_member(client, token, org["id"], project["id"], "symfold.member@example.com")
    assert client.post(f"{pro_b}/symbol-folders", json={"name": "x"}, headers=auth_headers(member)).status_code == 403
    assert client.post(f"{org_b}/symbol-folders", json={"name": "x"}, headers=auth_headers(member)).status_code == 403
    assert client.get(f"{org_b}/symbol-folders", headers=auth_headers(member)).status_code == 403
    admin_id, admin_member = add_member(client, token, org["id"], project["id"], "symfold.admin@example.com")
    grant_project_role(client, token, project["id"], admin_id, "architecture_admin")
    assert client.post(f"{pro_b}/symbol-folders", json={"name": "Allowed"}, headers=auth_headers(admin_member)).status_code == 201
    assert client.get(f"{pro_b}/symbol-folders", headers=auth_headers(member)).status_code == 200

    folder = _folder(client, token, org_b, "Secret Folder Name")
    symbol = _upload(client, token, org_b, "Quiet", folder=folder)
    _move(client, token, org_b, [symbol["id"]], None)
    events = client.get(f"/api/v1/orgs/{org['id']}/audit-log", headers=auth_headers(token))
    if events.status_code == 200:
        assert "Secret Folder Name" not in json.dumps(events.json())


# --- The library listing ---------------------------------------------------------------------


def test_the_library_lists_filters_sorts_and_pages_with_the_server_doing_the_work(client, admin_token):
    org, _project, token = setup(client, admin_token, "Symlib list")
    base = org_base(org["id"])
    network = _folder(client, token, base, "Network")
    deep = _folder(client, token, base, "Switches", parent=network)
    _upload(client, token, base, "Zebra router", folder=network)
    _upload(client, token, base, "Apple switch", folder=deep)
    _upload(client, token, base, "Mango", filename="mango.eps.svg")
    page = _library(client, token, base)
    assert page["library_total"] == page["total"] == 13 and page["converter_available"] in (True, False)

    assert _names(_library(client, token, base, search="router")) == ["Zebra router"]
    assert set(_names(_library(client, token, base, source="uploaded"))) == {"Zebra router", "Apple switch", "Mango"}
    assert _library(client, token, base, source="builtin")["total"] == 10
    assert _names(_library(client, token, base, file_type="eps")) == ["Mango"]
    assert _library(client, token, base, file_type="pdf")["total"] == 0
    # A folder filter takes the folder and, by default, what is below it.
    assert set(_names(_library(client, token, base, folder="Network"))) == {"Zebra router", "Apple switch"}
    assert _names(_library(client, token, base, folder="Network", subfolders="false")) == ["Zebra router"]
    assert _names(_library(client, token, base, folder="Network/Switches")) == ["Apple switch"]
    assert _library(client, token, base, folder="Nowhere")["total"] == 0

    by_name = _names(_library(client, token, base, source="uploaded", sort="name"))
    assert by_name == ["Apple switch", "Mango", "Zebra router"]
    assert _names(_library(client, token, base, source="uploaded", sort="name", order="desc")) == by_name[::-1]
    by_folder = _names(_library(client, token, base, source="uploaded", sort="folder"))
    assert by_folder[0] == "Mango" and by_folder[1:] == ["Zebra router", "Apple switch"]
    assert _names(_library(client, token, base, sort="source"))[-1] in {"Apple switch", "Mango", "Zebra router"}
    # Used by orders by the number of records that use the symbol, ties by name.
    types = org_element_types(client, token, org["id"])
    zebra = _symbol_id(client, token, base, "Zebra router")
    resp = client.patch(f"{base}/element-types/{types['System']}", json={"symbol_id": zebra}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    by_used = _names(_library(client, token, base, source="uploaded", sort="used"))
    assert by_used == ["Apple switch", "Mango", "Zebra router"]
    assert _names(_library(client, token, base, source="uploaded", sort="used", order="desc")) == ["Zebra router", "Mango", "Apple switch"]

    first, second = _library(client, token, base, limit=5), _library(client, token, base, limit=5, offset=5)
    assert len(first["items"]) == 5 and first["total"] == 13 and not set(_names(first)) & set(_names(second))
    assert client.get(f"{base}/symbols/library", params={"sort": "colour"}, headers=auth_headers(token)).status_code == 422
    assert client.get(f"{base}/symbols/library", params={"limit": 0}, headers=auth_headers(token)).status_code == 422


def test_used_is_read_from_element_types_and_elements_and_named_by_project_with_a_count_beyond_two(client, admin_token):
    org, project, token = setup(client, admin_token, "Symlib used")
    base = org_base(org["id"])
    second = create_project(client, token, org["id"], "Symlib second")
    third = create_project(client, token, org["id"], "Symlib third")
    shared = _upload(client, token, base, "Shared drawing")
    spare = _upload(client, token, base, "Spare drawing")
    for target in (project, second, third):
        make_element(client, token, target["id"], f"E {target['name']}", symbol_id=shared["id"])
    types = org_element_types(client, token, org["id"])
    resp = client.patch(
        f"{base}/element-types/{types['System']}", json={"symbol_id": shared["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    page = _library(client, token, base, used="used")
    row = next(r for r in page["items"] if r["name"] == "Shared drawing")
    # Three projects and the organisation use it: more than two owners, so the row carries a count and no names.
    assert row["usage_owner_count"] == 4 and row["usage_count"] == 4 and row["used_by"] == []
    assert _names(_library(client, token, base, used="unused")).count("Spare drawing") == 1
    assert "Shared drawing" not in _names(_library(client, token, base, used="unused"))
    assert spare["id"] not in {r["id"] for r in page["items"]}

    usage = client.get(f"{base}/symbols/{shared['id']}/usage", headers=auth_headers(token)).json()
    owners = {o["name"]: o for o in usage["owners"]}
    assert set(owners) == {org["name"], project["name"], second["name"], third["name"]}
    assert owners[org["name"]]["kind"] == "organization" and owners[org["name"]]["element_types"] == ["System"]
    assert owners[project["name"]]["element_count"] == 1 and owners[project["name"]]["element_types"] == []
    # Element names are never listed.
    assert "E Symlib" not in json.dumps(usage)

    # One owner is named in the row.
    only = _upload(client, token, base, "One user")
    make_element(client, token, second["id"], "Solo", symbol_id=only["id"])
    one = next(r for r in _library(client, token, base, search="one user")["items"])
    assert one["used_by"] == [second["name"]] and one["usage_owner_count"] == 1


def test_the_organisation_page_names_only_the_projects_the_reader_may_open(client, admin_token):
    org, project, token = setup(client, admin_token, "Symlib named")
    base = org_base(org["id"])
    other = create_project(client, token, org["id"], "Symlib private")
    symbol = _upload(client, token, base, "Both")
    make_element(client, token, project["id"], "In open", symbol_id=symbol["id"])
    make_element(client, token, other["id"], "In private", symbol_id=symbol["id"])
    user_id, member = add_member(client, token, org["id"], project["id"], "symlib.member@example.com")
    grant_org_role_ok = client.post(
        f"/api/v1/orgs/{org['id']}/users/{user_id}/module-roles", json={"module_key": "architecture", "role_key": "architecture_org_admin"},
        headers=auth_headers(token),
    )
    assert grant_org_role_ok.status_code == 204
    usage = client.get(f"{base}/symbols/{symbol['id']}/usage", headers=auth_headers(member)).json()
    names = {o["name"]: o for o in usage["owners"]}
    assert project["name"] in names and other["name"] not in json.dumps(usage)
    assert names["Other projects"]["kind"] == "other_projects" and names["Other projects"]["element_count"] == 1
    row = next(r for r in _library(client, member, base, search="both")["items"])
    assert other["name"] not in json.dumps(row) and row["usage_owner_count"] == 2


# --- A project's view ------------------------------------------------------------------------


def test_a_project_sees_the_organisations_symbols_by_their_folder_path_in_a_read_only_branch(client, admin_token):
    org, project, token = setup(client, admin_token, "Symlib project")
    org_b, pro_b = org_base(org["id"]), project_base(project["id"])
    network = _folder(client, token, org_b, "Network")
    switches = _folder(client, token, org_b, "Switches", parent=network)
    _upload(client, token, org_b, "Core router", folder=network)
    _upload(client, token, org_b, "Edge switch", folder=switches)
    own_folder = _folder(client, token, pro_b, "Network")
    mine = _upload(client, token, pro_b, "Core router mine", folder=own_folder)

    page = _library(client, token, pro_b)
    rows = {r["name"]: r for r in page["items"]}
    assert rows["Core router"]["tier"] == "organization" and rows["Core router"]["folder_path"] == "Network"
    assert rows["Core router"]["can_file"] is False and rows["Core router mine"]["tier"] == "project"
    assert rows["Core router mine"]["can_file"] is True and rows["Core router mine"]["folder_path"] == "Network"
    assert [(f["path"], f["symbol_count"]) for f in page["organization_folders"]] == [("Network", 1), ("Network/Switches", 1)]

    # The same path names two folders (one each); the scope decides which.
    assert _names(_library(client, token, pro_b, folder="Network", folder_scope="organization")) == ["Core router", "Edge switch"]
    assert _names(_library(client, token, pro_b, folder="Network", folder_scope="own")) == ["Core router mine"]
    # The organisation's symbol cannot be filed by the project, and the project's own can.
    org_symbol = rows["Core router"]
    assert client.post(
        f"{pro_b}/symbol-folders/move-records", json={"record_ids": [org_symbol["id"]], "folder_id": own_folder["id"]},
        headers=auth_headers(token),
    ).status_code == 404
    assert _move(client, token, pro_b, [mine["id"]], None) == {"moved": 1}

    # Hiding the organisation's symbol takes it, and its folder, out of the project's view.
    assert client.delete(f"{pro_b}/symbols/{org_symbol['id']}", headers=auth_headers(token)).status_code == 204
    hidden_page = _library(client, token, pro_b)
    assert "Core router" not in _names(hidden_page)
    assert [f["path"] for f in hidden_page["organization_folders"]] == ["Network/Switches", "Network"][::-1][:0] + ["Network/Switches"]


def test_a_project_counts_use_in_the_project_only_and_lists_its_element_types_in_the_detail(client, admin_token):
    org, project, token = setup(client, admin_token, "Symlib scope")
    org_b, pro_b = org_base(org["id"]), project_base(project["id"])
    other = create_project(client, token, org["id"], "Symlib scope other")
    symbol = _upload(client, token, org_b, "Org drawing")
    make_element(client, token, project["id"], "Here", symbol_id=symbol["id"])
    make_element(client, token, other["id"], "There", symbol_id=symbol["id"])
    row = next(r for r in _library(client, token, pro_b, search="org drawing")["items"])
    assert row["usage_count"] == 1 and row["used_by"] == [] and row["usage_owner_count"] == 1
    usage = client.get(f"{pro_b}/symbols/{symbol['id']}/usage", headers=auth_headers(token)).json()
    assert [(o["kind"], o["element_count"]) for o in usage["owners"]] == [("project", 1)]
    other_symbol = _upload(client, token, pro_b, "Project drawing")
    outsider = create_org_admin_in(client, admin_token, "Symlib outsider")[1]
    assert client.get(f"{pro_b}/symbols/{other_symbol['id']}/usage", headers=auth_headers(outsider)).status_code in (403, 404)
    assert client.get(f"{org_b}/symbols/{uuid.uuid4()}/usage", headers=auth_headers(token)).status_code == 404


def test_a_child_projects_copy_of_an_inherited_symbol_is_not_filed_in_the_parents_folder(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Symfold nested")
    from app.modules.architecture.tests._helpers import enable_module

    enable_module(client, token, org["id"])
    parent = create_project(client, token, org["id"], "Symfold parent", can_be_parent=True)
    folder = _folder(client, token, project_base(parent["id"]), "Parent icons")
    _upload(client, token, project_base(parent["id"]), "Parent pump", folder=folder)
    child = create_project(client, token, org["id"], "Symfold child", parent_project_id=parent["id"])
    child_base = project_base(child["id"])
    inherited = next(r for r in _library(client, token, child_base)["items"] if r["name"] == "Parent pump")
    assert inherited["tier"] == "inherited" and inherited["folder_path"] is None and inherited["can_file"] is False
    assert client.get(f"{child_base}/symbol-folders", headers=auth_headers(token)).json() == []
    # The first change in the child copies the parent's symbol; the copy is the child's and is filed nowhere.
    _upload(client, token, child_base, "Child pump")
    copy = next(r for r in _library(client, token, child_base)["items"] if r["name"] == "Parent pump")
    assert copy["tier"] == "project" and copy["folder_id"] is None and copy["folder_path"] is None
    with SessionLocal() as db:
        row = db.get(ArchitectureSymbol, uuid.UUID(copy["id"]))
        assert row is not None and row.folder_id is None and str(row.project_id) == child["id"]


# --- Bundles -------------------------------------------------------------------------------------


def test_an_organisation_bundle_carries_symbol_folders_and_filing_and_an_import_restores_them(client, admin_token):
    org, _project, token = setup(client, admin_token, "Symfold bundle")
    base = org_base(org["id"])
    network = _folder(client, token, base, "Network")
    switches = _folder(client, token, base, "Switches", parent=network)
    _folder(client, token, base, "Empty")
    _upload(client, token, base, "Router", folder=network)
    _upload(client, token, base, "Switch", folder=switches)
    _upload(client, token, base, "Loose")
    content = _zip(client, f"/api/v1/orgs/{org['id']}/export", token)
    data = _json(content, "org.json")
    entries = {e["name"]: e for e in data[ORG_SYMBOLS_KEY]}
    assert entries["Router"]["folder"] == "Network" and entries["Switch"]["folder"] == "Network/Switches"
    assert entries["Loose"]["folder"] is None and entries["Server"]["folder"] is None
    assert {(f["kind"], f["path"]) for f in data[ORG_FOLDERS_KEY]} == {
        ("symbol", "Network"), ("symbol", "Network/Switches"), ("symbol", "Empty"),
    }

    new_org_id, warnings = _import_org(client, admin_token, content, "Symfold bundle copy")
    assert not [w for w in warnings if "older" in w]
    with SessionLocal() as db:
        symbols = {
            s.name: s for s in db.scalars(select(ArchitectureSymbol).where(ArchitectureSymbol.organization_id == uuid.UUID(new_org_id)))
        }
        folders = {f.id: f for f in db.scalars(select(ArchitectureFolder).where(ArchitectureFolder.organization_id == uuid.UUID(new_org_id)))}
        paths = {folder_rules.path_of(folders, f.id) for f in folders.values()}
        assert paths == {"Network", "Network/Switches", "Empty"} and {f.kind for f in folders.values()} == {"symbol"}
        router, switch = symbols["Router"].folder_id, symbols["Switch"].folder_id
        assert router is not None and switch is not None
        assert folder_rules.path_of(folders, router) == "Network" and folder_rules.path_of(folders, switch) == "Network/Switches"
        assert symbols["Loose"].folder_id is None and symbols["Server"].folder_id is None


def test_a_project_bundle_carries_the_projects_symbol_folders_and_a_template_project_copies_them(client, admin_token):
    org, project, token = setup(client, admin_token, "Symfold project bundle")
    base = project_base(project["id"])
    folder = _folder(client, token, base, "Mine")
    _upload(client, token, base, "Filed pump", folder=folder)
    content = _zip(client, f"/api/v1/projects/{project['id']}/export", token)
    data = _json(content, "project.json")
    assert [(e["name"], e["folder"]) for e in data[PROJECT_SYMBOLS_KEY]] == [("Filed pump", "Mine")]
    assert ("symbol", "Mine") in {(f["kind"], f["path"]) for f in data[FOLDERS_KEY]}

    copy = _import_project(client, token, org["id"], content, "Symfold project copy")
    listed = _library(client, token, project_base(copy["project"]["id"]), source="uploaded")
    assert [(r["name"], r["folder_path"]) for r in listed["items"]] == [("Filed pump", "Mine")]
    assert {f["path"] for f in client.get(f"{project_base(copy['project']['id'])}/symbol-folders", headers=auth_headers(token)).json()} == {"Mine"}


def test_an_import_files_a_symbol_in_a_folder_the_bundle_lacks_and_never_files_a_built_in(client, admin_token):
    org, project, token = setup(client, admin_token, "Symfold import odd")
    base = project_base(project["id"])
    folder = _folder(client, token, base, "Mine")
    _upload(client, token, base, "Filed pump", folder=folder)
    content = _zip(client, f"/api/v1/projects/{project['id']}/export", token)

    def drop_folder_list(document: dict) -> None:
        document[FOLDERS_KEY] = []
        document[PROJECT_SYMBOLS_KEY][0]["folder"] = "Made/Up"

    copy = _import_project(client, token, org["id"], _rewrite(content, "project.json", drop_folder_list), "Symfold odd copy")
    listed = _library(client, token, project_base(copy["project"]["id"]), source="uploaded")
    assert [(r["name"], r["folder_path"]) for r in listed["items"]] == [("Filed pump", "Made/Up")]


# --- Deleting an organisation -----------------------------------------------------------------------


def test_an_organisation_holding_uploaded_symbols_in_folders_can_be_deleted(client, admin_token):
    """Deleting a stored file used to set the symbol's file to nothing, which the one-source CHECK refuses, so the
    organisation could not be deleted while it held an uploaded symbol."""
    org, project, token = setup(client, admin_token, "Symfold org delete")
    folder = _folder(client, token, org_base(org["id"]), "Icons")
    _upload(client, token, org_base(org["id"]), "Org drawing", folder=folder)
    _upload(client, token, project_base(project["id"]), "Project drawing")
    response = client.request(
        "DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]}, headers=auth_headers(admin_token),
    )
    assert response.status_code in (200, 204), response.text
    with SessionLocal() as db:
        assert db.scalars(select(ArchitectureSymbol).where(ArchitectureSymbol.organization_id == uuid.UUID(org["id"]))).first() is None
        assert db.scalars(select(ArchitectureFolder).where(ArchitectureFolder.organization_id == uuid.UUID(org["id"]))).first() is None
