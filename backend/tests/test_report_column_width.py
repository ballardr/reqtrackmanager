"""Tests for a table column's forced width.

Covers the width grammar and the shared resolver, the tree check, the text view (including `@images colwidth`), a run
over a table, and every output format: two tables with different content lay out their columns identically, a table with
no width is unchanged, and a sheet's forced widths reach XLSX and ODS.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

import pytest
from docx import Document
from openpyxl import load_workbook

from app.services import report_pdf
from app.services.report_column_width import (
    CM_PER_CHARACTER,
    MIN_AUTO_CM,
    MIN_COLUMN_CM,
    canonical_width,
    parse_width,
    percent_total,
    resolve_table_widths_cm,
    sheet_widths_cm,
    width_problem,
)
from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import InvalidLayoutError, assert_valid, empty_tree
from app.services.report_model import ReportDocument, Sheet, Table
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from app.services.report_render import RenderInput, render_ods, render_xlsx
from app.services.report_starters import STARTERS
from tests.conftest import auth_headers
from tests.link_world import World


def table_tree(*columns: dict[str, Any]) -> dict[str, Any]:
    return {**empty_tree("document"), "nodes": [{"type": "table", "source": {"record_type": "pain_point"}, "columns": list(columns)}]}


def errors_of(tree: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(InvalidLayoutError) as caught:
        assert_valid(tree)
    return [(e.path, e.message) for e in caught.value.errors]


# ---- the grammar and the resolver ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "expected"),
    [("30%", ("percent", 30.0)), ("12.5 %", ("percent", 12.5)), ("4 cm", ("cm", 4.0)), ("40mm", ("cm", 4.0)), ("4 CM", ("cm", 4.0))],
)
def test_a_width_is_a_percentage_or_a_length(spec, expected):
    assert parse_width(spec) == expected


@pytest.mark.parametrize("spec", ["", "auto", "30", "4 inches", "-3%", "3%%", None, 30])
def test_anything_else_is_not_a_width(spec):
    assert parse_width(spec) is None
    assert width_problem(spec)


@pytest.mark.parametrize("spec", ["0%", "101%", "2 mm", "101 cm"])
def test_a_width_outside_its_range_is_refused(spec):
    assert width_problem(spec)


def test_the_written_form_of_a_width_is_one_form():
    assert [canonical_width(s) for s in ("30 %", "4cm", "40 MM", "12.50%")] == ["30%", "4 cm", "40 mm", "12.5%"]
    with pytest.raises(ValueError, match="Not a width"):
        canonical_width("wide")


def test_percentages_are_totalled_and_lengths_are_not():
    assert percent_total(["30%", "4 cm", None, "20%"]) == 50


def test_fixed_columns_take_their_width_and_auto_columns_share_the_rest():
    widths = resolve_table_widths_cm(["10%", "4 cm", None, None], 20.0)
    assert widths[:2] == pytest.approx([2.0, 4.0])
    assert widths[2:] == pytest.approx([7.0, 7.0])


def test_auto_columns_share_the_rest_by_weight():
    widths = resolve_table_widths_cm(["20%", None, None], 20.0, weights=[1.0, 1.0, 3.0])
    assert widths == pytest.approx([4.0, 4.0, 12.0])


def test_widths_that_do_not_fill_the_table_are_scaled_to_it():
    assert resolve_table_widths_cm(["10%", "20%"], 20.0) == pytest.approx([6.667, 13.333], abs=0.001)


def test_widths_wider_than_the_table_are_scaled_down_and_never_exceed_it():
    widths = resolve_table_widths_cm(["15 cm", "15 cm", None], 20.0)
    assert sum(widths) == pytest.approx(20.0)
    assert widths[2] >= MIN_AUTO_CM * 20.0 / (30 + MIN_AUTO_CM)  # the auto column keeps a share of its own


def test_no_column_is_laid_out_narrower_than_the_floor():
    widths = resolve_table_widths_cm(["1%", "99%"], 17.0)
    assert widths == pytest.approx([MIN_COLUMN_CM, 17.0 - MIN_COLUMN_CM])


def test_the_floor_gives_way_when_the_columns_cannot_all_have_it():
    widths = resolve_table_widths_cm(["10%"] * 30, 12.0)
    assert sum(widths) == pytest.approx(12.0)
    assert min(widths) == pytest.approx(0.4)


def test_a_sheets_percentages_are_of_a_nominal_width_and_auto_stays_content_sized():
    assert sheet_widths_cm(["10%", "5 cm", None]) == [2.5, 5.0, None]


# ---- the tree ----------------------------------------------------------------------------------------------------


def test_a_table_column_may_carry_a_width():
    assert_valid(table_tree({"field": "code", "width": "12%"}, {"field": "title", "width": "4 cm"}, {"images": {}, "width": "30%"}))


def test_a_bad_width_names_the_column():
    errors = errors_of(table_tree({"field": "code"}, {"field": "title", "width": "wide"}))
    assert errors[0][0].endswith("columns[1].width")
    assert "percentage" in errors[0][1]


def test_percentages_over_a_hundred_are_one_error_on_the_columns():
    errors = errors_of(table_tree({"field": "code", "width": "60%"}, {"field": "title", "width": "50%"}))
    assert errors == [(errors[0][0], "The columns' percentage widths add up to 110%; they must not exceed 100%.")]
    assert errors[0][0].endswith(".columns")


def test_lengths_may_add_to_more_than_the_page_because_the_renderers_scale_them():
    assert_valid(table_tree({"field": "code", "width": "60 cm"}, {"field": "title", "width": "60 cm"}))


def test_a_sheet_column_may_carry_a_width():
    tree = {
        **empty_tree("table"),
        "nodes": [{"type": "sheet", "name": "S", "source": {"record_type": "pain_point"}, "columns": [{"field": "code", "width": "5 cm"}]}],
    }
    assert_valid(tree)


# ---- the text view ----------------------------------------------------------------------------------------------


def roundtrip(tree: dict[str, Any]) -> str:
    text = format_tree(tree)
    result = parse_text(text)
    assert result.errors == [], (text, result.errors)
    assert result.tree == tree, text
    assert format_tree(result.tree) == text
    return text


def test_a_width_reads_back_exactly_from_the_text_view():
    tree = table_tree(
        {"field": "code", "label": "ID", "width": "12%"}, {"field": "title", "width": "4 cm"},
        {"field": "status", "width": "40 mm"}, {"images": {"width": 90, "width_unit": "percent"}, "label": "Photos", "width": "20%"},
        {"field": "description"},
    )
    text = roundtrip(tree)
    assert '@column code "ID" width 12%' in text
    assert "@column title width 4 cm" in text
    assert "@column status width 40 mm" in text
    assert re.search(r'@images .*colwidth 20%', text)


def test_width_auto_is_no_width():
    result = parse_text('@layout document\n@table pain_point\n  @column code width auto\n@end\n')
    assert result.errors == []
    assert result.tree["nodes"][0]["columns"] == [{"field": "code"}]


def test_a_sheet_column_takes_a_width_after_its_link():
    result = parse_text('@layout table\n@sheet "S" pain_point\n  @column code "Code" width 5 cm\n@end\n')
    assert result.errors == []
    assert result.tree["nodes"][0]["columns"] == [{"field": "code", "label": "Code", "width": "5 cm"}]


@pytest.mark.parametrize(
    ("clause", "fragment"),
    [
        ("width", "Expected a width"), ("width wide", "percentage"), ("width 4", "percentage"), ("width 150%", "1%"),
        ("width 3% width 4%", "written once"),
    ],
)
def test_a_mistaken_width_is_reported_on_its_line(clause, fragment):
    result = parse_text(f"@layout document\n@table pain_point\n  @column code {clause}\n@end\n")
    assert result.errors and result.errors[0].line == 3
    assert fragment in result.errors[0].message


# ---- every document format -------------------------------------------------------------------------------------


def document_of(*tables: Table) -> ReportDocument:
    return ReportDocument(title="Widths", blocks=list(tables))


def two_tables(widths: list[str | None]) -> ReportDocument:
    """Two tables of different content (a short and a long cell) sharing one set of widths."""
    short = Table(["Code", "Title", "Notes"], [["A-1", "x", "y"]], compact=True, widths=widths)
    long = Table(
        ["Code", "Title", "Notes"],
        [["ACME-REQ-0001", "A very long title " * 8, "supercalifragilisticexpialidocious" * 4]] * 3,
        compact=True, widths=widths,
    )
    return document_of(short, long)


WIDTHS = ["10%", "5 cm", None]


def test_word_tables_have_a_fixed_grid_and_the_same_columns():
    document = Document(io.BytesIO(render_docx_document(two_tables(WIDTHS))))
    grids = [[column.width for column in table.columns] for table in document.tables]
    assert grids[0] == grids[1]
    assert all(width and width > 0 for width in grids[0])
    for table in document.tables:
        layout = table._tbl.tblPr.xpath("w:tblLayout")
        assert layout and layout[0].get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") == "fixed"
    first, second, third = grids[0]
    assert second > first  # 5 cm is wider than 10 % of the page
    assert third > 0


def test_a_word_table_with_no_width_keeps_its_equal_columns():
    document = Document(io.BytesIO(render_docx_document(document_of(Table(["A", "B"], [["1", "2"]])))))
    widths = [column.width for column in document.tables[0].columns]
    assert widths[0] == widths[1]


def odt_columns(data: bytes) -> list[list[float]]:
    """The column widths in cm of each table of an ODT, in order."""
    xml = zipfile.ZipFile(io.BytesIO(data)).read("content.xml").decode()
    column_style = r'style:name="([^"]+)" style:family="table-column"><style:table-column-properties style:column-width="([\d.]+)cm"'
    style_width = {m.group(1): float(m.group(2)) for m in re.finditer(column_style, xml)}
    tables = []
    for match in re.finditer(r"<table:table [^>]*>((?:<table:table-column [^>]*/>)+)", xml):
        tables.append([style_width[name] for name in re.findall(r'table:style-name="([^"]+)"', match.group(1))])
    return tables


def test_open_document_tables_have_the_same_columns():
    first, second = odt_columns(render_odt_document(two_tables(WIDTHS)))
    assert first == pytest.approx(second)
    assert first[1] > first[0]
    assert sum(first) == pytest.approx(sum(second))


def test_html_tables_are_fixed_with_a_column_per_width():
    html = render_html_document(two_tables(WIDTHS)).decode()
    groups = re.findall(r"<colgroup>(.*?)</colgroup>", html)
    assert groups == ['<col style="width:10%"><col style="width:5cm"><col>'] * 2
    assert html.count('<table class="compact fixed">') == 2
    assert "table.fixed { table-layout: fixed; }" in html


def test_html_tables_without_widths_are_not_fixed():
    html = render_html_document(document_of(Table(["A"], [["1"]], compact=True))).decode()
    assert "<colgroup>" not in html
    assert '<table class="compact">' in html


def test_pdf_tables_have_the_same_columns(monkeypatch):
    seen: list[list[float]] = []
    real = report_pdf.styled_table

    def spy(data, *, col_widths, **kwargs):
        seen.append(list(col_widths))
        return real(data, col_widths=col_widths, **kwargs)

    monkeypatch.setattr(report_pdf, "styled_table", spy)
    pdf = render_pdf_document(two_tables(WIDTHS))
    assert pdf.startswith(b"%PDF")
    assert len(seen) == 2
    assert seen[0] == pytest.approx(seen[1])
    assert seen[0][1] > seen[0][0]


def test_a_pdf_table_with_no_width_is_sized_as_before(monkeypatch):
    seen: list[list[float]] = []
    real = report_pdf.styled_table

    def spy(data, *, col_widths, **kwargs):
        seen.append(list(col_widths))
        return real(data, col_widths=col_widths, **kwargs)

    monkeypatch.setattr(report_pdf, "styled_table", spy)
    render_pdf_document(document_of(Table(["A", "B"], [["1", "2"]])))
    assert seen[0][0] == pytest.approx(seen[0][1])


def test_a_column_too_narrow_for_its_word_still_renders_in_every_format():
    narrow = document_of(Table(["Code", "Title"], [["supercalifragilisticexpialidocious", "x"]], compact=True, widths=["1%", "99%"]))
    for render in (render_pdf_document, render_docx_document, render_odt_document, render_html_document):
        assert render(narrow)


# ---- sheets ------------------------------------------------------------------------------------------------------


def sheet_with(widths: list[float | None] | None) -> Sheet:
    return Sheet("Data", ["Code", "Title"], [["A-1", "a longish title that would normally size the column"]], widths_cm=widths)


def test_xlsx_uses_a_forced_width_and_sizes_the_others_from_content():
    data = render_xlsx(RenderInput("Widths", sheets=[sheet_with([5.0, None])])).content
    sheet = load_workbook(io.BytesIO(data))["Data"]
    assert sheet.column_dimensions["A"].width == pytest.approx(5.0 / CM_PER_CHARACTER)
    assert sheet.column_dimensions["B"].width > 20


def test_ods_uses_a_forced_width():
    data = render_ods(RenderInput("Widths", sheets=[sheet_with([5.0, None])])).content
    xml = zipfile.ZipFile(io.BytesIO(data)).read("content.xml").decode()
    widths = [float(w) for w in re.findall(r'style:column-width="([\d.]+)cm"', xml)]
    assert widths[0] == pytest.approx(5.0)
    assert widths[1] > 5.0


def test_a_sheet_with_no_widths_is_sized_from_its_content():
    data = render_xlsx(RenderInput("Widths", sheets=[sheet_with(None)])).content
    sheet = load_workbook(io.BytesIO(data))["Data"]
    assert sheet.column_dimensions["A"].width == 8



# ---- a run over real records -------------------------------------------------------------------------------------


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Column Width Org", context_strategy=True)


def pain_point_world(world):
    project = world.project("Alpha")
    world.pain_point(project, "First")
    world.pain_point(project, "Second")
    return project


def created_layout(world, project: dict, tree: dict) -> dict:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts",
        json={"name": "Widths", "description": "d", "family": tree["family"], "tree": tree}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def run(world, project: dict, layout: dict, fmt: str) -> bytes:
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": fmt}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, (fmt, resp.text)
    return resp.content


def test_a_run_fixes_the_columns_in_the_preview_and_in_every_document_format(world):
    project = pain_point_world(world)
    tree = table_tree({"field": "code", "width": "15%"}, {"field": "title", "width": "5 cm"}, {"field": "status"})
    html = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts/preview", json={"tree": tree}, headers=auth_headers(world.token),
    ).json()["html"]
    assert '<colgroup><col style="width:15%"><col style="width:5cm"><col></colgroup>' in html

    layout = created_layout(world, project, tree)
    grid = [c.width for c in Document(io.BytesIO(run(world, project, layout, "docx"))).tables[0].columns]
    assert grid[1] > grid[0] and grid[2] > 0
    assert len(odt_columns(run(world, project, layout, "odt"))[0]) == 3
    assert run(world, project, layout, "pdf").startswith(b"%PDF")


def test_a_sheet_run_carries_the_forced_widths_into_the_workbook(world):
    project = pain_point_world(world)
    tree = {
        **empty_tree("table"),
        "nodes": [{
            "type": "sheet", "name": "Pain points", "source": {"record_type": "pain_point"},
            "columns": [{"field": "code", "width": "6 cm"}, {"field": "title"}],
        }],
    }
    layout = created_layout(world, project, tree)
    sheet = load_workbook(io.BytesIO(run(world, project, layout, "xlsx")))["Pain points"]
    assert sheet.column_dimensions["A"].width == pytest.approx(6.0 / CM_PER_CHARACTER)
    assert sheet.column_dimensions["B"].width != sheet.column_dimensions["A"].width


# ---- the starters ------------------------------------------------------------------------------------------------


def _tables(nodes: list[dict[str, Any]]):
    for node in nodes:
        if node["type"] == "table":
            yield node
        yield from _tables(node.get("children", []))


def test_every_starter_table_fixes_the_width_of_its_code_column():
    tables = [(starter.name, table) for starter in STARTERS for table in _tables(starter.tree["nodes"])]
    assert len(tables) >= 8, "the starters and the module sections contribute tables"
    for name, table in tables:
        codes = [c for c in table["columns"] if c["field"] == "code"]
        assert all(c.get("width") for c in codes), (name, table["columns"])
        assert percent_total([c.get("width") for c in table["columns"]]) <= 85, (name, table["columns"])
