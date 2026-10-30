"""Tests for a table's image column (the pictures attached to each row's record) and the layout-wide header-row switch.

Covers the tree check, the text view round trip, the shared sizing rule (a share of the column, no size caps of our own, only the
physical page limit), a run over Pain Points with pictures in every document format, the text fallback in a sheet, the one-batch
file query, the confidential mark and the header switch in every format.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from typing import Any

import pytest
from PIL import Image as PilImage
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.services.report_image_layout import CELL_PADDING_CM, place_cell_pictures
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import InvalidLayoutError, assert_valid, empty_tree
from app.services.report_model import Image, ImageCell
from tests.conftest import auth_headers
from tests.link_world import World


def png(colour: Any = "red", size: tuple[int, int] = (200, 100)) -> bytes:
    out = io.BytesIO()
    PilImage.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


def table_tree(images: dict[str, Any] | None = None, *, label: str | None = None, **root: Any) -> dict[str, Any]:
    """A document with a Pain Points table: id, title and an image column."""
    column: dict[str, Any] = {"images": images if images is not None else {}}
    if label is not None:
        column["label"] = label
    return {
        **empty_tree("document"), **root,
        "nodes": [{"type": "table", "source": {"record_type": "pain_point"}, "columns": [{"field": "code"}, {"field": "title"}, column]}],
    }


def sheet_tree(images: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        **empty_tree("table"),
        "nodes": [{
            "type": "sheet", "name": "Pain points", "source": {"record_type": "pain_point"},
            "columns": [{"field": "code"}, {"images": images if images is not None else {"max_count": 2}, "label": "Files"}],
        }],
    }


def pdf_pages(data: bytes) -> int:
    """The number of pages of a PDF (the page objects, which ReportLab writes uncompressed)."""
    return len(re.findall(rb"/Type /Page\b", data))


def pdf_images(data: bytes) -> int:
    """The number of distinct picture objects in a PDF (ReportLab writes one per distinct picture, however often it is drawn)."""
    return data.count(b"/Subtype /Image")


def errors_of(tree: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(InvalidLayoutError) as caught:
        assert_valid(tree)
    return [(e.path, e.message) for e in caught.value.errors]


# ---- the tree ---------------------------------------------------------------------------------------------------


def test_an_image_column_with_every_setting_is_valid_in_a_table_and_a_sheet():
    rules = {
        "names": ["{{row.code}}-*", "site-*"], "types": ["png", "JPG"], "max_count": 3, "order": "uploaded", "max_size_mb": 2.5,
        "width": 8, "width_unit": "cm", "height": 4, "height_unit": "cm", "arrange": "side_by_side",
    }
    assert_valid(table_tree(rules, label="Photos"))
    assert_valid(table_tree())
    assert_valid(table_tree({"width": 50, "width_unit": "percent", "arrange": "stacked"}))
    assert_valid(sheet_tree(rules))


@pytest.mark.parametrize(
    ("rules", "path"),
    [
        ({"names": "site-*"}, "names"),
        ({"names": ["{{row.nothing}}-*"]}, "names[0]"),
        ({"names": ["{{pp.code}}"]}, "names[0]"),
        ({"types": ["exe"]}, "types[0]"),
        ({"max_count": 0}, "max_count"),
        ({"max_count": 21}, "max_count"),
        ({"order": "random"}, "order"),
        ({"max_size_mb": 51}, "max_size_mb"),
        ({"width": 500}, "width"),
        ({"width": 0}, "width"),
        ({"width_unit": "cm"}, "width_unit"),
        ({"height": 5, "height_unit": "percent"}, "height_unit"),
        ({"arrange": "grid"}, "arrange"),
        ({"caption": "x"}, "caption"),
    ],
)
def test_a_bad_image_column_setting_names_its_path(rules, path):
    found = errors_of(table_tree(rules))
    assert any(p == f"nodes[0].columns[2].images.{path}" for p, _ in found), found


def test_an_image_column_needs_a_record_type_whose_attachments_can_be_printed():
    tree = table_tree()
    tree["nodes"][0]["source"] = {"record_type": "stakeholder"}
    tree["nodes"][0]["columns"] = [{"images": {}}]
    path, message = errors_of(tree)[0]
    assert path == "nodes[0].columns[0].images" and "identifiable person" in message


def test_a_column_is_a_field_or_images_not_both_and_images_must_be_an_object():
    tree = table_tree()
    tree["nodes"][0]["columns"] = [{"field": "code", "images": {}}]
    assert any("Unknown key" in m for _, m in errors_of(tree))
    tree["nodes"][0]["columns"] = [{"images": []}]
    assert any(p == "nodes[0].columns[0].images" and "object" in m for p, m in errors_of(tree))


def test_a_sheet_image_column_may_read_a_joined_record_and_rejects_an_unknown_name():
    tree = sheet_tree()
    tree["nodes"][0]["columns"][1]["from"] = "ghost"
    assert any(p.endswith(".from") for p, _ in errors_of(tree))


def test_the_header_switch_is_a_document_boolean():
    assert_valid(table_tree(repeat_table_header=False))
    assert_valid(table_tree(repeat_table_header=True))
    assert errors_of(table_tree(repeat_table_header="no"))[0][0] == "repeat_table_header"
    table = {**empty_tree("table"), "repeat_table_header": False}
    assert errors_of(table)[0][0] == "repeat_table_header"


# ---- the text view ----------------------------------------------------------------------------------------------


def test_the_text_view_round_trips_an_image_column_and_the_switch():
    rules = {
        "names": ["site-*", "{{row.code}}*"], "types": ["png", "jpg"], "max_count": 3, "order": "uploaded", "max_size_mb": 2,
        "width": 90, "width_unit": "percent", "height": 5, "height_unit": "cm", "arrange": "side_by_side",
    }
    tree = table_tree(rules, label="Photos", repeat_table_header=False)
    text = format_tree(tree)
    assert text.startswith("@layout document portrait norepeatheader")
    assert '@images names "site-*", "{{row.code}}*" types png, jpg max_count 3 order uploaded max_size_mb 2 width 90 percent' in text
    assert 'arrange side_by_side label "Photos"' in text
    assert parse_text(text).tree == tree
    plain = table_tree()
    assert parse_text(format_tree(plain)).tree == plain
    explicit = table_tree(repeat_table_header=True)
    assert "repeatheader" in format_tree(explicit).splitlines()[0] and parse_text(format_tree(explicit)).tree == explicit
    sheet = sheet_tree({"max_count": 2})
    assert parse_text(format_tree(sheet)).tree == sheet


def test_the_text_parser_reports_a_bad_images_line_at_its_line():
    text = "@layout document\n\n@table pain_point\n  @column code\n  @images width\n@end\n"
    result = parse_text(text)
    assert result.tree is None and result.errors[0].line == 5
    twice = parse_text("@layout document\n\n@table pain_point\n  @images width 10 percent width 20 percent\n@end\n")
    assert twice.tree is None and "written once" in twice.errors[0].message
    joined = parse_text("@layout document\n\n@table pain_point\n  @images from other\n@end\n")
    assert joined.tree is None and "joined name" in joined.errors[0].message


# ---- the sizing rule --------------------------------------------------------------------------------------------


def cell(count: int, arrange: str = "stacked") -> ImageCell:
    """A cell of `count` pictures, each 90 % of the column wide."""
    return ImageCell([Image(data=png(), width=90, width_unit="percent") for _ in range(count)], arrange)


def test_a_percent_width_is_a_share_of_the_column_less_its_padding():
    placed = place_cell_pictures(cell(1), 10.0, None)
    inner = 10.0 - 2 * CELL_PADDING_CM
    assert placed[0].width_cm == pytest.approx(inner * 0.9)
    assert placed[0].height_cm == pytest.approx(inner * 0.9 / 2)  # a 2:1 picture keeps its shape


def test_the_same_percent_scales_with_the_column_so_a_page_size_change_needs_no_edit():
    narrow, wide = place_cell_pictures(cell(1), 6.0, None)[0], place_cell_pictures(cell(1), 18.0, None)[0]
    assert wide.width_cm / narrow.width_cm == pytest.approx((18 - 0.4) / (6 - 0.4))


def test_no_size_cap_is_applied_below_the_physical_page_limit():
    tall = ImageCell([Image(data=png(size=(100, 400)), width=100, width_unit="percent")])
    placed = place_cell_pictures(tall, 20.0, None)
    assert placed[0].height_cm == pytest.approx(19.6 * 4)  # 78 cm tall: the author asked for the full column
    clamped = place_cell_pictures(tall, 20.0, 20.0)
    assert clamped[0].height_cm == pytest.approx(20.0)  # only a page that could never hold it shrinks it, keeping the shape
    assert clamped[0].width_cm == pytest.approx(5.0)


def test_stacked_pictures_take_a_line_each_and_side_by_side_ones_wrap():
    assert [p.line for p in place_cell_pictures(cell(3), 10.0, None)] == [0, 1, 2]
    side = ImageCell([Image(data=png(), width=3, width_unit="cm") for _ in range(5)], "side_by_side")
    assert [p.line for p in place_cell_pictures(side, 10.0, None)] == [0, 0, 0, 1, 1]  # three 3 cm pictures fit 9.6 cm


def test_a_picture_that_cannot_be_read_is_left_out():
    broken = ImageCell([Image(data=b"not an image", width=90, width_unit="percent"), Image(data=png(), width=90, width_unit="percent")])
    assert len(place_cell_pictures(broken, 10.0, None)) == 1


# ---- a run ------------------------------------------------------------------------------------------------------


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Image Columns Org", context_strategy=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def attach(world: World, project: dict, pain_point: uuid.UUID, name: str, data: bytes) -> dict:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/modules/context_strategy/pain-points/{pain_point}/files",
        files={"file": (name, data, "application/octet-stream")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def preview(world: World, project: dict, tree: dict) -> dict:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts/preview", json={"tree": tree}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def two_pain_points(world: World) -> tuple[dict, uuid.UUID, uuid.UUID]:
    project = world.project("Alpha")
    first = world.pain_point(project, "First")
    second = world.pain_point(project, "Second")
    attach(world, project, first, "site-2.png", png("green"))
    attach(world, project, first, "site-1.png", png("red"))
    attach(world, project, first, "notes.txt", b"not a picture")
    attach(world, project, second, "other.png", png("blue"))
    return project, first, second


def test_the_cells_hold_each_rows_own_matching_pictures_in_the_html(world):
    project, _, _ = two_pain_points(world)
    result = preview(world, project, table_tree({"names": ["site-*"]}))
    rows = re.findall(r"<tr>(.*?)</tr>", result["html"], flags=re.S)[1:]
    assert len(rows) == 2
    counts = sorted(row.count("<img") for row in rows)
    assert counts == [0, 2]  # the second Pain Point has no file matching site-*
    assert 'width:90%' in result["html"] and 'class="cell-images stacked"' in result["html"]


def test_the_default_size_is_ninety_percent_and_a_chosen_size_replaces_it(world):
    project, _, _ = two_pain_points(world)
    assert "width:90%" in preview(world, project, table_tree())["html"]
    chosen = preview(world, project, table_tree({"width": 4, "width_unit": "cm"}))["html"]
    assert "width:4cm" in chosen and "width:90%" not in chosen
    by_height = preview(world, project, table_tree({"height": 2, "height_unit": "cm"}))["html"]
    assert "height:2cm" in by_height and "width:90%" not in by_height


def test_the_arrangement_is_per_column_and_the_count_applies_to_real_pictures(world):
    project, _, _ = two_pain_points(world)
    side = preview(world, project, table_tree({"arrange": "side_by_side", "max_count": 2}))["html"]
    assert 'class="cell-images side"' in side and side.count("<img") == 3  # two for the first, one for the second
    one = preview(world, project, table_tree({"max_count": 1}))["html"]
    assert one.count("<img") == 2


def test_a_row_name_pattern_reads_the_rows_own_record(world):
    project = world.project("Alpha")
    first = world.pain_point(project, "First")
    second = world.pain_point(project, "Second")
    code = {"first": None, "second": None}
    pain = world.client.get(f"/api/v1/projects/{project['id']}/modules/context_strategy/pain-points", headers=auth_headers(world.token)).json()
    pain = pain["items"] if isinstance(pain, dict) else pain
    for item in pain:
        code["first" if item["id"] == str(first) else "second"] = item["unique_code"]
    attach(world, project, first, f"{code['first']}-photo.png", png("red"))
    attach(world, project, second, f"{code['second']}-photo.png", png("blue"))
    attach(world, project, second, f"{code['first']}-stray.png", png("green"))
    result = preview(world, project, table_tree({"names": ["{{row.code}}-*"]}))
    # Each row shows only the picture named for its own code; the file named for the first code but attached to the second
    # Pain Point matches nothing in the second row.
    assert result["html"].count("<img") == 2


def test_a_confidential_file_is_never_drawn(world):
    project, first, _ = two_pain_points(world)
    secret = attach(world, project, first, "site-secret.png", png("black"))
    marked = world.client.patch(f"/api/v1/files/{secret['id']}/confidential", json={"confidential": True}, headers=auth_headers(world.token))
    assert marked.status_code == 200, marked.text
    assert preview(world, project, table_tree({"names": ["site-*"]}))["html"].count("<img") == 2


def test_the_files_of_all_rows_are_read_in_one_query(world):
    project, _, _ = two_pain_points(world)
    queries: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):
        if "FROM" in statement and "files" in statement.lower() and "confidential" in statement.lower():
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        preview(world, project, table_tree())
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(queries) == 1


def test_a_table_over_a_type_with_no_attachments_is_refused_at_save(world):
    project = world.project("Alpha")
    tree = table_tree()
    tree["nodes"][0]["source"] = {"record_type": "stakeholder"}
    tree["nodes"][0]["columns"] = [{"images": {}}]
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts",
        json={"name": "Bad", "description": "", "family": "document", "tree": tree}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 422 and "identifiable person" in resp.text


def test_a_sheet_lists_the_file_names_instead_of_drawing_pictures(world):
    project, _, _ = two_pain_points(world)
    result = preview(world, project, sheet_tree({"names": ["site-*"], "max_count": 2}))
    rows = result["sheets"][0]["rows"]
    assert result["sheets"][0]["columns"] == ["Code", "Files"]
    assert sorted(row[1] for row in rows) == ["", "site-1.png, site-2.png"]


# ---- every format -----------------------------------------------------------------------------------------------


def created_layout(world: World, project: dict, tree: dict) -> dict:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts",
        json={"name": f"L {uuid.uuid4().hex[:6]}", "description": "d", "family": tree["family"], "tree": tree}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def run(world: World, project: dict, layout: dict, fmt: str) -> bytes:
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": fmt}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, (fmt, resp.text)
    return resp.content


def test_every_document_format_draws_the_cell_pictures(world):
    project, _, _ = two_pain_points(world)
    layout = created_layout(world, project, table_tree({"names": ["site-*"], "arrange": "side_by_side"}))
    assert pdf_images(run(world, project, layout, "pdf")) == 2
    docx = zipfile.ZipFile(io.BytesIO(run(world, project, layout, "docx")))
    assert len([n for n in docx.namelist() if n.startswith("word/media/")]) >= 1
    assert docx.read("word/document.xml").count(b"<w:drawing>") == 2
    odt = zipfile.ZipFile(io.BytesIO(run(world, project, layout, "odt")))
    assert len([n for n in odt.namelist() if n.startswith("Pictures/")]) >= 1
    assert odt.read("content.xml").count(b"<draw:frame") == 2
    html = run(world, project, layout, "html").decode()
    assert html.count("<img") == 2


def test_a_long_table_of_pictures_runs_over_several_pages_and_keeps_every_picture(world):
    project = world.project("Alpha")
    for n in range(14):
        point = world.pain_point(project, f"Row {n}")
        attach(world, project, point, "a.png", png((n * 16, 255 - n * 16, 40), (300, 300)))
        attach(world, project, point, "b.png", png((40, n * 16, 255 - n * 16), (300, 300)))
    layout = created_layout(world, project, table_tree({"width": 70, "width_unit": "percent"}))
    data = run(world, project, layout, "pdf")
    assert pdf_pages(data) > 1
    assert pdf_images(data) == 28


def test_a_picture_taller_than_a_page_is_shrunk_to_it_in_pdf_instead_of_failing(world):
    project = world.project("Alpha")
    point = world.pain_point(project, "Tall")
    attach(world, project, point, "tall.png", png("red", (100, 900)))
    layout = created_layout(world, project, table_tree({"width": 100, "width_unit": "percent"}))
    assert pdf_images(run(world, project, layout, "pdf")) == 1


# ---- the header switch ------------------------------------------------------------------------------------------


def long_table_layout(world: World, **root: Any) -> tuple[dict, dict]:
    project = world.project("Alpha")
    for n in range(70):
        world.pain_point(project, f"Row {n}")
    tree = table_tree(**root)
    tree["nodes"][0]["columns"] = [{"field": "code", "label": "Unique heading"}, {"field": "title"}]
    return project, created_layout(world, project, tree)


def test_the_pdf_table_repeats_its_header_unless_switched_off(world):
    from reportlab.lib import colors

    from app.services.report_model import Table
    from app.services.report_pdf import _InlineImages, _table

    accent, images = colors.HexColor("#336699"), _InlineImages()
    on = _table(Table(["A"], [["x"]] * 3), accent, 500.0, 700.0, images)
    off = _table(Table(["A"], [["x"]] * 3, repeat_header=False), accent, 500.0, 700.0, images)
    images.close()
    assert on.repeatRows == 1 and off.repeatRows == 0


def test_a_long_pdf_table_still_runs_over_pages_either_way(world):
    project, on = long_table_layout(world)
    project2, off = long_table_layout(world, repeat_table_header=False)
    assert pdf_pages(run(world, project, on, "pdf")) > 1 and pdf_pages(run(world, project2, off, "pdf")) > 1


def test_word_odt_and_html_follow_the_switch(world):
    project, on = long_table_layout(world)
    project2, off = long_table_layout(world, repeat_table_header=False)
    assert b"<w:tblHeader" in zipfile.ZipFile(io.BytesIO(run(world, project, on, "docx"))).read("word/document.xml")
    assert b"<w:tblHeader" not in zipfile.ZipFile(io.BytesIO(run(world, project2, off, "docx"))).read("word/document.xml")
    assert b"table:table-header-rows" in zipfile.ZipFile(io.BytesIO(run(world, project, on, "odt"))).read("content.xml")
    assert b"table:table-header-rows" not in zipfile.ZipFile(io.BytesIO(run(world, project2, off, "odt"))).read("content.xml")
    assert "<thead>" in run(world, project, on, "html").decode()
    assert "<thead>" not in run(world, project2, off, "html").decode()
