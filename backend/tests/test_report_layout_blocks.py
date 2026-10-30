"""Tests for what the visual designer reads to draw its forms and check a draft: the block catalogue
(`GET .../report-layouts/blocks`, `services.report_layout_block_schema`) and the tree check
(`POST .../report-layouts/validate`), at the organisation and project tier.

Every registered block type must describe its form, so a module's block type needs no frontend edit; the
templates must be nodes the validator at least recognises. Each test builds its own organisation.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.report_layout import ReportLayout
from app.services import report_layout_designer
from app.services.report_layout_block_schema import FIELD_KINDS, LAYOUT_FIELDS
from app.services.report_layout_tree import BLOCK_SPECS, empty_tree, validate_tree
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import REQ, World

SECRET = "Customer-confidential-phrase-4e7a"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Blocks Org")


def org_url(world: World, suffix: str) -> str:
    return f"/api/v1/orgs/{world.org['id']}/report-layouts{suffix}"


def project_url(project: dict, suffix: str) -> str:
    return f"/api/v1/projects/{project['id']}/report-layouts{suffix}"


def member_token(world: World) -> str:
    email = f"m-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    return login(world.client, email, "Password123!")


# ---- the schemas themselves -------------------------------------------------------------------------------------


def test_every_registered_block_type_describes_its_form():
    undescribed = [key for key, spec in BLOCK_SPECS.items() if spec.schema is None]
    assert not undescribed, f"block types without a schema: {undescribed}"


def test_every_field_uses_a_kind_the_designer_can_draw_and_names_real_siblings():
    for key, spec in BLOCK_SPECS.items():
        assert spec.schema is not None
        keys = [f.key for f in spec.schema.fields]
        assert len(keys) == len(set(keys)), key
        for f in spec.schema.fields:
            assert f.kind in FIELD_KINDS, (key, f.key)
            assert f.depends_on is None or f.depends_on in keys, (key, f.key)
            assert (f.kind == "choice") == bool(f.choices), (key, f.key)
        if spec.schema.provides is not None:
            assert spec.schema.provides.key in keys, key
    assert all(f.kind in FIELD_KINDS for f in LAYOUT_FIELDS)


def test_every_field_of_a_core_block_explains_itself():
    for key, spec in BLOCK_SPECS.items():
        assert spec.schema is not None
        assert all(f.help for f in spec.schema.fields), (key, [f.key for f in spec.schema.fields if not f.help])
    assert all(f.help for f in LAYOUT_FIELDS)


def test_a_template_is_a_node_of_its_own_type_and_every_required_key_is_in_the_form():
    for key, spec in BLOCK_SPECS.items():
        schema = spec.schema
        assert schema is not None and schema.template["type"] == key
        form_keys = {f.key for f in schema.fields} | {c.key for c in schema.containers} | {"type"}
        assert set(schema.template) <= form_keys, key
        for container in schema.containers:
            assert container.key in {"children", "else_children"}


def test_a_template_in_a_new_layout_fails_only_on_what_the_author_has_yet_to_choose():
    """A blank block is not an 'unknown key' or 'unknown block type' error: the validator recognises it."""
    for key, spec in BLOCK_SPECS.items():
        assert spec.schema is not None
        family = spec.families[0]
        tree = {**empty_tree(family), "nodes": [spec.schema.template]}
        messages = [e.message for e in validate_tree(tree).errors]
        assert not any("Unknown" in m for m in messages), (key, messages)


# ---- the block catalogue ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("tier", ["org", "project"])
def test_the_block_catalogue_lists_every_type_with_its_form(world, tier):
    project = world.project()
    url = org_url(world, "/blocks") if tier == "org" else project_url(project, "/blocks")

    resp = world.client.get(url, headers=auth_headers(world.token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [b["type"] for b in body["blocks"]] == list(BLOCK_SPECS)
    assert all(b["described"] for b in body["blocks"])
    each = next(b for b in body["blocks"] if b["type"] == "each")
    assert each["provides"] == {"key": "as", "kind": "record", "default": "record"}
    assert [c["key"] for c in each["containers"]] == ["children"]
    assert [f["key"] for f in each["fields"]] == ["source", "as", "empty_text"]
    assert next(f for f in each["fields"] if f["key"] == "source")["required"] is True
    iff = next(b for b in body["blocks"] if b["type"] == "if")
    assert [c["key"] for c in iff["containers"]] == ["children", "else_children"]
    group = next(b for b in body["blocks"] if b["type"] == "group")
    assert next(f for f in group["fields"] if f["key"] == "by")["depends_on"] == "source"
    heading = next(b for b in body["blocks"] if b["type"] == "heading")
    level = next(f for f in heading["fields"] if f["key"] == "level")
    assert (level["minimum"], level["maximum"], level["default"]) == (1, 4, 1)
    sheet = next(b for b in body["blocks"] if b["type"] == "sheet")
    assert sheet["families"] == ["table"]
    assert body["field_kinds"] == list(FIELD_KINDS)
    assert {f["key"] for f in body["layout_fields"]} == {"orientation", "page_size", "margins", "mirror_margins", "page_styles", "variables"}
    section = next(b for b in body["blocks"] if b["type"] == "section")
    assert [f["key"] for f in section["fields"]] == ["page_style"] and [c["key"] for c in section["containers"]] == ["children"]
    image = next(b for b in body["blocks"] if b["type"] == "image")
    assert [f["key"] for f in image["fields"]] == [
        "file", "alt", "decorative", "width", "width_unit", "height", "height_unit", "align", "caption", "caption_position",
        "numbering",
    ]
    assert next(f for f in image["fields"] if f["key"] == "file")["kind"] == "image" and image["containers"] == []
    width = next(f for f in image["fields"] if f["key"] == "width")
    assert (width["kind"], width["minimum"], width["maximum"]) == ("number", 1.0, 1000.0)
    units = next(f for f in image["fields"] if f["key"] == "width_unit")
    assert units["choices"] == ["cm", "mm", "percent"]
    assert next(f for f in image["fields"] if f["key"] == "numbering")["choices"] == ["auto", "always", "never"]
    assert body["operators"]["enum"] == ["eq", "ne", "in", "not_in", "empty", "not_empty"]
    assert body["valueless_operators"] == ["empty", "not_empty"] and body["list_operators"] == ["in", "not_in"]
    assert body["schema_version"] == 1


def test_a_block_type_without_a_schema_is_offered_as_raw_json(monkeypatch):
    from app.services.report_layout_tree import BlockSpec

    monkeypatch.setitem(BLOCK_SPECS, "custom", BlockSpec("custom", ("document",), lambda v, n, p: None))

    entry = next(b for b in report_layout_designer.block_catalogue().blocks if b.key == "custom")

    assert entry.described is False
    assert entry.schema.template == {"type": "custom"} and entry.schema.fields == ()


def test_the_catalogue_needs_the_manage_permission(world):
    project = world.project()
    member = member_token(world)

    for url in (org_url(world, "/blocks"), project_url(project, "/blocks")):
        assert world.client.get(url, headers=auth_headers(member)).status_code in (403, 404), url
        assert world.client.get(url).status_code in (401, 403), url


# ---- the tree check ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tier", ["org", "project"])
def test_a_valid_tree_checks_out(world, tier):
    project = world.project()
    url = org_url(world, "/validate") if tier == "org" else project_url(project, "/validate")
    tree = {**empty_tree("document"), "nodes": [{"type": "heading", "text": "Hello", "level": 2}, {"type": "page_break"}]}

    resp = world.client.post(url, json={"tree": tree}, headers=auth_headers(world.token))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "errors": [], "node_count": 2}


@pytest.mark.parametrize("tier", ["org", "project"])
def test_every_problem_comes_back_with_the_path_of_its_block(world, tier):
    project = world.project()
    url = org_url(world, "/validate") if tier == "org" else project_url(project, "/validate")
    tree = {
        **empty_tree("document"),
        "nodes": [
            {"type": "heading", "text": "Fine"},
            {"type": "each", "source": {"record_type": REQ}, "children": [{"type": "heading", "level": 9, "text": "x"}]},
        ],
    }

    resp = world.client.post(url, json={"tree": tree}, headers=auth_headers(world.token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False and body["node_count"] == 3
    assert {"path": "nodes[1].children[0].level", "message": "Must be 1 to 4."} in body["errors"]


def test_a_tree_that_is_not_a_layout_is_reported_not_rejected(world):
    resp = world.client.post(org_url(world, "/validate"), json={"tree": {"nodes": 3}}, headers=auth_headers(world.token))

    assert resp.status_code == 200
    assert resp.json()["ok"] is False and resp.json()["errors"]


def test_checking_stores_audits_and_logs_nothing(world, caplog):
    project = world.project()
    tree = {**empty_tree("document"), "nodes": [{"type": "text", "text": SECRET}]}

    def counts() -> tuple[int, int]:
        with SessionLocal() as db:
            return (db.scalar(select(func.count()).select_from(AuditEvent)), db.scalar(select(func.count()).select_from(ReportLayout)))

    before = counts()
    with caplog.at_level(logging.DEBUG):
        for url in (org_url(world, "/validate"), project_url(project, "/validate")):
            assert world.client.post(url, json={"tree": tree}, headers=auth_headers(world.token)).status_code == 200

    assert counts() == before
    assert SECRET not in caplog.text


def test_checking_needs_the_manage_permission(world):
    project = world.project()
    member = member_token(world)
    body = {"tree": empty_tree("document")}

    for url in (org_url(world, "/validate"), project_url(project, "/validate")):
        assert world.client.post(url, json=body, headers=auth_headers(member)).status_code in (403, 404), url
        assert world.client.post(url, json=body).status_code in (401, 403), url
