"""Tests for the symbol sections of the bundles (`export.py`): a project's own symbols travel with their files and the
organisation symbols it hides by name, an organisation's library travels in the organisation bundle, a type or element
names its symbol by tier and name (never by id), an import checks and sanitises every file again and takes no id from a
bundle, a built-in is never doubled, and a project created from a template receives the template's symbols. Every test
builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.architecture.export import HIDDEN_SYMBOLS_KEY, ORG_SYMBOLS_KEY, PROJECT_KEYS, PROJECT_SYMBOLS_KEY
from app.modules.architecture.models import ArchitectureElement, ArchitectureElementType, ArchitectureSymbol
from app.modules.architecture.tests._helpers import enable_module, make_element, make_org_element, org_base, project_base, setup
from app.modules.architecture.tests.test_architecture_symbols import ENTITY, HOSTILE, PUMP, _content, _png, _symbols, _upload
from tests.conftest import auth_headers, create_org_admin_in


def _zip(client, url, token) -> bytes:
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _json(content: bytes, entry: str) -> dict:
    return json.loads(zipfile.ZipFile(io.BytesIO(content)).read(entry))


def _rewrite(content: bytes, entry: str, change: Callable[[dict], None], files: Callable[[str, bytes], bytes] | None = None) -> bytes:
    """The bundle with `entry` (a JSON file) changed by `change`, and optionally every `files/` entry's bytes replaced."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == entry:
                parsed = json.loads(data)
                change(parsed)
                data = json.dumps(parsed).encode()
            elif files is not None and item.filename.startswith("files/"):
                data = files(item.filename, data)
            dst.writestr(item, data)
    return out.getvalue()


def _replacing(payload: bytes) -> Callable[[str, bytes], bytes]:
    """A `_rewrite` file hook that swaps every embedded file's bytes for `payload`."""

    def replace(_name: str, _data: bytes) -> bytes:
        return payload

    return replace


def _import_project(client, token, org_id, content: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _import_org(client, admin_token, content: bytes, name: str) -> tuple[str, list[str]]:
    resp = client.post(
        "/api/v1/orgs/import", data={"name": name}, files={"file": ("bundle.zip", content, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["organization"]["id"], resp.json().get("warnings", [])


def _elements(client, token, project_id) -> dict[str, dict]:
    resp = client.get(f"{project_base(project_id)}/elements", headers=auth_headers(token))
    return {e["name"]: e for e in resp.json()}


def _project_with_symbols(client, admin_token, name: str):
    """A project with an own symbol, a hidden organisation symbol, a type and elements that use them."""
    org, project, token = setup(client, admin_token, name)
    base, h = project_base(project["id"]), auth_headers(token)
    pump = _upload(client, token, base, PUMP, name="Pump")
    symbols = _symbols(client, token, base)
    client.delete(f"{base}/symbols/{symbols['Firewall']['id']}", headers=h)
    pumps = client.post(f"{base}/element-types", json={"name": "Pumps", "symbol_id": pump["id"]}, headers=h).json()
    make_element(client, token, project["id"], "Station", type_name="Pumps")
    make_element(client, token, project["id"], "Cloud store", symbol_id=symbols["Cloud"]["id"])
    make_element(client, token, project["id"], "Pump house", symbol_id=pump["id"])
    return org, project, token, pump, pumps


def test_a_project_exports_its_symbols_with_files_and_names_and_never_ids(client, admin_token):
    _org, project, token, pump, _pumps = _project_with_symbols(client, admin_token, "Arch symbol bundle export")
    content = _zip(client, f"/api/v1/projects/{project['id']}/export", token)
    data = _json(content, "project.json")

    [entry] = data[PROJECT_SYMBOLS_KEY]
    assert entry["name"] == "Pump" and entry["builtin_key"] is None and entry["filename"] == "pump.svg"
    assert f"files/{entry['file_ref']}" in zipfile.ZipFile(io.BytesIO(content)).namelist()
    assert data[HIDDEN_SYMBOLS_KEY] == ["Firewall"]
    [local_type] = data["architecture_project_element_types"]
    assert local_type["symbol"] == {"tier": "project", "name": "Pump"} and "symbol_id" not in local_type
    by_name = {e["name"]: e for e in data["architecture_elements"]}
    assert by_name["Cloud store"]["symbol"] == {"tier": "organisation", "name": "Cloud"}
    assert by_name["Pump house"]["symbol"] == {"tier": "project", "name": "Pump"} and by_name["Station"]["symbol"] is None
    architecture = {key: value for key, value in data.items() if key.startswith("architecture_")}
    assert pump["id"] not in json.dumps(architecture) and "symbol_id" not in json.dumps(architecture)


def test_a_project_import_recreates_the_symbols_and_points_types_and_elements_at_them(client, admin_token):
    org, project, token, pump, _pumps = _project_with_symbols(client, admin_token, "Arch symbol bundle import")
    content = _zip(client, f"/api/v1/projects/{project['id']}/export", token)
    imported = _import_project(client, token, org["id"], content, "Arch symbol bundle import copy")
    copy_id = imported["project"]["id"]
    base = project_base(copy_id)

    copy_symbols = _symbols(client, token, base)
    assert "Firewall" not in copy_symbols
    copied = copy_symbols["Pump"]
    assert copied["project_id"] == copy_id and copied["id"] != pump["id"]
    assert _content(client, token, base, copied["id"]).text == _content(client, token, project_base(project["id"]), pump["id"]).text

    elements = _elements(client, token, copy_id)
    assert elements["Pump house"]["symbol_id"] == copied["id"]
    assert elements["Cloud store"]["symbol_id"] == copy_symbols["Cloud"]["id"]
    assert elements["Station"]["symbol_id"] is None and elements["Station"]["effective_symbol_id"] == copied["id"]
    local_type = next(t for t in client.get(f"{base}/element-types", headers=auth_headers(token)).json() if t["name"] == "Pumps")
    assert local_type["symbol_id"] == copied["id"]


def test_a_symbol_the_target_organisation_lacks_is_reported_and_the_record_keeps_its_shape(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch symbol bundle lacking")
    custom = _upload(client, token, org_base(org["id"]), PUMP, name="Custom pump")
    make_element(client, token, project["id"], "Pumpish", symbol_id=custom["id"])
    content = _zip(client, f"/api/v1/projects/{project['id']}/export", token)
    assert _json(content, "project.json")["architecture_elements"][0]["symbol"] == {"tier": "organisation", "name": "Custom pump"}

    other_org, other_token = create_org_admin_in(client, admin_token, "Arch symbol bundle lacking target")
    enable_module(client, other_token, other_org["id"])
    imported = _import_project(client, other_token, other_org["id"], content, "Arch symbol bundle lacking copy")
    assert any("Custom pump" in w for w in imported.get("warnings", []))
    assert _elements(client, other_token, imported["project"]["id"])["Pumpish"]["symbol_id"] is None


def test_an_import_takes_no_symbol_id_from_a_bundle(client, admin_token):
    """A crafted bundle that names another organisation's symbol by id gets no reference to it."""
    org, project, token, _pump, _pumps = _project_with_symbols(client, admin_token, "Arch symbol bundle forged")
    other_org, _other_project, other_token = setup(client, admin_token, "Arch symbol bundle forged other")
    foreign = _symbols(client, other_token, org_base(other_org["id"]))["Server"]
    content = _zip(client, f"/api/v1/projects/{project['id']}/export", token)

    def forge(data: dict) -> None:
        for entry in [*data["architecture_project_element_types"], *data["architecture_elements"]]:
            entry["symbol_id"] = foreign["id"]
            entry["symbol"] = None

    imported = _import_project(client, token, org["id"], _rewrite(content, "project.json", forge), "Arch symbol bundle forged copy")
    copy_id = uuid.UUID(imported["project"]["id"])
    with SessionLocal() as db:
        types = list(db.scalars(select(ArchitectureElementType).where(ArchitectureElementType.project_id == copy_id)))
        elements = list(db.scalars(select(ArchitectureElement).where(ArchitectureElement.project_id == copy_id)))
    assert types and elements
    assert all(t.symbol_id is None for t in types) and all(e.symbol_id is None for e in elements)


def test_an_embedded_file_is_checked_and_sanitised_again_on_import(client, admin_token):
    org, project, token, _pump, _pumps = _project_with_symbols(client, admin_token, "Arch symbol bundle hostile")
    content = _zip(client, f"/api/v1/projects/{project['id']}/export", token)

    hostile = _import_project(
        client, token, org["id"], _rewrite(content, "project.json", lambda _d: None, _replacing(HOSTILE.encode())),
        "Arch symbol bundle hostile copy",
    )
    base = project_base(hostile["project"]["id"])
    stored = _content(client, token, base, _symbols(client, token, base)["Pump"]["id"]).text
    assert "script" not in stored and "onclick" not in stored and "<image" not in stored

    for label, payload in (("entity", ENTITY.encode()), ("raster", _png()), ("empty", b"")):
        refused = _import_project(
            client, token, org["id"], _rewrite(content, "project.json", lambda _d: None, _replacing(payload)),
            f"Arch symbol bundle refused {label}",
        )
        assert "Pump" not in _symbols(client, token, project_base(refused["project"]["id"])), label
        assert any("Pump" in w for w in refused.get("warnings", [])), label

    stripped = _rewrite(content, "project.json", lambda d: d[PROJECT_SYMBOLS_KEY][0].update(file_ref="nothing_here.svg"))
    gone = _import_project(client, token, org["id"], stripped, "Arch symbol bundle no file")
    assert "Pump" not in _symbols(client, token, project_base(gone["project"]["id"]))
    assert any("not in the bundle" in w for w in gone.get("warnings", []))


def test_an_organisation_bundle_carries_the_library_and_does_not_double_the_builtins(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch symbol bundle org")
    h = auth_headers(token)
    custom = _upload(client, token, org_base(org["id"]), PUMP, name="Org pump")
    org_types = client.get(f"{org_base(org['id'])}/element-types", headers=h).json()
    client.patch(f"{org_base(org['id'])}/element-types/{org_types[0]['id']}", json={"symbol_id": custom["id"]}, headers=h)
    content = _zip(client, f"/api/v1/orgs/{org['id']}/export", token)

    data = _json(content, "org.json")
    by_name = {e["name"]: e for e in data[ORG_SYMBOLS_KEY]}
    assert by_name["Org pump"]["builtin_key"] is None and by_name["Server"]["builtin_key"] == "server" and "file_ref" not in by_name["Server"]
    assert f"files/{by_name['Org pump']['file_ref']}" in zipfile.ZipFile(io.BytesIO(content)).namelist()
    assert data["architecture_element_types"][0]["symbol"] == {"tier": "organisation", "name": "Org pump"}

    new_org_id, _warnings = _import_org(client, admin_token, content, "Arch symbol bundle org copy")
    with SessionLocal() as db:
        symbols = list(db.scalars(select(ArchitectureSymbol).where(ArchitectureSymbol.organization_id == uuid.UUID(new_org_id))))
        types = list(db.scalars(select(ArchitectureElementType).where(ArchitectureElementType.organization_id == uuid.UUID(new_org_id))))
    names = [s.name for s in symbols]
    assert len(names) == len(set(names)) and "Org pump" in names and names.count("Server") == 1
    copied = next(s for s in symbols if s.name == "Org pump")
    assert copied.file_asset_id is not None and copied.builtin_key is None
    first = next(t for t in types if t.name == org_types[0]["name"])
    assert first.symbol_id == copied.id


def test_an_organisation_element_keeps_its_symbol_through_an_organisation_bundle(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch symbol bundle org element")
    custom = _upload(client, token, org_base(org["id"]), PUMP, name="Org pump")
    make_org_element(client, token, org["id"], "Platform", symbol_id=custom["id"])
    content = _zip(client, f"/api/v1/orgs/{org['id']}/export", token)
    assert _json(content, "org.json")["architecture_org_elements"][0]["symbol"] == {"tier": "organisation", "name": "Org pump"}
    new_org_id, _warnings = _import_org(client, admin_token, content, "Arch symbol bundle org element copy")
    with SessionLocal() as db:
        element = db.scalar(select(ArchitectureElement).where(ArchitectureElement.organization_id == uuid.UUID(new_org_id)))
        assert element is not None and element.symbol_id is not None
        symbol = db.get(ArchitectureSymbol, element.symbol_id)
        assert symbol is not None and symbol.name == "Org pump"


def test_the_symbol_sections_are_template_configuration():
    assert {PROJECT_SYMBOLS_KEY, HIDDEN_SYMBOLS_KEY} <= PROJECT_KEYS


def test_a_project_created_from_a_template_receives_its_symbols(client, admin_token):
    org, project, token, _pump, _pumps = _project_with_symbols(client, admin_token, "Arch symbol template")
    h = auth_headers(token)
    assert client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=h).status_code == 200
    created = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "Arch symbol template child", "summary": "", "template_project_id": project["id"]},
        headers=h,
    )
    assert created.status_code == 201, created.text
    base = project_base(created.json()["id"])
    symbols = _symbols(client, token, base)
    assert symbols["Pump"]["project_id"] == created.json()["id"] and "Firewall" not in symbols
    assert _content(client, token, base, symbols["Pump"]["id"]).status_code == 200
    elements: dict[str, Any] = _elements(client, token, created.json()["id"])
    assert elements["Pump house"]["symbol_id"] == symbols["Pump"]["id"]
