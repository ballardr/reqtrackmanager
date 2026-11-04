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
from app.services.report_layout_block_schema import (
    FIELD_KINDS,
    LAYOUT_FIELDS,
    BlockField,
    BlockGroup,
    BlockSchema,
    arrangement_problems,
)
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


def test_every_core_block_arranges_its_form_soundly():
    for key, spec in BLOCK_SPECS.items():
        assert spec.schema is not None
        assert arrangement_problems(spec.schema) == [], key


#: The most fields a block's form may have and stay flat; a longer form must be arranged in groups.
MOST_FIELDS_IN_A_FLAT_FORM = 5


def test_a_long_block_form_is_arranged_in_groups():
    """A block type with more than a few fields declares groups, so the next block ships arranged."""
    flat_and_long = {
        key: len(spec.schema.fields) for key, spec in BLOCK_SPECS.items()
        if len(spec.schema.fields) > MOST_FIELDS_IN_A_FLAT_FORM and not spec.schema.groups
    }
    assert flat_and_long == {}


def test_a_block_form_with_no_basic_part_opens_its_first_group():
    """With nothing always visible a form of closed bars would show nothing, so one group starts open."""
    for key, spec in BLOCK_SPECS.items():
        if spec.schema.groups and not any(f.basic or not f.group for f in spec.schema.fields):
            assert any(g.open for g in spec.schema.groups), key


def test_the_picture_blocks_arrange_their_size_position_and_caption():
    groups = {key: {g.key for g in BLOCK_SPECS[key].schema.groups} for key in ("image", "shape", "record_images")}
    assert groups == {
        "image": {"size", "position", "caption"},
        "shape": {"outline", "size", "position", "svg"},
        "record_images": {"which", "caption", "size", "position"},
    }
    for key in ("image", "shape", "record_images"):
        by_key = {f.key: f for f in BLOCK_SPECS[key].schema.fields}
        for unit in ("width_unit", "height_unit"):
            assert by_key[unit].group == "size", (key, unit)
            assert by_key[unit].inline, (key, unit)
        assert by_key["align"].control == "choice-buttons", key


def test_the_heading_and_text_words_declare_the_marks_the_form_offers_buttons_for():
    """The Bold and Italic buttons appear on exactly the texts that read ** and * marks."""
    heading = {f.key: f for f in BLOCK_SPECS["heading"].schema.fields}
    text = {f.key: f for f in BLOCK_SPECS["text"].schema.fields}
    assert "marks" in heading["text"].features
    assert "markdown" in text["text"].features
    for key in ("level", "font", "size", "colour"):
        assert "marks" not in heading[key].features


def _schema(*fields: BlockField, groups: tuple[BlockGroup, ...] = ()) -> BlockSchema:
    return BlockSchema("X", "x", fields, groups=groups)


def test_a_field_naming_an_undeclared_group_is_a_problem():
    problems = arrangement_problems(_schema(BlockField("a", "A", "text", help="h", group="ghost")))
    assert problems == ["field 'a' names group 'ghost', which the schema does not declare"]


def test_a_basic_field_inside_a_group_and_an_empty_group_are_problems():
    schema = _schema(
        BlockField("a", "A", "text", group="g", basic=True), groups=(BlockGroup("g", "G"), BlockGroup("unused", "U")),
    )
    assert arrangement_problems(schema) == ["field 'a' is basic but sits in group 'g'", "group 'unused' holds no field"]


def test_in_an_arranged_form_every_field_is_in_a_group_or_basic():
    schema = _schema(BlockField("a", "A", "text"), BlockField("b", "B", "text", group="g"), groups=(BlockGroup("g", "G"),))
    assert arrangement_problems(schema) == ["field 'a' is neither in a group nor marked basic"]
    assert arrangement_problems(_schema(BlockField("a", "A", "text"))) == []


def test_a_required_field_cannot_hide_in_a_group_that_starts_closed():
    schema = _schema(
        BlockField("a", "A", "text", group="shut", required=True), BlockField("b", "B", "text", group="ajar", required=True),
        BlockField("c", "C", "text", group="shut"), groups=(BlockGroup("shut", "S"), BlockGroup("ajar", "A", open=True)),
    )
    assert arrangement_problems(schema) == ["field 'a' is required but sits in group 'shut', which starts closed"]


def test_an_inline_field_must_follow_a_field_of_its_own_group():
    schema = _schema(
        BlockField("a", "A", "text", group="g"), BlockField("b", "B", "text", group="g", inline=True),
        BlockField("c", "C", "text", group="h", inline=True), BlockField("d", "D", "text", group="h", inline=True),
        groups=(BlockGroup("g", "G"), BlockGroup("h", "H")),
    )
    assert arrangement_problems(schema) == [
        "field 'c' is inline but does not follow a field of its own group",
        "field 'd' is inline but does not follow a field of its own group",
    ]
    assert arrangement_problems(_schema(BlockField("a", "A", "text", inline=True))) == [
        "field 'a' is inline but does not follow a field of its own group",
    ]


def test_a_duplicate_group_key_is_a_problem():
    schema = _schema(BlockField("a", "A", "text", group="g"), groups=(BlockGroup("g", "G"), BlockGroup("g", "Again")))
    assert arrangement_problems(schema) == ["group 'g' is declared twice"]


def test_a_control_must_suit_the_kind_and_the_number_of_values():
    five = tuple("abcde")
    schema = _schema(
        BlockField("t", "T", "text", control="toggle"),
        BlockField("c", "C", "choice", choices=five, control="choice-buttons"),
        BlockField("i", "I", "integer", minimum=1, maximum=4, control="choice-buttons"),
        BlockField("n", "N", "integer", control="choice-buttons"),
        BlockField("z", "Z", "boolean", control="slider"),
    )
    assert arrangement_problems(schema) == [
        "field 't' is a toggle but its kind is 'text', not boolean",
        "field 'c' has choice-buttons for 5 values (2 to 4 fit)",
        "field 'n' has choice-buttons but its kind is 'integer'",
        "field 'z' has unknown control 'slider'",
    ]


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
    assert [f["key"] for f in each["fields"]] == ["source", "as", "empty_text", "label"]
    assert next(f for f in each["fields"] if f["key"] == "source")["required"] is True
    iff = next(b for b in body["blocks"] if b["type"] == "if")
    assert [c["key"] for c in iff["containers"]] == ["children", "else_children"]
    group = next(b for b in body["blocks"] if b["type"] == "group")
    assert next(f for f in group["fields"] if f["key"] == "by")["depends_on"] == "source"
    heading = next(b for b in body["blocks"] if b["type"] == "heading")
    level = next(f for f in heading["fields"] if f["key"] == "level")
    assert (level["minimum"], level["maximum"], level["default"]) == (1, 4, 1)
    assert level["control"] == "choice-buttons" and heading["groups"] == []
    grid = next(b for b in body["blocks"] if b["type"] == "grid")
    assert [(g["key"], g["label"], g["open"]) for g in grid["groups"]] == [
        ("borders", "Borders", False), ("cell_style", "Cell style", False), ("look", "Look", False),
    ]
    assert {f["key"]: f["group"] for f in grid["fields"]} == {
        "columns": "", "rows": "", "header_rows": "", "label": "", "borders": "borders", "border_color": "borders", "align": "cell_style",
        "valign": "cell_style", "fill": "cell_style", "color": "cell_style", "bold": "cell_style", "font": "look", "size": "look",
    }
    assert {f["key"]: f["control"] for f in grid["fields"] if f["control"]} == {
        "align": "choice-buttons", "valign": "choice-buttons", "bold": "toggle",
    }
    sheet = next(b for b in body["blocks"] if b["type"] == "sheet")
    assert sheet["families"] == ["table"]
    image = next(b for b in body["blocks"] if b["type"] == "image")
    assert {f["key"]: f["empty_label"] for f in image["fields"] if f["key"] in ("width", "height", "alt")} == {
        "width": "Auto", "height": "Auto", "alt": "",
    }
    assert body["field_kinds"] == list(FIELD_KINDS)
    assert {f["key"] for f in body["layout_fields"]} == {
        "orientation", "page_size", "margins", "mirror_margins", "repeat_table_header", "align_tables", "page_styles", "header",
        "footer", "variables", "file_name", "contents_sheet", "run_scope", "palette", "styles", "embed_fonts", "table_header_fill",
            "table_header_text",
    }
    contents = next(f for f in body["layout_fields"] if f["key"] == "contents_sheet")
    assert (contents["kind"], contents["families"]) == ("boolean", ["table"])
    repeat = next(f for f in body["layout_fields"] if f["key"] == "repeat_table_header")
    assert (repeat["kind"], repeat["default"]) == ("boolean", True)
    assert [f["key"] for f in body["image_column_fields"]] == [
        "names", "types", "max_count", "order", "max_size_mb", "width", "width_unit", "height", "height_unit", "arrange",
    ]
    assert next(f for f in body["image_column_fields"] if f["key"] == "width_unit")["default"] == "percent"
    section = next(b for b in body["blocks"] if b["type"] == "section")
    assert [f["key"] for f in section["fields"]] == ["page_style", "label"] and [c["key"] for c in section["containers"]] == ["children"]
    image = next(b for b in body["blocks"] if b["type"] == "image")
    assert [f["key"] for f in image["fields"]] == [
        "file", "alt", "decorative", "width", "width_unit", "height", "height_unit", "align", "placement", "anchor", "offset_x",
        "offset_y", "caption", "caption_position", "numbering", "label",
    ]
    placement = next(f for f in image["fields"] if f["key"] == "placement")
    assert placement["choices"] == ["inline", "wrap", "behind", "front"] and placement["default"] == "inline"
    assert next(f for f in image["fields"] if f["key"] == "anchor")["choices"] == ["paragraph", "margin", "page"]
    assert all(f["help"] for f in image["fields"] if f["key"] in ("placement", "anchor", "offset_x", "offset_y"))
    assert next(f for f in image["fields"] if f["key"] == "file")["kind"] == "image" and image["containers"] == []
    width = next(f for f in image["fields"] if f["key"] == "width")
    assert (width["kind"], width["minimum"], width["maximum"]) == ("number", 1.0, 1000.0)
    units = next(f for f in image["fields"] if f["key"] == "width_unit")
    assert units["choices"] == ["cm", "mm", "percent"]
    assert next(f for f in image["fields"] if f["key"] == "numbering")["choices"] == ["auto", "always", "never"]
    assert body["operators"]["enum"] == ["eq", "ne", "in", "not_in", "empty", "not_empty"]
    assert body["valueless_operators"] == ["empty", "not_empty"] and body["list_operators"] == ["in", "not_in"]
    assert body["schema_version"] == 1


@pytest.mark.parametrize("tier", ["org", "project"])
def test_every_described_block_offers_a_label_and_a_longer_name(world, tier):
    project = world.project()
    url = org_url(world, "/blocks") if tier == "org" else project_url(project, "/blocks")

    body = world.client.get(url, headers=auth_headers(world.token)).json()

    for block in body["blocks"]:
        label = [f for f in block["fields"] if f["key"] == "label"]
        assert len(label) == 1 and block["fields"][-1]["key"] == "label", block["type"]
        assert (label[0]["kind"], label[0]["max_length"], label[0]["required"]) == ("text", 128, False)
        assert "never printed" in label[0]["help"]
    names = [f for b in body["blocks"] for f in b["fields"] if f["kind"] == "alias"]
    assert names and all(f["max_length"] == 128 for f in names)


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
    assert resp.json() == {"ok": True, "errors": [], "node_count": 2, "warnings": []}


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
