"""The organisation's one report look (accent, logo, footer, cover page, chapters): where it is set, who applies it,
how a custom layout reads it, and how it travels in a bundle.

A built-in report applies the look automatically. A custom layout is never forced: it prints the footer text, cover page
and logo only where it reads them (`{{org.footer_text}}`, `if org.include_cover_page`, the `org_logo` image).
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

import pytest
from PIL import Image as PilImage
from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.services.org_export import import_org_bundle
from app.services.report_layout_tree import empty_tree, validate_tree
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project
from tests.link_world import World

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0121_org_report_look.py"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Look Org")


def _png() -> bytes:
    buffer = io.BytesIO()
    PilImage.new("RGB", (40, 20), (200, 30, 30)).save(buffer, "PNG")
    return buffer.getvalue()


def set_look(world: World, *, footer: str | None = None, cover: bool | None = None, chapters: bool | None = None,
             accent: str | None = None, logo: bool | None = None) -> None:
    """Sets the organisation's report look through the two endpoints that own it (Branding and Configuration)."""
    h, org = auth_headers(world.token), world.org["id"]
    branding: dict = {}
    if accent is not None:
        branding["report_accent_color_hex"] = accent
    if logo is not None:
        branding["report_include_logo"] = logo
    if branding:
        assert world.client.put(f"/api/v1/orgs/{org}/branding", json=branding, headers=h).status_code == 200
    config: dict = {}
    if footer is not None:
        config["report_footer_text"] = footer
    if cover is not None:
        config["report_include_cover_page"] = cover
    if chapters is not None:
        config["report_chapters_per_component"] = chapters
    if config:
        assert world.client.put(f"/api/v1/orgs/{org}/advanced-settings", json=config, headers=h).status_code == 200


def upload_logo(world: World) -> None:
    resp = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/branding-image", files={"file": ("logo.png", _png(), "image/png")},
        data={"kind": "logo"}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text


def layout(world: World, nodes: list[dict], name: str = "Look layout", **root) -> dict:
    resp = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/report-layouts",
        json={"name": name, "family": "document", "tree": {**empty_tree("document"), "nodes": nodes, **root}},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def docx_of(world: World, project: dict, lay: dict) -> zipfile.ZipFile:
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{lay['id']}/run", params={"format": "docx"}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return zipfile.ZipFile(io.BytesIO(resp.content))


def part_text(archive: zipfile.ZipFile, prefix: str) -> str:
    return " ".join(archive.read(n).decode() for n in archive.namelist() if n.startswith(prefix))


# ---- where the look is set ----------------------------------------------------------------------------------------


def test_the_look_is_set_on_branding_and_configuration_and_a_partial_client_leaves_it(world):
    set_look(world, footer="Confidential", cover=True, chapters=False, accent="#ff0000", logo=False)
    h, org = auth_headers(world.token), world.org["id"]

    config = world.client.get(f"/api/v1/orgs/{org}/advanced-settings", headers=h).json()
    assert (config["report_footer_text"], config["report_include_cover_page"], config["report_chapters_per_component"]) == (
        "Confidential", True, False,
    )
    branded = world.client.get(f"/api/v1/orgs/{org}", headers=h).json()
    assert (branded["report_accent_color_hex"], branded["report_include_logo"]) == ("#ff0000", False)

    # A client that sends neither the report fields nor anything about them must not reset the look.
    assert world.client.put(f"/api/v1/orgs/{org}/advanced-settings", json={}, headers=h).status_code == 200
    assert world.client.put(f"/api/v1/orgs/{org}/branding", json={"header_title": "Hi"}, headers=h).status_code == 200
    again = world.client.get(f"/api/v1/orgs/{org}/advanced-settings", headers=h).json()
    assert again["report_footer_text"] == "Confidential" and again["report_include_cover_page"] is True
    assert world.client.get(f"/api/v1/orgs/{org}", headers=h).json()["report_accent_color_hex"] == "#ff0000"

    # An empty footer clears it; null accent follows the UI accent again.
    set_look(world, footer="   ")
    assert world.client.get(f"/api/v1/orgs/{org}/advanced-settings", headers=h).json()["report_footer_text"] is None
    assert world.client.put(f"/api/v1/orgs/{org}/branding", json={"report_accent_color_hex": None}, headers=h).status_code == 200
    assert world.client.get(f"/api/v1/orgs/{org}", headers=h).json()["report_accent_color_hex"] is None


def test_only_an_org_admin_may_change_the_look_and_the_accent_must_be_a_colour(world, client, admin_token):
    _, other = create_org_admin_in(client, admin_token, "Look Other Org")
    org = world.org["id"]
    assert client.put(f"/api/v1/orgs/{org}/branding", json={"report_accent_color_hex": "#00ff00"}, headers=auth_headers(other)).status_code == 403
    assert client.put(
        f"/api/v1/orgs/{org}/advanced-settings", json={"report_footer_text": "x"}, headers=auth_headers(other),
    ).status_code == 403
    assert client.put(
        f"/api/v1/orgs/{org}/branding", json={"report_accent_color_hex": "red"}, headers=auth_headers(world.token),
    ).status_code == 422


def test_report_templates_no_longer_exist(world):
    h, org = auth_headers(world.token), world.org["id"]
    assert world.client.get(f"/api/v1/orgs/{org}/report-templates", headers=h).status_code == 404
    assert world.client.post(f"/api/v1/orgs/{org}/report-templates", json={"name": "x"}, headers=h).status_code in (404, 405)


# ---- a built-in report applies the look; a custom layout reads it ------------------------------------------------------------


def test_a_builtin_report_applies_the_organisations_look(world):
    project = create_project(world.client, world.token, world.org["id"])
    create_component_and_category(world.client, world.token, project["id"])
    url = f"/api/v1/projects/{project['id']}/reports"
    h = auth_headers(world.token)

    plain = world.client.post(url, json={"format": "docx"}, headers=h)
    assert plain.status_code == 200 and "BRAND-FOOTER" not in part_text(zipfile.ZipFile(io.BytesIO(plain.content)), "word/footer")

    set_look(world, footer="BRAND-FOOTER", accent="#ff0000")
    branded = world.client.post(url, json={"format": "docx"}, headers=h)
    assert branded.status_code == 200 and "BRAND-FOOTER" in part_text(zipfile.ZipFile(io.BytesIO(branded.content)), "word/footer")
    assert world.client.post(url, json={"format": "pdf"}, headers=h).content.startswith(b"%PDF")


def test_a_custom_layout_prints_the_footer_text_only_where_it_reads_it(world):
    project = world.project()
    set_look(world, footer="BRAND-FOOTER", cover=True)
    silent = layout(world, [{"type": "heading", "text": "Hello"}], name="Silent")
    assert "BRAND-FOOTER" not in part_text(docx_of(world, project, silent), "word/footer")

    reading = layout(
        world, [{"type": "heading", "text": "Hello"}], name="Reading",
        footer={"centre": "{{org.footer_text}} · Page {{page}}"},
    )
    assert "BRAND-FOOTER" in part_text(docx_of(world, project, reading), "word/footer")

    in_text = layout(world, [{"type": "text", "text": "Footer is {{org.footer_text}}"}], name="In text")
    assert "Footer is BRAND-FOOTER" in part_text(docx_of(world, project, in_text), "word/document")


def test_a_layout_can_test_the_cover_page_and_logo_settings(world):
    project = world.project()
    guarded = layout(world, [
        {"type": "if", "when": {"ref": "org.include_cover_page", "op": "eq", "value": True},
         "children": [{"type": "heading", "text": "THE-COVER"}], "else_children": [{"type": "heading", "text": "NO-COVER"}]},
    ])
    assert "NO-COVER" in part_text(docx_of(world, project, guarded), "word/document")
    set_look(world, cover=True)
    body = part_text(docx_of(world, project, guarded), "word/document")
    assert "THE-COVER" in body and "NO-COVER" not in body


def test_the_organisations_logo_is_an_image_source(world):
    project = world.project()
    node = {"type": "image", "file": "org_logo", "alt": "Logo", "width": 3, "width_unit": "cm"}
    lay = layout(world, [node])
    assert not [n for n in docx_of(world, project, lay).namelist() if n.startswith("word/media/")]

    upload_logo(world)
    assert [n for n in docx_of(world, project, lay).namelist() if n.startswith("word/media/")]
    banded = layout(world, [{"type": "heading", "text": "x"}], name="Logo band", header={"logo": {"file": "org_logo", "height": 1.0}})
    assert [n for n in docx_of(world, project, banded).namelist() if n.startswith("word/media/")]


# ---- what a layout may name -------------------------------------------------------------------------------------------


def _errors(tree: dict) -> list[str]:
    return [f"{e.path}: {e.message}" for e in validate_tree(tree).errors]


def test_an_unknown_organisation_setting_is_a_checked_problem():
    tree = {**empty_tree("document"), "nodes": [{"type": "text", "text": "{{org.nope}}"}]}
    assert any("not an organisation report setting" in e for e in _errors(tree))
    ok = {**empty_tree("document"), "nodes": [{"type": "text", "text": "{{org.footer_text}} {{org.report_accent}}"}]}
    assert _errors(ok) == []
    in_band = {**empty_tree("document"), "footer": {"centre": "{{org.nope}}"}}
    assert any("not an organisation report setting" in e for e in _errors(in_band))
    in_band_ok = {**empty_tree("document"), "footer": {"centre": "{{org.footer_text}}"}}
    assert _errors(in_band_ok) == []


def test_org_is_a_reserved_name_and_a_condition_on_it_is_checked():
    reserved = {**empty_tree("document"), "nodes": [
        {"type": "each", "source": {"record_type": "requirement"}, "as": "org", "children": []},
    ]}
    assert any("reserved" in e for e in _errors(reserved))
    bad_value = {**empty_tree("document"), "nodes": [
        {"type": "if", "when": {"ref": "org.include_cover_page", "op": "eq", "value": "yes"}, "children": []},
    ]}
    assert any("true or false" in e for e in _errors(bad_value))
    bad_key = {**empty_tree("document"), "nodes": [
        {"type": "if", "when": {"ref": "org.colour", "op": "eq", "value": True}, "children": []},
    ]}
    assert any("not an organisation report setting" in e for e in _errors(bad_key))


def test_the_text_format_reads_and_writes_an_organisation_condition():
    from app.services.report_layout_text import format_tree, parse_text

    source = "@layout document\n\n@if org.include_cover_page eq true\n  # Cover\n@end\n\nFooter {{org.footer_text}}\n"
    parsed = parse_text(source)
    assert parsed.ok, [e.message for e in parsed.errors]
    assert parsed.tree is not None
    cond = parsed.tree["nodes"][0]["when"]
    assert (cond["ref"], cond["op"], cond["value"]) == ("org.include_cover_page", "eq", True)
    assert "@if org.include_cover_page eq true" in format_tree(parsed.tree)


# ---- bundles ----------------------------------------------------------------------------------------------------------------


def _export(world: World) -> dict:
    exported = world.client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=auth_headers(world.token))
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        return json.loads(archive.read("org.json"))


def test_an_organisation_bundle_carries_the_look_and_no_templates(world):
    set_look(world, footer="Bundle footer", cover=True, chapters=False, accent="#112233", logo=False)
    data = _export(world)
    assert "report_templates" not in data
    assert data["report_look"] == {
        "accent_color_hex": "#112233", "include_cover_page": True, "include_logo": False, "footer_text": "Bundle footer",
        "chapters_per_component": False,
    }


def _rebundle(world: World, data: dict) -> bytes:
    """The organisation's export with its `org.json` replaced by `data`."""
    exported = world.client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=auth_headers(world.token))
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported.content)) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, json.dumps(data).encode() if item.filename == "org.json" else zin.read(item.filename))
    return out.getvalue()


def test_an_old_bundle_with_templates_becomes_the_look_and_extra_templates_are_dropped(world, client, admin_token):
    set_look(world, footer="x")
    data = _export(world)
    del data["report_look"]
    data["report_templates"] = [
        {"name": "Other", "accent_color_hex": "#010101", "include_cover_page": False, "include_logo": True, "footer_text": "OTHER",
         "chapters_per_component": True, "is_default": False},
        {"name": "Corporate", "accent_color_hex": "#abcdef", "include_cover_page": True, "include_logo": False,
         "footer_text": "CORP", "chapters_per_component": False, "is_default": True},
    ]
    bundle = _rebundle(world, data)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.is_server_admin))
        org, warnings = import_org_bundle(db, name=f"Imported Look {uuid.uuid4().hex[:6]}", zip_bytes=bundle, current_user=admin)
        assert (org.report_accent_color_hex, org.report_footer_text, org.report_include_cover_page) == ("#abcdef", "CORP", True)
        assert org.report_include_logo is False and org.report_chapters_per_component is False
        assert any("1 report template(s)" in w for w in warnings)


# ---- the migration's rewrite of a layout ---------------------------------------------------------------------------------


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0121", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_a_migrated_layout_is_valid_and_reads_the_organisations_values():
    migrate = _migration()._migrated_tree
    original = {**empty_tree("document"), "nodes": [{"type": "heading", "text": "Body"}]}

    assert migrate(original, footer_text=False, cover=False, logo=False) is None  # nothing to carry over

    migrated = migrate(original, footer_text=True, cover=True, logo=True)
    assert migrated is not None and _errors(migrated) == []
    assert migrated["footer"]["centre"] == "{{org.footer_text}}  ·  Page {{page}}" and migrated["footer"]["first_page"] == "none"
    assert migrated["header"]["logo"]["file"] == "org_logo"
    cover, body = migrated["nodes"]
    assert cover["type"] == "if" and cover["when"]["ref"] == "org.include_cover_page" and body == original["nodes"][0]
    assert original["nodes"] == [{"type": "heading", "text": "Body"}]  # the source tree is not changed


def test_a_migration_keeps_a_layouts_own_header_and_footer():
    migrate = _migration()._migrated_tree
    own = {**empty_tree("document"), "header": {"left": "Mine"}, "footer": {"centre": "Mine too"}, "nodes": []}
    assert migrate(own, footer_text=True, cover=False, logo=True) is None


def test_the_migration_is_one_revision_after_the_last_and_no_template_table_remains(world):
    text = MIGRATION.read_text()
    assert 'down_revision: str | None = "0120"' in text
    from sqlalchemy import inspect
    with SessionLocal() as db:
        assert not inspect(db.get_bind()).has_table("report_templates")
        assert "report_template_id" not in {c["name"] for c in inspect(db.get_bind()).get_columns("report_layouts")}
    assert re.search(r"^revision: str = \"0121\"", text, re.M)


def _rows(sql: str, **params):
    from sqlalchemy import text

    with SessionLocal() as db:
        return db.execute(text(sql), params).all()


def test_the_migration_saves_a_new_version_of_a_layout_whose_old_output_printed_branding(world):
    """`_migrate_layouts` against the real tables: a layout whose effective template had a footer, a cover and a logo
    reads the organisation's values from version 2; a layout that wrote its own footer and header is left alone."""
    from sqlalchemy import text

    migration = _migration()
    set_look(world, footer="MIG-FOOTER", cover=True)
    upload_logo(world)
    plain = layout(world, [{"type": "heading", "text": "Body"}], name="Plain")
    own = layout(world, [{"type": "heading", "text": "Own"}], name="Own bands", header={"left": "H"}, footer={"centre": "F"})
    template = {"footer_text": "MIG-FOOTER", "include_cover_page": True, "include_logo": True}
    org_id = uuid.UUID(world.org["id"])
    with SessionLocal() as db:
        migrated = migration._migrate_layouts(db.connection(), {}, {org_id: template}, {org_id})
        db.commit()
    assert migrated == 2  # `Own bands` still gets the cover block; its own header and footer stay

    versions = {r.name: (r.current_version, r.tree) for r in _rows(
        "SELECT l.name, l.current_version, v.tree FROM report_layouts l JOIN report_layout_versions v "
        "ON v.layout_id = l.id AND v.version = l.current_version WHERE l.organization_id = :o", o=org_id,
    )}
    version, tree = versions["Plain"]
    assert version == 2 and tree["footer"]["centre"].startswith("{{org.footer_text}}") and tree["header"]["logo"]["file"] == "org_logo"
    assert _errors(tree) == []
    _, own_tree = versions["Own bands"]
    assert own_tree["footer"] == {"centre": "F"} and own_tree["header"] == {"left": "H"}
    hashes = _rows("SELECT tree_hash FROM report_layout_versions WHERE layout_id = :l AND version = 2", l=uuid.UUID(plain["id"]))
    assert hashes and len(hashes[0][0]) == 64 and own["id"]

    project = world.project()
    archive = docx_of(world, project, plain)  # the migrated layout still runs, and prints the organisation's footer
    assert "MIG-FOOTER" in part_text(archive, "word/footer")
    assert [n for n in archive.namelist() if n.startswith("word/media/")]
    with SessionLocal() as db:
        assert db.execute(text("SELECT count(*) FROM report_layout_versions WHERE layout_id = :l"), {"l": uuid.UUID(plain["id"])}).scalar() == 2


def test_the_migration_strips_a_packs_template_name_and_rehashes_the_definition(world):
    from sqlalchemy import text

    from app.services.report_pack_definition import definition_hash

    resp = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/report-packs",
        json={"name": "Old pack", "definition": {"schema_version": 1, "entries": []}}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    pack_id = uuid.UUID(resp.json()["id"])
    with SessionLocal() as db:
        db.execute(
            text("UPDATE report_pack_versions SET definition = definition || CAST(:t AS JSONB) WHERE pack_id = :p"),
            {"t": json.dumps({"template": "Corporate"}), "p": pack_id},
        )
        db.commit()
        assert _migration()._strip_pack_templates(db.connection()) >= 1
        db.commit()
    [(definition, stored_hash)] = _rows("SELECT definition, definition_hash FROM report_pack_versions WHERE pack_id = :p", p=pack_id)
    assert "template" not in definition and stored_hash == definition_hash(definition)
