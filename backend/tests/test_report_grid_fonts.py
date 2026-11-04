"""Tests for the font and size of a custom table (`grid`) at grid and column level: the tree rules, the text view, the
cascade (column over grid over the document), and what each of the four formats writes. A row or cell never sets either."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import replace
from typing import Any

import pytest

from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_model import DocumentStyles, Grid, GridCell, GridRow, MathText, ReportDocument, Styled
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from app.services.report_styles import font_keys, used_extra_families
from tests.conftest import auth_headers
from tests.test_report_images import db, world  # noqa: F401 - the world and db fixtures
from tests.test_report_styles import create, errors_of, family, pdf_fonts, styled_tree

MONO, SERIF = family("mono"), family("serif")


def tree_with(*nodes: dict[str, Any], styles: dict[str, Any] | None = None) -> dict[str, Any]:
    tree = styled_tree(styles)
    tree["nodes"] = list(nodes)
    return tree


def grid_node(**settings: Any) -> dict[str, Any]:
    """A two-column grid; `settings` go on the grid, and `columns` (a list of column objects) replaces the default."""
    columns = settings.pop("columns", [{}, {}])
    return {"type": "grid", "columns": columns, "rows": [{"cells": [{"text": "code"}, {"text": "words"}]}], **settings}


def cell(text: str, font=None, size=None, bold=False) -> GridCell:
    return GridCell((text,), font=font, size=size, bold=bold)


def document(*blocks: Any) -> ReportDocument:
    return ReportDocument(title="Title", blocks=list(blocks), styles=DocumentStyles())


def two_column_grid() -> Grid:
    """A mono first column, a serif second column at 12 pt, and a third column that sets nothing."""
    return Grid(
        [None, None, None],
        [GridRow([cell("monoword", MONO), cell("serifword", SERIF, 12), cell("plainword")])],
    )


def content_xml(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("content.xml").decode()


def body_xml(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()


# ---- the tree ----------------------------------------------------------------------------------------------------


def test_a_grid_and_a_column_may_set_a_font_and_size():
    from app.services.report_layout_tree import assert_valid

    assert_valid(tree_with(grid_node(font="serif", size=10, columns=[{"font": "mono", "size": 8.5}, {}])))


@pytest.mark.parametrize(("node", "path", "text"), [
    (grid_node(font="Times"), "nodes[0].font", "Must be a font"),
    (grid_node(size=5), "nodes[0].size", "from 6 to 72"),
    (grid_node(size="9"), "nodes[0].size", "number of points"),
    (grid_node(columns=[{"font": 3}, {}]), "nodes[0].columns[0].font", "Must be a font"),
    (grid_node(columns=[{}, {"size": 73}]), "nodes[0].columns[1].size", "from 6 to 72"),
    (grid_node(columns=[{}, {"size": 10.2}]), "nodes[0].columns[1].size", "whole or half"),
])
def test_a_bad_grid_or_column_font_or_size_is_refused_with_its_path(node, path, text):
    assert any(p == path and text in m for p, m in errors_of(tree_with(node)))


def test_a_row_or_a_cell_cannot_set_a_font_or_size():
    node = grid_node()
    node["rows"] = [{"font": "mono", "cells": [{"text": "x", "size": 9}, {"text": "y"}]}]
    problems = errors_of(tree_with(node))
    assert any(p == "nodes[0].rows[0].font" and "Unknown key" in m for p, m in problems)
    assert any(p == "nodes[0].rows[0].cells[0].size" and "Unknown key" in m for p, m in problems)


def test_the_fonts_a_tree_names_include_those_of_a_grid_and_its_columns_at_any_depth():
    tree = tree_with(
        grid_node(font="serif", columns=[{"font": "mono"}, {}]),
        {"type": "section", "page_style": "A", "children": [grid_node(columns=[{"font": "x-house-face"}, {}])]},
    )
    assert font_keys(tree) == ["serif", "mono", "x-house-face"]


# ---- the text view -----------------------------------------------------------------------------------------------


GRID_TEXT = (
    "@layout document\n\n"
    "@grid columns=2 font=serif size=9\n"
    "  @col 2 font=mono size=10.5\n"
    "  | a | b |\n"
    "@end\n"
)


def test_the_text_view_reads_and_writes_grid_and_column_fonts_exactly():
    parsed = parse_text(GRID_TEXT)
    assert not parsed.errors
    node = parsed.tree["nodes"][0]
    assert node["font"] == "serif" and node["size"] == 9
    assert node["columns"] == [{}, {"font": "mono", "size": 10.5}]
    assert "@grid columns=2 font=serif size=9" in format_tree(parsed.tree)
    assert "@col 2 font=mono size=10.5" in format_tree(parsed.tree)
    assert parse_text(format_tree(parsed.tree)).tree == parsed.tree


@pytest.mark.parametrize(("line", "message"), [
    ("@grid columns=2 size=big", "number of points"),
    ("@grid columns=2 size=9 size=10", "written once"),
    ("@grid columns=2 font=serif font=mono", "written once"),
])
def test_text_view_mistakes_in_a_grid_font_or_size_are_reported(line, message):
    parsed = parse_text(f"@layout document\n\n{line}\n  | a | b |\n@end\n")
    assert any(message in e.message for e in parsed.errors)


def test_a_row_or_cell_cannot_take_font_in_the_text_view():
    parsed = parse_text("@layout document\n\n@grid columns=2\n  @row font=mono\n  | a | b |\n@end\n")
    assert any("Unexpected" in e.message for e in parsed.errors)


# ---- the cascade, through the evaluator --------------------------------------------------------------------------


def test_the_column_wins_over_the_grid_and_an_unset_column_follows_the_grid(world):  # noqa: F811
    from tests.test_report_shapes import preview

    project = world.project("Alpha")
    result = preview(world, project, tree_with(grid_node(font="serif", size=10, columns=[{"font": "mono"}, {"size": 8}])))
    html = result["html"]
    cells = re.findall(r"<td[^>]*>", html)
    assert 'font-family:&quot;Courier New&quot;, monospace' in cells[0] and "font-size:10pt" in cells[0]
    assert 'font-family:&quot;Times New Roman&quot;, serif' in cells[1] and "font-size:8pt" in cells[1]


def test_a_grid_that_sets_nothing_is_drawn_as_before(world):  # noqa: F811
    from tests.test_report_shapes import preview

    project = world.project("Alpha")
    html = preview(world, project, tree_with(grid_node()))["html"]
    assert "font-family" not in "".join(re.findall(r"<td[^>]*>", html))


def test_a_column_naming_a_font_the_server_lacks_prints_in_the_standard_one_with_a_run_note(world):  # noqa: F811
    from tests.test_report_shapes import preview

    project = world.project("Alpha")
    result = preview(world, project, tree_with(grid_node(columns=[{"font": "x-house-face"}, {}])))
    assert any("x-house-face" in w for w in result["warnings"])


# ---- PDF ---------------------------------------------------------------------------------------------------------


def test_the_pdf_draws_each_columns_family_and_size():
    fonts = pdf_fonts(render_pdf_document(document(two_column_grid())))
    assert {"LiberationMono", "LiberationSerif", "Helvetica"} <= fonts


def test_a_grid_without_a_font_draws_in_the_documents_own_font_only():
    plain = Grid([None], [GridRow([cell("x")])])
    assert pdf_fonts(render_pdf_document(document(plain))) <= {"Helvetica", "Helvetica-Bold"}


def test_the_pdf_cell_style_takes_the_size_and_a_leading_two_points_larger():
    from app.services.report_grid_render import pdf_grid

    table = pdf_grid(Grid([None, None], [GridRow([cell("a", MONO, 14), cell("b")])]), 400, 700, lambda text, bold: text)
    big, small = (table._cellvalues[0][i][0].style for i in (0, 1))
    assert big.fontSize == 14 and big.leading == 16 and big.fontName == "Report-mono-regular"
    assert small.fontSize == 9


def test_a_bold_cell_in_a_family_column_uses_that_familys_bold_face():
    fonts = pdf_fonts(render_pdf_document(document(Grid([None], [GridRow([cell("x", SERIF, bold=True)])]))))
    assert "LiberationSerif-Bold" in fonts


# ---- Word --------------------------------------------------------------------------------------------------------


def test_word_writes_the_family_and_size_on_the_runs_of_that_column_only():
    body = body_xml(render_docx_document(document(two_column_grid())))
    mono = re.search(r"<w:p>(?:(?!</w:p>).)*monoword.*?</w:p>", body, re.S).group(0)
    assert 'w:ascii="Courier New"' in mono and 'w:val="18"' in mono  # the table's own 9 pt
    serif = re.search(r"<w:p>(?:(?!</w:p>).)*serifword.*?</w:p>", body, re.S).group(0)
    assert 'w:ascii="Times New Roman"' in serif and 'w:val="24"' in serif
    plain = re.search(r"<w:p>(?:(?!</w:p>).)*plainword.*?</w:p>", body, re.S).group(0)
    assert "<w:rFonts" not in plain and 'w:val="18"' in plain


# ---- OpenDocument ------------------------------------------------------------------------------------------------


def test_odt_gives_each_distinct_look_one_cell_paragraph_style_and_declares_the_family():
    xml = content_xml(render_odt_document(document(two_column_grid())))
    assert re.search(r'style:parent-style-name="Standard"><style:paragraph-properties[^>]*/><style:text-properties '
                     r'fo:font-size="9pt" style:font-name="Courier New"', xml)
    assert 'fo:font-size="12pt" style:font-name="Times New Roman"' in xml
    assert 'style:name="Courier New"' in xml and 'style:name="Times New Roman"' in xml


def test_odt_cells_that_look_alike_share_a_style():
    grid = Grid([None, None], [GridRow([cell("a", MONO, 10), cell("b", MONO, 10)])])
    xml = content_xml(render_odt_document(document(grid)))
    assert len(re.findall(r'style:name="Grid\d+_s\dp"', xml)) == 1


# ---- HTML --------------------------------------------------------------------------------------------------------


def test_html_sets_validated_css_only_on_cells_that_set_a_look():
    html = render_html_document(document(two_column_grid())).decode()
    assert re.search(r'<td[^>]*style="font-family:&quot;Courier New&quot;, monospace"[^>]*>', html)
    assert re.search(r'<td[^>]*style="font-family:&quot;Times New Roman&quot;, serif;font-size:12pt"[^>]*>', html)
    assert not re.search(r"<td[^>]*font[^>]*>(?:(?!</td>).)*plainword", html, re.S)


# ---- embedding ---------------------------------------------------------------------------------------------------


def test_bundled_grid_fonts_are_never_asked_to_be_embedded():
    assert used_extra_families(document(two_column_grid())) == []


def test_an_extra_family_named_only_by_a_grid_cell_is_found_for_embedding():
    extra = replace(MONO, key="x-house", bundled=False, faces_found=("regular", "bold"))
    grid = Grid([None], [GridRow([GridCell((MathText(["a ", Styled("b", bold=True)]),), font=extra)])])
    uses = used_extra_families(document(grid))
    assert [u.family.key for u in uses] == ["x-house"] and {"regular", "bold"} <= uses[0].styles


# ---- a run through the API ---------------------------------------------------------------------------------------


def test_a_run_prints_a_monospaced_column_in_all_four_formats(world):  # noqa: F811
    project = world.project("Alpha")
    h = auth_headers(world.token)
    layout = create(world, project, tree_with(grid_node(size=10, columns=[{"font": "mono"}, {}]), styles={"body": {"font": "serif"}}))
    base = f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run"
    pdf = world.client.get(base, params={"format": "pdf"}, headers=h)
    assert pdf.status_code == 200, pdf.text
    assert {"LiberationMono", "LiberationSerif"} <= pdf_fonts(pdf.content)
    docx = world.client.get(base, params={"format": "docx"}, headers=h).content
    mono = re.search(r"<w:p>(?:(?!</w:p>).)*code.*?</w:p>", body_xml(docx), re.S).group(0)
    assert 'w:ascii="Courier New"' in mono and 'w:val="20"' in mono
    odt = world.client.get(base, params={"format": "odt"}, headers=h).content
    assert 'style:font-name="Courier New"' in content_xml(odt)
    html = world.client.get(base, params={"format": "html"}, headers=h).text
    assert "Courier New" in html and "font-size:10pt" in html
