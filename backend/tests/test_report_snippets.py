"""Tests for report snippets (`services.report_snippets`, `services.report_snippets_core`, the `.../snippets` routes): the
built-in set is valid and applies to an empty layout and to one that already has what it adds, a page style is reused or
renamed and never overwritten, the logo is sized for the page and obeys the picture-library tier rule, a parameter is
checked, the target is honoured, the layout's own problems are not the snippet's, nothing is stored, and the gates. Each
test builds its own organisation.
"""

from __future__ import annotations

import copy
import io
from typing import Any

import pytest
from PIL import Image as PilImage
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.report_layout import ReportLayoutVersion
from app.modules.registry import get_report_snippets
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import MAX_NODES, empty_tree, validate_tree
from app.services.report_snippets_core import CORE_REPORT_SNIPPETS
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World

EXPECTED_KEYS = ["cover-page", "logo-top-right", "document-control", "record-images", "landscape-table-section", "approvals"]


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Snippets Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def png(width: int = 200, height: int = 100) -> bytes:
    out = io.BytesIO()
    PilImage.new("RGB", (width, height), "red").save(out, "PNG")
    return out.getvalue()


def org_base(world: World) -> str:
    return f"/api/v1/orgs/{world.org['id']}/report-layouts"


def project_base(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}/report-layouts"


def upload(world: World, url: str, name: str = "logo.png", **size: int) -> str:
    resp = world.client.post(url, files={"file": (name, png(**size), "image/png")}, headers=auth_headers(world.token))
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def listing(world: World, base: str, token: str | None = None) -> list[dict]:
    resp = world.client.get(f"{base}/snippets", headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def apply(world: World, base: str, key: str, tree: dict, parameters: dict | None = None, *, token: str | None = None, **target: Any):
    body: dict[str, Any] = {"tree": tree, "parameters": parameters or {}}
    if target:
        body["target"] = target
    return world.client.post(f"{base}/snippets/{key}/apply", json=body, headers=auth_headers(token or world.token))


def values_for(world: World, base: str, key: str, image: str | None = None) -> dict[str, str]:
    """Values for every parameter of a snippet: the first record type offered, `image`, a text's default."""
    snippet = next(s for s in listing(world, base) if s["key"] == key)
    values: dict[str, str] = {}
    for parameter in snippet["parameters"]:
        if parameter["kind"] == "record_type":
            values[parameter["key"]] = parameter["choices"][0]["value"]
        elif parameter["kind"] == "image":
            assert image is not None
            values[parameter["key"]] = image
    return values


def doc(*nodes: dict, **root: Any) -> dict:
    return {**empty_tree("document"), **root, "nodes": list(nodes)}


def ok(resp) -> dict:
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"], body["errors"]
    return body


def refused(resp) -> list[tuple[str, str]]:
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert not body["ok"] and body["tree"] is None and body["changes"] == []
    return [(e["path"], e["message"]) for e in body["errors"]]


# ---- the built-in set --------------------------------------------------------------------------------------------


def test_the_built_in_set_is_the_documented_six_and_a_workbook_one_with_unique_keys_and_real_targets():
    keys = [snippet.key for snippet in CORE_REPORT_SNIPPETS]
    assert sorted(keys) == sorted([*EXPECTED_KEYS, "linked-sheets"])
    assert [s.key for _module, s in get_report_snippets()][: len(keys)] == keys
    for snippet in CORE_REPORT_SNIPPETS:
        assert snippet.name and snippet.description and snippet.category and snippet.formats
        for parameter in snippet.parameters:
            assert parameter.targets and parameter.help
            if parameter.kind in ("image", "record_type"):
                assert parameter.default is None, "a picture and a record type are never defaulted"


def test_the_list_gives_every_built_in_with_its_parameters_and_the_record_types_the_scope_can_use(world):
    snippets = {s["key"]: s for s in listing(world, org_base(world))}

    assert set(EXPECTED_KEYS) <= set(snippets)
    images = snippets["record-images"]["parameters"][0]
    assert images["kind"] == "record_type" and images["required"] and images["choices"]
    assert {c["value"] for c in images["choices"]} <= {c["value"] for c in snippets["landscape-table-section"]["parameters"][0]["choices"]}
    logo = {p["key"]: p for p in snippets["logo-top-right"]["parameters"]}
    assert logo["image"]["required"] and logo["alt"]["default"] == "Logo" and not logo["alt"]["required"]
    assert snippets["logo-top-right"]["formats"] == ["pdf", "docx", "odt"]


@pytest.mark.parametrize("key", EXPECTED_KEYS)
def test_each_snippet_applies_to_an_empty_layout_and_to_one_that_has_it_already(world, key):
    base = org_base(world)
    image = upload(world, f"{base[: -len('report-layouts')]}report-images")
    values = values_for(world, base, key, image)

    first = ok(apply(world, base, key, doc(), values))
    assert validate_tree(first["tree"], family="document").ok
    assert first["count"] >= 1 and first["inserted_at"] == "nodes[0]" and first["problems_elsewhere"] == 0
    # the text view and the stored tree agree
    text = format_tree(first["tree"])
    assert parse_text(text).tree == first["tree"]

    second = ok(apply(world, base, key, first["tree"], values))
    assert validate_tree(second["tree"], family="document").ok
    assert len(second["tree"]["nodes"]) == 2 * len(first["tree"]["nodes"])


def test_a_snippet_is_a_copy_nothing_in_the_result_refers_back_to_it(world):
    tree = ok(apply(world, org_base(world), "approvals", doc()))["tree"]

    assert all(set(node) <= {"type", "text", "level"} for node in tree["nodes"])


# ---- page styles: reuse, rename, never overwrite ----------------------------------------------------------------


def test_the_cover_page_adds_its_page_style_and_a_second_use_reuses_it(world):
    base = org_base(world)
    first = ok(apply(world, base, "cover-page", doc()))
    second = ok(apply(world, base, "cover-page", first["tree"]))

    assert [s["name"] for s in first["tree"]["page_styles"]] == ["Cover"]
    assert first["changes"] == ['Inserted 1 block at nodes[0].', 'Added page style "Cover".']
    assert [s["name"] for s in second["tree"]["page_styles"]] == ["Cover"]
    assert 'Used the layout\'s existing page style "Cover".' in second["changes"]
    assert [n["page_style"] for n in second["tree"]["nodes"]] == ["Cover", "Cover"]


def test_a_different_page_style_of_the_same_name_is_kept_and_the_inserted_section_follows_the_new_name(world):
    mine = {"name": "Landscape", "orientation": "portrait", "margins": {"top": 3}}
    tree = doc({"type": "heading", "text": "Mine"}, page_styles=[mine])
    base = org_base(world)

    body = ok(apply(world, base, "landscape-table-section", tree, values_for(world, base, "landscape-table-section")))

    assert body["tree"]["page_styles"][0] == mine
    assert body["tree"]["page_styles"][1]["name"] == "Landscape 2"
    assert body["tree"]["page_styles"][1]["orientation"] == "landscape"
    inserted = body["tree"]["nodes"][-1]
    assert inserted["page_style"] == "Landscape 2"
    assert any("Landscape 2" in change and 'different "Landscape"' in change for change in body["changes"])


def test_the_page_style_limit_refuses_the_insertion_with_a_reason(world):
    styles = [{"name": f"S{i}"} for i in range(10)]
    errors = refused(apply(world, org_base(world), "cover-page", doc(page_styles=styles)))

    assert errors and errors[0][0].startswith("page_styles")


def test_a_cover_page_cannot_go_inside_a_section(world):
    base = org_base(world)
    section = {"type": "section", "page_style": "Wide", "children": [{"type": "text", "text": "x"}]}
    tree = doc(section, page_styles=[{"name": "Wide", "orientation": "landscape"}])

    errors = refused(apply(world, base, "cover-page", tree, container="nodes[0].children"))

    assert any("cannot be inside another section" in message for _path, message in errors)


# ---- the logo ----------------------------------------------------------------------------------------------------


def test_the_logo_is_sized_and_placed_at_the_top_right_of_the_pages_text_edge(world):
    base = org_base(world)
    logo = upload(world, f"/api/v1/orgs/{world.org['id']}/report-images", width=200, height=100)

    block = ok(apply(world, base, "logo-top-right", doc(), {"image": logo}))["tree"]["nodes"][0]

    assert block["file"] == logo and block["placement"] == "front" and block["anchor"] == "page"
    # default margins are 1.5 cm: the box is 0.9 cm tall, so a 2:1 picture is 1.8 cm wide and ends at the right margin
    assert block["width"] == 1.8 and "height" not in block
    assert block["offset_x"] == pytest.approx(21.0 - 1.5 - 1.8) and block["offset_y"] == 0.5
    assert block["alt"] == "Logo"


def test_the_logo_follows_the_layouts_paper_and_margins(world):
    base = org_base(world)
    logo = upload(world, f"/api/v1/orgs/{world.org['id']}/report-images", width=400, height=100)
    tree = doc(page_size="A3", orientation="landscape", margins={"top": 3, "right": 2.5})

    block = ok(apply(world, base, "logo-top-right", tree, {"image": logo, "alt": "Acme"}))["tree"]["nodes"][0]

    assert block["alt"] == "Acme"
    assert block["width"] == 4.0  # a wide picture fills the 4 cm width of the box
    assert block["offset_x"] == pytest.approx(42.0 - 2.5 - 4.0)


def test_the_logo_needs_a_picture_and_never_gets_a_placeholder(world):
    errors = refused(apply(world, org_base(world), "logo-top-right", doc(), {}))

    assert errors == [("parameters.image", "Logo: choose one.")]


def test_an_organisation_layout_refuses_a_project_picture_naming_the_file(world):
    project = world.project("Pics")
    own = upload(world, f"/api/v1/projects/{project['id']}/report-images", "site-logo.png")

    errors = refused(apply(world, org_base(world), "logo-top-right", doc(), {"image": own}))
    assert errors[0][0] == "parameters.image" and "site-logo.png" in errors[0][1]

    # the project's own layout may use it
    body = ok(apply(world, project_base(project), "logo-top-right", doc(), {"image": own}))
    assert body["tree"]["nodes"][0]["file"] == own


def test_a_picture_that_is_not_an_id_or_does_not_exist_is_refused(world):
    base = org_base(world)

    assert refused(apply(world, base, "logo-top-right", doc(), {"image": "not-an-id"}))[0][0] == "parameters.image"
    assert "no longer exists" in refused(apply(world, base, "logo-top-right", doc(), {"image": "00000000-0000-0000-0000-000000000000"}))[0][1]


# ---- parameters --------------------------------------------------------------------------------------------------


def test_the_record_images_snippet_prints_the_chosen_types_attachments(world):
    base = org_base(world)
    choice = values_for(world, base, "record-images")["record_type"]

    each = ok(apply(world, base, "record-images", doc(), {"record_type": choice}))["tree"]["nodes"][0]

    assert each["type"] == "each" and each["source"]["record_type"] == choice
    assert [child["type"] for child in each["children"]] == ["heading", "record_images"]


def test_a_record_type_outside_the_scope_or_without_attachments_is_refused(world):
    base = org_base(world)

    errors = refused(apply(world, base, "record-images", doc(), {"record_type": "no_such_type"}))
    assert errors == [("parameters.record_type", "Not a kind of record this scope can use here.")]
    assert refused(apply(world, base, "record-images", doc(), {}))[0] == ("parameters.record_type", "Records: choose one.")


def test_text_parameters_use_their_default_and_are_length_checked(world):
    base = org_base(world)
    record_type = values_for(world, base, "landscape-table-section")["record_type"]

    default = ok(apply(world, base, "landscape-table-section", doc(), {"record_type": record_type}))
    custom = ok(apply(world, base, "landscape-table-section", doc(), {"record_type": record_type, "heading": "Open items"}))
    too_long = refused(apply(world, base, "landscape-table-section", doc(), {"record_type": record_type, "heading": "x" * 201}))

    assert default["tree"]["nodes"][0]["children"][0]["text"] == "Records"
    assert custom["tree"]["nodes"][0]["children"][0]["text"] == "Open items"
    assert too_long[0][0] == "parameters.heading"


def test_an_unknown_parameter_is_refused(world):
    errors = refused(apply(world, org_base(world), "approvals", doc(), {"colour": "red"}))

    assert errors == [("parameters.colour", "This snippet has no such parameter.")]


# ---- the target --------------------------------------------------------------------------------------------------


def test_the_blocks_go_at_the_index_in_the_chosen_list(world):
    base = org_base(world)
    container = {"type": "if", "when": {"module": "x"}, "children": [{"type": "text", "text": "in"}]}
    tree = doc({"type": "heading", "text": "A"}, container, {"type": "heading", "text": "B"})

    start = ok(apply(world, base, "approvals", tree, index=0))
    middle = ok(apply(world, base, "approvals", tree, index=1))
    end = ok(apply(world, base, "approvals", tree))
    inside = ok(apply(world, base, "approvals", tree, container="nodes[1].children", index=0))

    assert start["tree"]["nodes"][0]["text"] == "Approvals" and start["inserted_at"] == "nodes[0]"
    assert middle["tree"]["nodes"][0]["text"] == "A" and middle["tree"]["nodes"][1]["text"] == "Approvals"
    assert end["tree"]["nodes"][2]["text"] == "B" and end["inserted_at"] == "nodes[3]"
    assert inside["inserted_at"] == "nodes[1].children[0]" and inside["tree"]["nodes"][1]["children"][0]["text"] == "Approvals"
    assert tree["nodes"][0]["text"] == "A" and len(tree["nodes"]) == 3, "the given tree is not changed"


@pytest.mark.parametrize(
    "target",
    [{"container": "pages"}, {"container": "nodes[9].children"}, {"container": "nodes[0].text"}, {"container": "nodes.children"}, {"index": 5}],
)
def test_a_target_that_is_not_a_list_of_blocks_or_a_position_in_it_is_refused(world, target):
    errors = refused(apply(world, org_base(world), "approvals", doc({"type": "heading", "text": "A"}), **target))

    assert errors[0][0] == "target"


def test_a_snippet_for_the_other_layout_family_is_refused(world):
    errors = refused(apply(world, org_base(world), "approvals", empty_tree("table")))

    assert errors[0][0] == "" and "document layout" in errors[0][1]


# ---- the layout's own problems ----------------------------------------------------------------------------------


def test_a_draft_with_other_problems_still_takes_a_snippet_and_says_how_many_remain(world):
    broken = {"type": "no_such_block"}
    tree = doc(broken, {"type": "heading", "text": "fine"})
    assert not validate_tree(tree).ok

    body = ok(apply(world, org_base(world), "approvals", tree, index=1))

    assert body["problems_elsewhere"] >= 1
    assert body["tree"]["nodes"][1]["text"] == "Approvals" and body["tree"]["nodes"][0] == broken


def test_a_snippet_that_would_take_the_layout_past_the_block_limit_is_refused(world):
    tree = doc(*[{"type": "text", "text": "x"} for _ in range(MAX_NODES - 1)])
    assert validate_tree(tree).ok

    errors = refused(apply(world, org_base(world), "approvals", tree))

    assert errors and "too" in errors[0][1]


# ---- nothing is stored, and the gates ---------------------------------------------------------------------------


def test_applying_stores_and_audits_nothing(world, db):
    base = org_base(world)
    versions = db.scalar(select(func.count()).select_from(ReportLayoutVersion))
    events = db.scalar(select(func.count()).select_from(AuditEvent))

    ok(apply(world, base, "cover-page", doc()))
    listing(world, base)

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ReportLayoutVersion)) == versions
    assert db.scalar(select(func.count()).select_from(AuditEvent)) == events


def test_an_unknown_snippet_is_404_and_a_member_without_the_manage_permission_is_refused(world):
    base = org_base(world)
    email = "plain-snippets@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    member = login(world.client, email, "Password123!")

    assert apply(world, base, "no-such-snippet", doc()).status_code == 404
    assert world.client.get(f"{base}/snippets", headers=auth_headers(member)).status_code == 403
    assert apply(world, base, "approvals", doc(), token=member).status_code == 403
    assert world.client.post(f"{base}/snippets/approvals/apply", json={"tree": doc()}).status_code in (401, 403)


def test_a_project_scope_lists_and_applies_the_same_snippets(world):
    project = world.project("Scope")
    base = project_base(project)

    assert set(EXPECTED_KEYS) <= {s["key"] for s in listing(world, base)}
    body = ok(apply(world, base, "document-control", doc()))
    assert body["tree"]["nodes"][0]["text"] == "Document control"
    assert world.client.post(
        f"{base}/snippets/approvals/apply", json={"tree": copy.deepcopy(doc())}, headers=auth_headers(world.token),
    ).status_code == 200


# ---- the result is a real layout ---------------------------------------------------------------------------------


def test_all_the_snippets_together_save_as_a_layout_and_preview(world):
    project = world.project("Whole")
    base = project_base(project)
    logo = upload(world, f"/api/v1/projects/{project['id']}/report-images")
    tree = doc()
    for key in ["cover-page", "document-control", "record-images", "landscape-table-section", "approvals", "logo-top-right"]:
        tree = ok(apply(world, base, key, tree, values_for(world, base, key, logo), index=0 if key == "logo-top-right" else None))["tree"]

    created = world.client.post(
        base, json={"name": "From snippets", "family": "document", "tree": tree}, headers=auth_headers(world.token),
    )
    assert created.status_code == 201, created.text
    preview = world.client.post(f"{base}/preview", json={"tree": tree}, headers=auth_headers(world.token))
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["ok"], body
    assert "Document control" in body["html"] and "Approvals" in body["html"]
    assert "__" in body["html"], "the fill-in lines print as underscores, not as emphasis"


# ---- the table snippet --------------------------------------------------------------------------------------------


def test_two_linked_sheets_fills_both_sheets_and_the_link_follows_the_first_sheets_name(world):
    base = org_base(world)
    snippet = next(s for s in listing(world, base) if s["key"] == "linked-sheets")
    assert snippet["family"] == "table" and snippet["formats"] == ["xlsx", "ods", "csv"]
    kinds = {c["value"] for c in snippet["parameters"][0]["choices"]}
    values = {"first_type": "requirement", "second_type": "change_request", "first_name": "Needs", "second_name": "Changes"}
    assert {"requirement", "change_request"} <= kinds

    body = ok(apply(world, base, "linked-sheets", empty_tree("table"), values))

    first, second = body["tree"]["nodes"]
    assert (first["name"], first["source"]["record_type"]) == ("Needs", "requirement")
    join_type = second["joins"][0]["source"]["record_type"]
    assert (second["name"], second["source"]["record_type"], join_type) == ("Changes", "change_request", "requirement")
    assert second["columns"][3]["link"] == {"sheet": "Needs"}
    assert validate_tree(body["tree"], family="table").ok
    assert parse_text(format_tree(body["tree"])).tree == body["tree"]


def test_two_linked_sheets_is_refused_for_a_document_layout(world):
    errors = refused(apply(world, org_base(world), "linked-sheets", doc(), {"first_type": "requirement", "second_type": "change_request"}))

    assert errors and "table layout" in errors[0][1]
