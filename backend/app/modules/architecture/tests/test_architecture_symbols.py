"""Tests for the symbol library: the built-in set and its seeding, uploads (and the files they refuse), the organisation
and project tiers with hide, restore and the nested fallback, assignment to element types and elements, the in-use rule
and the shared file, who may read a symbol's SVG, and the roles that manage it. Every test builds its own organisation."""

from __future__ import annotations

import io
import uuid

from PIL import Image as PilImage
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.file import FileAsset
from app.modules.architecture.models import ArchitectureSymbol
from app.modules.architecture.service import DEFAULT_SYMBOLS, DEFAULT_TYPE_SYMBOLS
from app.modules.architecture.symbols import BUILTIN_SVG, MAX_SYMBOL_BYTES, default_name
from app.modules.architecture.tests._helpers import (
    add_member,
    element_types,
    enable_module,
    grant,
    grant_org_role,
    grant_project_role,
    make_collection,
    make_element,
    make_org_element,
    org_base,
    org_element_types,
    project_base,
    put_element,
    setup,
)
from app.services.report_svg import sanitize_svg
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

NS = 'xmlns="http://www.w3.org/2000/svg"'
PUMP = f'<svg {NS} viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="none" stroke="currentColor"/></svg>'
HOSTILE = (
    f'<svg {NS} viewBox="0 0 10 10"><script>alert(1)</script><rect width="10" height="10" onclick="alert(2)"/>'
    '<image href="https://example.com/x.png"/></svg>'
)
ENTITY = f'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "boom">]><svg {NS}><text>&x;</text></svg>'


def _png() -> bytes:
    buf = io.BytesIO()
    PilImage.new("RGB", (4, 4), "red").save(buf, "PNG")
    return buf.getvalue()


def _upload(client, token, base, svg, *, filename="pump.svg", name=None, expect=201) -> dict:
    """Uploads a symbol under `base` (a project or organisation base URL); returns the body (or the response)."""
    resp = client.post(
        f"{base}/symbols", files={"file": (filename, svg if isinstance(svg, bytes) else svg.encode(), "image/svg+xml")},
        data={"name": name} if name else None, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _symbols(client, token, base) -> dict[str, dict]:
    resp = client.get(f"{base}/symbols", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {s["name"]: s for s in resp.json()}


def _content(client, token, base, symbol_id):
    return client.get(f"{base}/symbols/{symbol_id}/content", headers=auth_headers(token))


def _file_count(org_id) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(FileAsset).where(FileAsset.organization_id == uuid.UUID(org_id))) or 0


# --- The built-in set ---------------------------------------------------------


def test_every_builtin_key_has_its_own_drawing_that_passes_the_sanitiser():
    assert set(BUILTIN_SVG) == {key for key, _name in DEFAULT_SYMBOLS}
    assert len(set(BUILTIN_SVG.values())) == len(BUILTIN_SVG)
    for key, drawing in BUILTIN_SVG.items():
        clean = sanitize_svg(drawing)
        assert "<svg" in clean and "currentColor" in clean, key
    assert set(DEFAULT_TYPE_SYMBOLS.values()) <= set(BUILTIN_SVG)


def test_a_new_organisation_has_the_builtins_in_order_and_its_seeded_types_use_them(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch symbol seed")
    symbols = client.get(f"{org_base(org['id'])}/symbols", headers=auth_headers(token)).json()
    assert [s["name"] for s in symbols] == [name for _key, name in DEFAULT_SYMBOLS]
    assert all(s["is_builtin"] and s["organization_id"] == org["id"] and s["project_id"] is None for s in symbols)
    by_key = {s["builtin_key"]: s["id"] for s in symbols}
    types = {t["name"]: t for t in client.get(f"{org_base(org['id'])}/element-types", headers=auth_headers(token)).json()}
    for type_name, key in DEFAULT_TYPE_SYMBOLS.items():
        assert types[type_name]["symbol_id"] == by_key[key]
    assert types["System"]["symbol_id"] is None and types["Component"]["symbol_id"] is None


def test_a_builtin_is_served_as_its_drawing_without_a_stored_file(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch symbol builtin")
    before = _file_count(org["id"])
    server = _symbols(client, token, org_base(org["id"]))["Server"]
    resp = _content(client, token, org_base(org["id"]), server["id"])
    assert resp.status_code == 200 and resp.text == BUILTIN_SVG["server"]
    assert _file_count(org["id"]) == before


# --- Uploads --------------------------------------------------------------------


def test_an_upload_is_stored_sanitised_and_served_with_a_restrictive_policy(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch symbol upload")
    base = org_base(org["id"])
    created = _upload(client, token, base, HOSTILE, filename="pump station.eps.svg")
    assert created["name"] == "pump station" and created["is_builtin"] is False and created["builtin_key"] is None

    resp = _content(client, token, base, created["id"])
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    policy = resp.headers["content-security-policy"]
    assert "default-src 'none'" in policy and "sandbox" in policy and "frame-ancestors 'none'" in policy
    assert resp.headers["x-content-type-options"] == "nosniff"
    # Other responses keep the application-wide policy.
    assert "frame-src" in client.get(f"{base}/symbols", headers=auth_headers(token)).headers["content-security-policy"]
    for forbidden in ("script", "onclick", "example.com", "<image"):
        assert forbidden not in resp.text
    assert "<rect" in resp.text

    with SessionLocal() as db:
        row = db.get(ArchitectureSymbol, uuid.UUID(created["id"]))
        assert row is not None and row.file_asset_id is not None
        asset = db.get(FileAsset, row.file_asset_id)
        assert asset is not None and asset.content_type == "image/svg+xml" and asset.project_id is None and asset.is_org_resource is False
        file_id = asset.id
    # The file belongs to no report library or shared resource, and the generic download route has no owner for it.
    assert client.get(f"/api/v1/files/{file_id}", headers=auth_headers(token)).status_code == 403


def test_the_given_name_wins_over_the_file_name_and_default_names_are_trimmed():
    assert default_name("Pump.SVG") == "Pump"
    assert default_name("C:\\icons\\pump.eps.svg") == "pump"
    assert default_name(".svg") == "Symbol"
    assert len(default_name("x" * 300 + ".svg")) == 100


def test_files_that_are_not_safe_svg_drawings_are_refused_and_store_nothing(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch symbol refuse")
    base = org_base(org["id"])
    before = _file_count(org["id"])
    big = f'<svg {NS}><desc>{"x" * (MAX_SYMBOL_BYTES + 10)}</desc></svg>'
    for label, payload in (
        ("entity", ENTITY), ("raster", _png()), ("empty", b""), ("text", "just words"), ("too large", big),
        ("not an svg root", '<html xmlns="http://www.w3.org/1999/xhtml"/>'),
    ):
        resp = _upload(client, token, base, payload, filename="bad.svg", name=f"bad {label}", expect=422)
        assert resp["detail"], label
    assert _file_count(org["id"]) == before
    assert not [n for n in _symbols(client, token, base) if n.startswith("bad ")]


def test_a_clashing_name_is_refused_without_leaving_a_file(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch symbol clash")
    base = org_base(org["id"])
    _upload(client, token, base, PUMP, name="Pump")
    before = _file_count(org["id"])
    assert _upload(client, token, base, PUMP, name="pump", expect=400)["detail"]
    assert _upload(client, token, base, PUMP, name="Server", expect=400)["detail"]
    assert _file_count(org["id"]) == before


def test_rename_and_reorder_work_but_a_builtin_cannot_be_renamed(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch symbol rename")
    base, h = f"{org_base(org['id'])}/symbols", auth_headers(token)
    mine = _upload(client, token, org_base(org["id"]), PUMP, name="Pump")
    assert client.patch(f"{base}/{mine['id']}", json={"name": "Pump house"}, headers=h).json()["name"] == "Pump house"
    assert client.patch(f"{base}/{mine['id']}", json={"name": "Server"}, headers=h).status_code == 400

    builtin = _symbols(client, token, org_base(org["id"]))["Device"]
    assert client.patch(f"{base}/{builtin['id']}", json={"name": "Gadget"}, headers=h).status_code == 400
    assert client.patch(f"{base}/{builtin['id']}", json={"name": "Device"}, headers=h).status_code == 200
    moved = client.post(f"{base}/{mine['id']}/move", json={"direction": "up"}, headers=h)
    assert moved.status_code == 200, moved.text


# --- Roles ------------------------------------------------------------------------


def test_only_an_architecture_admin_changes_the_library_but_any_member_reads_it(client, admin_token):
    org, project, admin = setup(client, admin_token, "Arch symbol roles")
    project_url = project_base(project["id"])
    _uid, member = add_member(client, admin, org["id"], project["id"], "symbol.member@example.com")
    user_id = create_org_user(client, admin, org["id"], "symbol.architect@example.com")
    client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(admin))
    grant_project_role(client, admin, project["id"], user_id, "architect")
    architect_token = login(client, "symbol.architect@example.com", "Password123!")

    for token in (member, architect_token):
        assert _upload(client, token, project_url, PUMP, expect=403)["detail"]
        assert client.get(f"{project_url}/symbols", headers=auth_headers(token)).status_code == 200
    own = _upload(client, admin, project_url, PUMP, name="Pump")
    assert _content(client, member, project_url, own["id"]).status_code == 200
    assert client.patch(f"{project_url}/symbols/{own['id']}", json={"name": "x"}, headers=auth_headers(member)).status_code == 403
    assert client.delete(f"{project_url}/symbols/{own['id']}", headers=auth_headers(architect_token)).status_code == 403

    # The project role does not reach the organisation's library; the organisation role does.
    org_url = org_base(org["id"])
    delegate = create_org_user(client, admin, org["id"], "symbol.orgadmin@example.com")
    delegate_token = login(client, "symbol.orgadmin@example.com", "Password123!")
    assert _upload(client, delegate_token, org_url, PUMP, expect=403)["detail"]
    grant_org_role(client, admin, org["id"], delegate, "architecture_org_admin")
    assert _upload(client, delegate_token, org_url, PUMP, name="Org pump")["name"] == "Org pump"


def test_a_disabled_module_serves_no_symbols(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch symbol disabled")
    assert client.get(f"{org_base(org['id'])}/symbols", headers=auth_headers(token)).status_code == 404
    enable_module(client, token, org["id"])
    assert client.get(f"{org_base(org['id'])}/symbols", headers=auth_headers(token)).status_code == 200


# --- Project tier, hide and restore, nested fallback --------------------------------


def test_a_project_lists_the_organisations_symbols_and_its_own_and_can_hide_and_restore(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch symbol project")
    base, h = project_base(project["id"]), auth_headers(token)
    own = _upload(client, token, base, PUMP, name="Local pump")
    assert own["project_id"] == project["id"] and own["organization_id"] is None
    listed = _symbols(client, token, base)
    assert len(listed) == len(DEFAULT_SYMBOLS) + 1 and "Local pump" in listed

    # A project symbol may share a name with nothing it can see, but not with an organisation symbol.
    assert _upload(client, token, base, PUMP, name="Server", expect=400)["detail"]

    firewall = listed["Firewall"]
    assert client.delete(f"{base}/symbols/{firewall['id']}", headers=h).status_code == 204
    assert "Firewall" not in _symbols(client, token, base)
    assert [s["name"] for s in client.get(f"{base}/symbols/hidden", headers=h).json()] == ["Firewall"]
    # The organisation's own library is unaffected.
    assert "Firewall" in _symbols(client, token, org_base(org["id"]))

    restored = client.post(f"{base}/symbols/restore", json={}, headers=h)
    assert restored.status_code == 200 and [s["name"] for s in restored.json()["restored"]] == ["Firewall"]
    assert "Firewall" in _symbols(client, token, base)


def test_a_child_project_shows_the_nearest_configured_ancestors_symbols_and_copies_them_on_first_change(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch symbol nested")
    enable_module(client, token, org["id"])
    parent = create_project(client, token, org["id"], "Arch symbol parent", can_be_parent=True)
    parent_base = project_base(parent["id"])
    parent_symbol = _upload(client, token, parent_base, PUMP, name="Parent pump")

    child = create_project(client, token, org["id"], "Arch symbol child", parent_project_id=parent["id"])
    child_base = project_base(child["id"])
    assert "Parent pump" in _symbols(client, token, child_base)
    assert _content(client, token, child_base, parent_symbol["id"]).status_code == 200

    _upload(client, token, child_base, PUMP, name="Child pump")
    child_symbols = _symbols(client, token, child_base)
    assert {"Parent pump", "Child pump"} <= set(child_symbols)
    assert child_symbols["Parent pump"]["id"] != parent_symbol["id"] and child_symbols["Parent pump"]["project_id"] == child["id"]
    assert "Child pump" not in _symbols(client, token, parent_base)

    # The copy shares the parent's file: deleting it leaves the parent's drawing readable.
    copy_id = child_symbols["Parent pump"]["id"]
    assert client.delete(f"{child_base}/symbols/{copy_id}", headers=auth_headers(token)).status_code == 204
    assert _content(client, token, parent_base, parent_symbol["id"]).status_code == 200
    assert "Parent pump" not in _symbols(client, token, child_base)


# --- Assignment and use ----------------------------------------------------------


def test_an_element_type_and_an_element_take_a_symbol_the_owner_may_use(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch symbol assign")
    base, h = project_base(project["id"]), auth_headers(token)
    mine = _upload(client, token, base, PUMP, name="Pump")
    builtin = _symbols(client, token, base)["Cloud"]

    local_type = client.post(f"{base}/element-types", json={"name": "Pumps", "symbol_id": mine["id"]}, headers=h)
    assert local_type.status_code == 201 and local_type.json()["symbol_id"] == mine["id"]
    element = make_element(client, token, project["id"], "P1", type_name="Pumps")
    assert (element["symbol_id"], element["effective_symbol_id"]) == (None, mine["id"])

    changed = put_element(client, token, project["id"], element, symbol_id=builtin["id"])
    assert (changed["symbol_id"], changed["effective_symbol_id"]) == (builtin["id"], builtin["id"])
    cleared = put_element(client, token, project["id"], changed, symbol_id=None)
    assert (cleared["symbol_id"], cleared["effective_symbol_id"]) == (None, mine["id"])

    cleared_type = client.patch(f"{base}/element-types/{local_type.json()['id']}", json={"symbol_id": None}, headers=h)
    assert cleared_type.status_code == 200 and cleared_type.json()["symbol_id"] is None
    assert put_element(client, token, project["id"], cleared)["effective_symbol_id"] is None
    # An edit that leaves the symbol out keeps it.
    kept = put_element(client, token, project["id"], cleared, symbol_id=builtin["id"])
    assert put_element(client, token, project["id"], kept, name="P1b")["symbol_id"] == builtin["id"]


def test_a_symbol_the_owner_may_not_use_is_refused_everywhere(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch symbol refuse use")
    other_org, other_project, other_token = setup(client, admin_token, "Arch symbol refuse other")
    base, h = project_base(project["id"]), auth_headers(token)
    foreign = _upload(client, other_token, org_base(other_org["id"]), PUMP, name="Foreign")
    sibling = create_project(client, token, org["id"], "Arch symbol sibling")
    sibling_symbol = _upload(client, token, project_base(sibling["id"]), PUMP, name="Sibling pump")
    hidden = _symbols(client, token, base)["Queue"]
    client.delete(f"{base}/symbols/{hidden['id']}", headers=h)
    own = _upload(client, token, base, PUMP, name="Mine")
    element = make_element(client, token, project["id"], "E1")
    component_type = element_types(client, token, project["id"])["Component"]

    for bad in (foreign["id"], sibling_symbol["id"], hidden["id"], str(uuid.uuid4())):
        assert client.post(f"{base}/element-types", json={"name": f"T {bad[:6]}", "symbol_id": bad}, headers=h).status_code == 400
        assert client.patch(f"{base}/element-types/{component_type}", json={"symbol_id": bad}, headers=h).status_code in (400, 404)
        assert client.post(
            f"{base}/elements", json={"name": "X", "element_type_id": component_type, "symbol_id": bad}, headers=h,
        ).status_code == 400
        put_element(client, token, project["id"], element, expect=400, symbol_id=bad)

    # An organisation type or element may use the organisation's symbols only, never a project's.
    org_url = org_base(org["id"])
    org_type = client.get(f"{org_url}/element-types", headers=h).json()[0]
    assert client.patch(f"{org_url}/element-types/{org_type['id']}", json={"symbol_id": own["id"]}, headers=h).status_code == 400
    org_symbol = _symbols(client, token, org_url)["Cloud"]
    assert client.patch(f"{org_url}/element-types/{org_type['id']}", json={"symbol_id": org_symbol["id"]}, headers=h).status_code == 200
    org_system = org_element_types(client, token, org["id"])["System"]
    resp = client.post(
        f"{org_url}/elements", json={"name": "Org E", "element_type_id": org_system, "symbol_id": own["id"]}, headers=h,
    )
    assert resp.status_code == 400


def test_a_symbol_in_use_cannot_be_deleted_and_its_file_goes_with_it_when_it_is_not(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch symbol delete")
    base, h = project_base(project["id"]), auth_headers(token)
    org_url = org_base(org["id"])
    mine = _upload(client, token, base, PUMP, name="Pump")
    element = make_element(client, token, project["id"], "P1", symbol_id=mine["id"])
    typed = client.post(f"{base}/element-types", json={"name": "Typed", "symbol_id": mine["id"]}, headers=h).json()

    assert client.delete(f"{base}/symbols/{mine['id']}", headers=h).status_code == 409
    assert client.delete(f"{base}/symbols/{mine['id']}", headers=h).json()["detail"]
    put_element(client, token, project["id"], element, symbol_id=None)
    assert client.delete(f"{base}/symbols/{mine['id']}", headers=h).status_code == 409
    client.patch(f"{base}/element-types/{typed['id']}", json={"symbol_id": None}, headers=h)

    with SessionLocal() as db:
        row = db.get(ArchitectureSymbol, uuid.UUID(mine["id"]))
        assert row is not None
        file_id = row.file_asset_id
    assert client.delete(f"{base}/symbols/{mine['id']}", headers=h).status_code == 204
    with SessionLocal() as db:
        assert db.get(FileAsset, file_id) is None
    assert _content(client, token, base, mine["id"]).status_code == 404

    # An organisation symbol in use by a type is protected the same way; a built-in nothing uses may be deleted.
    service = _symbols(client, token, org_url)["Server"]
    assert client.delete(f"{org_url}/symbols/{service['id']}", headers=h).status_code == 409
    user = _symbols(client, token, org_url)["User"]
    assert client.delete(f"{org_url}/symbols/{user['id']}", headers=h).status_code == 204
    assert "User" not in _symbols(client, token, org_url)


# --- Who may read a symbol -----------------------------------------------------------


def test_an_organisation_symbol_is_readable_by_members_and_a_project_symbol_only_through_its_project_or_a_shared_element(client, admin_token):
    org, owner, admin = setup(client, admin_token, "Arch symbol read")
    consumer = create_project(client, admin, org["id"], "Arch symbol read consumer")
    outsider = create_project(client, admin, org["id"], "Arch symbol read outsider")
    _c, consumer_token = add_member(client, admin, org["id"], consumer["id"], "symbol.read.c@example.com")
    _o, outsider_token = add_member(client, admin, org["id"], outsider["id"], "symbol.read.o@example.com")
    owner_base = project_base(owner["id"])
    secret = _upload(client, admin, owner_base, PUMP, name="Secret pump")
    element = make_element(client, admin, owner["id"], "Shared pump", symbol_id=secret["id"])
    builtin = _symbols(client, admin, org_base(org["id"]))["Cloud"]

    for token, project in ((consumer_token, consumer), (outsider_token, outsider)):
        assert _content(client, token, project_base(project["id"]), builtin["id"]).status_code == 200
        assert _content(client, token, project_base(project["id"]), secret["id"]).status_code == 404
        assert client.get(f"{project_base(project['id'])}/symbols/{uuid.uuid4()}/content", headers=auth_headers(token)).status_code == 404

    collection = make_collection(client, admin, owner_base, "Infra", members=[element["id"]])
    grant(client, admin, owner_base, collection["id"], project_id=consumer["id"])
    assert _content(client, consumer_token, project_base(consumer["id"]), secret["id"]).status_code == 200
    assert _content(client, outsider_token, project_base(outsider["id"]), secret["id"]).status_code == 404

    shown = client.get(f"{project_base(consumer['id'])}/elements/{element['id']}", headers=auth_headers(consumer_token)).json()
    assert shown["effective_symbol_id"] == secret["id"]


def test_a_symbol_through_the_type_of_a_shared_element_is_readable_and_another_organisation_sees_nothing(client, admin_token):
    org, owner, admin = setup(client, admin_token, "Arch symbol type read")
    consumer = create_project(client, admin, org["id"], "Arch symbol type consumer")
    _c, consumer_token = add_member(client, admin, org["id"], consumer["id"], "symbol.type.c@example.com")
    owner_base = project_base(owner["id"])
    pump = _upload(client, admin, owner_base, PUMP, name="Pump")
    pump_type = client.post(f"{owner_base}/element-types", json={"name": "Pumps", "symbol_id": pump["id"]}, headers=auth_headers(admin)).json()
    element = make_element(client, admin, owner["id"], "P1", type_name="Pumps")
    assert pump_type["symbol_id"] == pump["id"]
    assert _content(client, consumer_token, project_base(consumer["id"]), pump["id"]).status_code == 404
    collection = make_collection(client, admin, owner_base, "Infra", members=[element["id"]])
    grant(client, admin, owner_base, collection["id"], project_id=consumer["id"])
    assert _content(client, consumer_token, project_base(consumer["id"]), pump["id"]).status_code == 200

    other_org, other_project, other_token = setup(client, admin_token, "Arch symbol type other")
    assert _content(client, other_token, project_base(other_project["id"]), pump["id"]).status_code == 404
    assert _content(client, other_token, org_base(other_org["id"]), pump["id"]).status_code == 404
    assert client.get(f"{org_base(org['id'])}/symbols", headers=auth_headers(other_token)).status_code in (403, 404)


def test_an_organisation_element_may_use_an_organisation_symbol(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch symbol org element")
    cloud = _symbols(client, token, org_base(org["id"]))["Cloud"]
    element = make_org_element(client, token, org["id"], "Platform", symbol_id=cloud["id"])
    assert element["symbol_id"] == cloud["id"] and element["effective_symbol_id"] == cloud["id"]
    assert _content(client, token, org_base(org["id"]), cloud["id"]).status_code == 200
