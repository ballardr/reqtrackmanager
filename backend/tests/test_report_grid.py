"""Tests for the custom table (`grid` block): the span checks, tree validation, the text view (including an exact round
trip), the evaluator (style cascade, colour words, Markdown in a cell, placeholders) and the four drawings read back (PDF,
Word, ODT, HTML) for merged cells, per-cell alignment and colour, row heights, borders and header rows.

Validation, the text view and the drawings need no database; the evaluator tests build an organisation. The same case
set was also opened in LibreOffice (Word and ODT) and the PDF rendered, as the decisions log's custom tables entries say."""

from __future__ import annotations

import html
import io
import random
import uuid
import zipfile
from typing import Any

import pytest
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from lxml import etree
from lxml import html as lxml_html
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate

from app.database import SessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.services import report_layout_eval
from app.services.link_graph import ArtefactResolver
from app.services.report_docx import _add_text, render_docx_document
from app.services.report_framework import ReportContext
from app.services.report_grid import border_edges, cell_paragraphs, low_contrast, place_grid, place_spans, text_lines
from app.services.report_grid_render import docx_grid, html_grid, odt_grid, pdf_grid
from app.services.report_html import render_html_document
from app.services.report_layout_eval import evaluate_layout
from app.services.report_layout_text import TEXT_FORMS, format_tree, parse_text
from app.services.report_layout_tree import BLOCK_SPECS, FAMILY_DOCUMENT, tree_hash, validate_tree
from app.services.report_model import (
    BulletList,
    Equation,
    Grid,
    GridCell,
    GridRow,
    MathText,
    NumberedList,
    PageStyle,
    Paragraph,
    ReportDocument,
    Styled,
)
from app.services.report_odf import xml_text
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from tests.conftest import auth_headers
from tests.link_world import REQ, World
from tests.test_report_layout_tree import doc, errors

USABLE = PageStyle().usable_width_cm
NS = {"table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0", "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
      "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0", "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
      "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0"}
ODF_NS = " ".join(f'xmlns:{prefix}="{uri}"' for prefix, uri in NS.items())
BLACK = {"fill": "#000000", "color": "#ffffff", "bold": True}


def cell(text: str = "", **style: Any) -> GridCell:
    return GridCell(tuple(text.split("\n")) if text else ("",), **style)


def row(*cells: GridCell, height: float | None = None) -> GridRow:
    return GridRow(list(cells), height)


def square(rows: list[GridRow], **kwargs: Any) -> Grid:
    return Grid(widths=["25%"] * 4, rows=rows, **kwargs)


def case_set() -> Grid:
    """A 4-column grid with a header, a title across four columns, a label down two rows, black bold columns 1 and 3, a right
    aligned, a justified and a middle aligned cell, and a blank 2 cm row."""
    note = "A longer review note that wraps across several lines so that justification and a vertical merge can be seen."
    return Grid(
        widths=["20%", None, "20%", None], header_rows=1,
        rows=[
            row(cell("Document details", colspan=4, align="center", fill="#1f4e79", color="#ffffff", bold=True)),
            row(cell("Document", **BLACK), cell("Quarterly risk report"), cell("Version", **BLACK), cell("1.2", align="right")),
            row(cell("Review", rowspan=2, valign="middle", **BLACK), cell(note, align="justify"), cell("Date", **BLACK), cell("")),
            row(cell("Reviewer"), cell("Status", **BLACK), cell("Draft", valign="middle", align="center")),
            row(cell("Approval", **BLACK), cell(""), cell("Date", **BLACK), cell(""), height=2.0),
        ],
    )


def grid_node(rows: list[dict[str, Any]], columns: int = 4, **extra: Any) -> dict[str, Any]:
    return {"type": "grid", "columns": [{} for _ in range(columns)], "rows": rows, **extra}


def cells(*texts: str, **style: Any) -> dict[str, Any]:
    return {"cells": [{"text": text, **style} for text in texts]}


# ---- the span check ----------------------------------------------------------------------------------------------


def test_the_case_set_places_every_cell_once():
    placed = place_grid(case_set())
    assert len(placed) == 16 and {(p.row, p.col) for p in placed} >= {(0, 0), (2, 0), (3, 1)}
    assert [(p.last_row, p.last_col) for p in placed if p.cell.rowspan > 1] == [(3, 0)]


@pytest.mark.parametrize(
    ("spans", "header", "row_index", "cell_index", "message"),
    [
        ([[(3, 1), (2, 1)]], 0, 0, 1, "more cells|past the edge|overlaps"),
        ([[(1, 1), (1, 2), (1, 1), (1, 1)], [(2, 1), (1, 1), (1, 1)]], 0, 1, 0, "overlaps"),
        ([[(1, 2), (1, 1), (1, 1), (1, 1)]], 0, 0, 0, "past the edge"),
        ([[(1, 1), (1, 1)]], 0, 0, None, "fewer cells"),
        ([[(1, 1)] * 5], 0, 0, 4, "more cells"),
        ([[(0, 1), (1, 1), (1, 1), (1, 1)]], 0, 0, 0, "at least one"),
        ([[(1, 2), (1, 1), (1, 1), (1, 1)], [(1, 1), (1, 1), (1, 1)]], 1, 0, 0, "header rows"),
    ],
)
def test_a_bad_merge_is_reported_with_its_row_and_cell(spans, header, row_index, cell_index, message):
    _, problems = place_spans(4, spans, header)
    assert any(p.row == row_index and p.cell == cell_index and any(m in p.message for m in message.split("|")) for p in problems), problems


def test_low_contrast_is_flagged_but_a_good_pair_and_a_missing_colour_are_not():
    assert low_contrast("#777777", "#888888") and not low_contrast("#000000", "#ffffff")
    assert not low_contrast(None, "#888888") and not low_contrast("#777777", None)


@pytest.mark.parametrize(("borders", "edges"), [("all", (True,) * 4), ("none", (False,) * 4), ("horizontal", (True, False, True, False))])
def test_border_edges_for_an_inner_cell(borders, edges):
    inner = next(p for p in place_grid(square([row(*[cell(str(i)) for i in range(4)]) for _ in range(3)])) if (p.row, p.col) == (1, 1))
    assert border_edges(borders, inner, 4, 3) == edges


def test_outer_borders_draw_only_the_edge_of_the_table():
    placed = {(p.row, p.col): p for p in place_grid(square([row(*[cell(str(i)) for i in range(4)]) for _ in range(3)]))}
    assert border_edges("outer", placed[(1, 1)], 4, 3) == (False, False, False, False)
    assert border_edges("outer", placed[(0, 3)], 4, 3) == (True, True, False, False)
    assert border_edges("outer", placed[(2, 0)], 4, 3) == (False, False, True, True)


# ---- the cell's text ---------------------------------------------------------------------------------------------


def test_a_line_break_starts_a_new_paragraph_and_keeps_styles():
    value = MathText(["a ", Styled("bold", bold=True), "\nsecond ", Equation("x", False)])
    lines = text_lines(value)
    assert [str(line) for line in lines] == ["a bold", "second \\(x\\)"]
    assert isinstance(lines[0], MathText) and lines[0].parts[1] == Styled("bold", bold=True)


def test_cell_paragraphs_read_lists_headings_and_display_equations():
    blocks = [Paragraph("one\ntwo"), BulletList(["x", "y"]), NumberedList(["p", "q"])]
    assert [str(p) for p in cell_paragraphs(blocks)] == ["one", "two", "• x", "• y", "1. p", "2. q"]
    assert cell_paragraphs([]) == ("",)
    assert cell_paragraphs([Equation("x^2", True)])[0].parts == (Equation("x^2", False),)


# ---- the tree ----------------------------------------------------------------------------------------------------


def test_the_block_is_registered_everywhere_a_block_must_be():
    assert "grid" in BLOCK_SPECS and "grid" in TEXT_FORMS and "grid" in report_layout_eval._EVALUATORS
    assert BLOCK_SPECS["grid"].families == (FAMILY_DOCUMENT,)
    schema = BLOCK_SPECS["grid"].schema
    assert schema is not None and schema.label == "Table (custom)" and all(f.help for f in schema.fields)
    assert validate_tree(doc(schema.template)).ok


def valid_node() -> dict[str, Any]:
    return grid_node(
        [cells("Title", colspan=4, align="center", fill="primary"), {"height": 2, "cells": [{"text": ""}] * 4}],
        columns=4, header_rows=1, borders="outer", border_color="#999999", fill="white", color="black", bold=True,
    ) | {"columns": [{"width": "25%", "fill": "#000000", "color": "#ffffff", "bold": True}, {}, {"width": "4 cm"}, {"width": "30%"}]}


def test_a_valid_grid_passes():
    assert validate_tree(doc(valid_node())).ok, validate_tree(doc(valid_node())).errors


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (lambda n: n.update(borders="dotted"), "nodes[0].borders"),
        (lambda n: n.update(border_color="none"), "nodes[0].border_color"),
        (lambda n: n.update(border_color="red; x"), "nodes[0].border_color"),
        (lambda n: n.update(align="diagonal"), "nodes[0].align"),
        (lambda n: n.update(valign="centre"), "nodes[0].valign"),
        (lambda n: n.update(fill="#12"), "nodes[0].fill"),
        (lambda n: n.update(color='#fff" onload="x'), "nodes[0].color"),
        (lambda n: n.update(bold="yes"), "nodes[0].bold"),
        (lambda n: n.update(header_rows=9), "nodes[0].header_rows"),
        (lambda n: n.update(header_rows=True), "nodes[0].header_rows"),
        (lambda n: n.update(shadow=True), "nodes[0].shadow"),
        (lambda n: n.update(columns=[]), "nodes[0].columns"),
        (lambda n: n.update(columns=[{}] * 21), "nodes[0].columns"),
        (lambda n: n.update(columns=[{"width": "big"}] * 4), "nodes[0].columns[0].width"),
        (lambda n: n.update(columns=[{"width": "60%"}, {"width": "60%"}, {}, {}]), "nodes[0].columns"),
        (lambda n: n.update(columns=[{"colspan": 2}, {}, {}, {}]), "nodes[0].columns[0].colspan"),
        (lambda n: n.update(rows=[]), "nodes[0].rows"),
        (lambda n: n.update(rows=[cells("a")] * 201), "nodes[0].rows"),
        (lambda n: n["rows"][1].update(height=0.1), "nodes[0].rows[1].height"),
        (lambda n: n["rows"][1].update(height=21), "nodes[0].rows[1].height"),
        (lambda n: n["rows"][1].update(height_unit="mm"), "nodes[0].rows[1].height"),
        (lambda n: n["rows"][1].update(height_unit="inch"), "nodes[0].rows[1].height_unit"),
        (lambda n: n["rows"][0]["cells"][0].update(text="x" * 2001), "nodes[0].rows[0].cells[0].text"),
        (lambda n: n["rows"][0]["cells"][0].update(text="{{nonesuch}}"), "nodes[0].rows[0].cells[0].text"),
        (lambda n: n["rows"][0]["cells"][0].update(text=5), "nodes[0].rows[0].cells[0].text"),
        (lambda n: n["rows"][0]["cells"][0].pop("text"), "nodes[0].rows[0].cells[0].text"),
        (lambda n: n["rows"][0]["cells"][0].update(colspan=5), "nodes[0].rows[0].cells[0]"),
        (lambda n: n["rows"][0]["cells"][0].update(colspan=0), "nodes[0].rows[0].cells[0].colspan"),
        (lambda n: n["rows"][0]["cells"][0].update(rowspan=True), "nodes[0].rows[0].cells[0].rowspan"),
        (lambda n: n["rows"][0]["cells"][0].update(italic=True), "nodes[0].rows[0].cells[0].italic"),
        (lambda n: n["rows"][0]["cells"][0].update(rowspan=2), "nodes[0].rows[0].cells[0]"),
        (lambda n: n["rows"][1]["cells"].pop(), "nodes[0].rows[1]"),
    ],
)
def test_a_bad_grid_is_refused_at_its_path(change, path):
    node = valid_node()
    change(node)
    assert path in errors(doc(node)), errors(doc(node))


def test_a_scheme_name_must_be_one_the_layout_or_organisation_defines():
    node = grid_node([cells("a", fill="brand")], columns=1)
    found = {e.path for e in validate_tree(doc(node), organization_colours=[]).errors}
    assert found == {"nodes[0].rows[0].cells[0].fill"}
    assert validate_tree({**doc(node), "palette": [{"name": "brand", "colour": "#112233"}]}, organization_colours=[]).ok
    assert validate_tree(doc(node), organization_colours=["brand"]).ok


def test_a_table_layout_refuses_a_grid():
    assert errors({"schema_version": 1, "family": "table", "nodes": [grid_node([cells("a")], columns=1)]})


def test_a_grid_inside_a_loop_may_name_the_record():
    node = {"type": "each", "source": {"record_type": REQ}, "children": [grid_node([cells("{{record.title}}")], columns=1)]}
    assert validate_tree(doc(node)).ok
    node["children"][0]["rows"][0]["cells"][0]["text"] = "{{other.title}}"
    assert errors(doc(node))


# ---- the text view -----------------------------------------------------------------------------------------------


TEXT_CASE = """@layout document

@grid columns=4 headerrows=1 borders=outer bordercolor=#999999
  @col 1 width=25% fill=#000000 color=#ffffff bold
  @col 3 fill=#000000 color=#ffffff bold
  | {colspan=4 align=center fill=primary} Document details |
  | Document | {{report_title}} | Version | {align=right} 1.2 |
  @row height=2cm
  | Review | a \\| b\\nline two | {rowspan=2} Date | |
  | Reviewer | Status | Draft |
@end
"""


def test_the_text_view_reads_a_grid_and_writes_it_back_unchanged():
    parsed = parse_text(TEXT_CASE)
    assert parsed.errors == [], parsed.errors
    node = parsed.tree["nodes"][0]
    assert node["header_rows"] == 1 and node["columns"][0] == {"width": "25%", "fill": "#000000", "color": "#ffffff", "bold": True}
    assert node["rows"][0]["cells"] == [{"colspan": 4, "align": "center", "fill": "primary", "text": "Document details"}]
    assert node["rows"][2]["height"] == 2 and node["rows"][2]["cells"][1]["text"] == "a | b\nline two"
    assert node["rows"][2]["cells"][3] == {"text": ""}
    written = format_tree(parsed.tree)
    again = parse_text(written)
    assert again.errors == [] and again.tree == parsed.tree and tree_hash(again.tree) == tree_hash(parsed.tree)


@pytest.mark.parametrize("text", ["", " ", "  two  spaces  ", "a|b", "a\\b", "\\|", "{literal", "{{report_title}}", "line\nbreak\r\nthere",
                                  "tab\there", "- a\n- b", "1. x\n2. y", "**bold** and \\(x^2\\)", "@not a directive", "| leading bar",
                                  "trailing \\", "é ü 漢"])
def test_a_cell_reads_back_exactly(text):
    tree = doc(grid_node([{"cells": [{"text": text}, {"text": "b", "colspan": 2, "bold": False}, {"text": text, "align": "right"}]}], columns=4))
    tree["nodes"][0]["rows"][0]["cells"][1]["colspan"] = 2  # three cells cover the four columns
    tree["nodes"][0]["rows"].append(cells(*["x"] * 4))
    written = format_tree(tree)
    parsed = parse_text(written)
    assert parsed.errors == [], (written, parsed.errors)
    assert parsed.tree == tree, written


def test_a_row_with_no_cells_is_two_bars_and_reads_back():
    tree = doc(grid_node([{"cells": [{"text": "a", "colspan": 2, "rowspan": 2}]}, {"cells": []}], columns=2))
    written = format_tree(tree)
    assert "||" in written
    parsed = parse_text(written)
    assert parsed.errors == [] and parsed.tree == tree


def random_grid(rng: random.Random) -> dict[str, Any]:
    """A valid random grid: random spans placed with the same occupancy rule the checker uses."""
    columns, count = rng.randint(1, 6), rng.randint(1, 6)
    taken = [[False] * columns for _ in range(count)]
    rows: list[dict[str, Any]] = []
    alphabet = ["a", "b", " ", "|", "\\", "{", "}", "\n", "é", "x y", "{{report_title}}", "**b**", "@", "-"]
    for r in range(count):
        row_cells: list[dict[str, Any]] = []
        c = 0
        while c < columns:
            if taken[r][c]:
                c += 1
                continue
            width = 1
            while c + width < columns and not taken[r][c + width] and rng.random() < 0.3:
                width += 1
            height = rng.randint(1, count - r) if rng.random() < 0.3 else 1
            height = min(height, count - r)
            if any(taken[rr][cc] for rr in range(r, r + height) for cc in range(c, c + width)):
                height = 1
            for rr in range(r, r + height):
                for cc in range(c, c + width):
                    taken[rr][cc] = True
            node: dict[str, Any] = {"text": "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))}
            if width > 1:
                node["colspan"] = width
            if height > 1:
                node["rowspan"] = height
            for key, options in (("align", ("left", "center", "right", "justify")), ("valign", ("top", "middle", "bottom")),
                                 ("fill", ("#112233", "white", "none", "primary")), ("color", ("#ffffff", "black"))):
                if rng.random() < 0.2:
                    node[key] = rng.choice(options)
            if rng.random() < 0.2:
                node["bold"] = rng.random() < 0.5
            row_cells.append(node)
            c += width
        item: dict[str, Any] = {"cells": row_cells}
        if rng.random() < 0.3:
            item["height"] = rng.choice([1, 2.5, 15])
            if rng.random() < 0.5:
                item["height_unit"] = rng.choice(["cm", "mm"])
                if item["height_unit"] == "mm":
                    item["height"] = rng.choice([5, 30, 100])
        if rng.random() < 0.2:
            item["fill"] = "#abcdef"
        rows.append(item)
    node = {"type": "grid", "columns": [({"width": rng.choice(["10%", "3 cm", "20 mm"])} if rng.random() < 0.3 else {}) for _ in range(columns)],
            "rows": rows}
    if rng.random() < 0.5:
        node["header_rows"] = rng.randint(0, 1) if count == 1 else 0
    if rng.random() < 0.5:
        node["borders"] = rng.choice(["all", "outer", "horizontal", "none"])
    if rng.random() < 0.3:
        node["bold"] = True
    return node


def test_any_valid_grid_survives_the_text_view_exactly():
    rng = random.Random(69)
    for _ in range(150):
        tree = doc(random_grid(rng))
        found = validate_tree(tree)
        if not found.ok:  # a random text may hold a placeholder the validator refuses; only valid trees must round trip
            continue
        written = format_tree(tree)
        parsed = parse_text(written)
        assert parsed.errors == [] and parsed.tree == tree, written


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("@grid\n| a |\n@end", "columns"),
        ("@grid columns=0\n@end", "columns"),
        ("@grid columns=21\n@end", "at most 20"),
        ("@grid columns=2 fill=red fill=blue\n@end", "written once"),
        ("@grid columns=2 shadow=1\n@end", "Unexpected"),
        ("@grid columns=2\n@col 3 fill=red\n@end", "no column 3"),
        ("@grid columns=2\n@col 1 fill=red\n@col 1 fill=blue\n@end", "already has"),
        ("@grid columns=2\n@col 1 width=big\n@end", "percentage|width"),
        ("@grid columns=2\n@row height=tall\n| a | b |\n@end", "height"),
        ("@grid columns=2\n@row\n@end", "no line of cells"),
        ("@grid columns=2\n@row\n@row\n| a | b |\n@end", "no line of cells"),
        ("@grid columns=2\nplain text\n@end", "Inside @grid"),
        ("@grid columns=2\n| a | b\n@end", "ends with a"),
        ("@grid columns=2\n| a \\q | b |\n@end", "backslash"),
        ("@grid columns=2\n| {colspan=x} a | b |\n@end", "whole number"),
        ("@grid columns=2\n| {colspan=2 | b |\n@end", "never closed"),
        ("@grid columns=2\n| {shadow=2} a | b |\n@end", "Unexpected"),
        ("@grid columns=2\n@heading nope\n@end", "Inside @grid"),
    ],
)
def test_a_mistake_in_a_grid_is_a_syntax_error_at_its_line(body, message):
    parsed = parse_text(f"@layout document\n\n{body}\n")
    assert parsed.tree is None and parsed.errors
    import re as _re
    assert _re.search(message, parsed.errors[0].message), parsed.errors


def test_a_merge_problem_is_reported_at_the_line_of_the_row():
    parsed = parse_text("@layout document\n\n@grid columns=2\n  | a | b |\n  | {colspan=3} c |\n@end\n")
    assert parsed.tree is not None and [e.line for e in parsed.errors] == [5]
    assert "past the edge" in parsed.errors[0].message


def test_a_pipe_line_outside_a_grid_is_ordinary_text():
    parsed = parse_text("@layout document\n\n| not | a table |\n")
    assert parsed.ok and parsed.tree["nodes"] == [{"type": "text", "text": "| not | a table |"}]


# ---- the drawings ------------------------------------------------------------------------------------------------


def markup(text: str, bold: bool) -> str:
    return html.escape(str(text))


def build_pdf(*flowables) -> bytes:
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm).build(list(flowables))
    return buffer.getvalue()


def test_pdf_spans_fills_and_the_header():
    table = pdf_grid(case_set(), USABLE * cm, 700, markup)
    spans = [(c[1], c[2]) for c in table._spanCmds]
    assert ((0, 0), (3, 0)) in spans and ((0, 2), (0, 3)) in spans
    assert [c for c in table._bkgrndcmds if c[1] == (0, 1) and c[2] == (0, 1)]
    assert table.repeatRows == 1
    assert build_pdf(table).startswith(b"%PDF")


def test_pdf_a_blank_row_keeps_its_minimum_height_and_a_wrapped_one_grows():
    table = pdf_grid(case_set(), USABLE * cm, 700, markup)
    assert table._rowHeights[4] == pytest.approx(2 * cm)
    assert table._rowHeights[2] > table._rowHeights[1]


def test_pdf_the_layout_can_turn_header_repeat_off():
    grid = case_set()
    table = pdf_grid(Grid(grid.widths, grid.rows, 1, False), USABLE * cm, 700, markup)
    assert table.repeatRows == 0


def test_pdf_a_long_table_keeps_rows_whole_and_repeats_the_header_over_pages():
    rows = [row(*[cell("Head")] * 4)] + [row(cell(f"r{i}"), cell("two\nlines"), cell(""), cell("")) for i in range(80)]
    table = pdf_grid(square(rows, header_rows=1), USABLE * cm, 700, markup)
    assert table.splitInRow == 0 and table.repeatRows == 1
    assert build_pdf(table).count(b"/Type /Page\n") >= 3


def test_pdf_a_row_taller_than_a_page_is_split_instead_of_failing_the_run():
    tall = cell("\n".join(f"line {i}" for i in range(150)))
    table = pdf_grid(square([row(*[cell("Head")] * 4), row(cell("Tall"), tall, cell(""), cell(""))], header_rows=1), USABLE * cm, 700, markup)
    assert table.splitInRow == 1
    assert build_pdf(table).startswith(b"%PDF")


def test_pdf_one_paragraph_longer_than_a_page_is_cut_so_the_run_does_not_fail():
    word = "word " * 400  # 2,000 characters in a narrow column is taller than a page
    narrow = Grid(["1 cm", None], [row(cell(word), cell("b"))])
    table = pdf_grid(narrow, USABLE * cm, 700, markup)
    assert len(table._cellvalues[0][0]) > 1
    assert build_pdf(table).startswith(b"%PDF")


def docx_of(grid: Grid):
    return docx_grid(DocxDocument(), grid, USABLE, _add_text)


def test_docx_merges_are_gridspan_and_vmerge_and_every_row_adds_up():
    table = docx_of(case_set())
    tcs = [list(tr.tc_lst) for tr in table._tbl.tr_lst]
    assert len(tcs[0]) == 1 and tcs[0][0].tcPr.find(qn("w:gridSpan")).get(qn("w:val")) == "4"
    assert tcs[2][0].tcPr.find(qn("w:vMerge")).get(qn("w:val")) == "restart"
    assert tcs[3][0].tcPr.find(qn("w:vMerge")) is not None
    columns = len(table._tbl.tblGrid.findall(qn("w:gridCol")))
    for tr in table._tbl.tr_lst:
        spans = [int(tc.tcPr.find(qn("w:gridSpan")).get(qn("w:val"))) if tc.tcPr.find(qn("w:gridSpan")) is not None else 1 for tc in tr.tc_lst]
        assert sum(spans) == columns


def test_docx_cell_style_row_height_header_and_borders():
    table = docx_of(case_set())
    rows = table._tbl.tr_lst
    first = rows[1].tc_lst[0]
    assert first.tcPr.find(qn("w:shd")).get(qn("w:fill")) == "000000" and first.tcPr.find(qn("w:vAlign")).get(qn("w:val")) == "top"
    assert rows[1].tc_lst[3].p_lst[0].pPr.find(qn("w:jc")).get(qn("w:val")) == "right"
    assert rows[2].tc_lst[1].p_lst[0].pPr.find(qn("w:jc")).get(qn("w:val")) == "both"
    assert rows[2].tc_lst[0].tcPr.find(qn("w:vAlign")).get(qn("w:val")) == "center"
    height = rows[4].trPr.find(qn("w:trHeight"))
    assert (height.get(qn("w:hRule")), int(height.get(qn("w:val")))) == ("atLeast", round(2 * 567))
    assert all(tr.trPr.find(qn("w:cantSplit")) is not None for tr in rows)
    assert rows[0].trPr.find(qn("w:tblHeader")) is not None and rows[1].trPr.find(qn("w:tblHeader")) is None
    run = rows[1].tc_lst[0].p_lst[0].r_lst[0]
    assert run.rPr.find(qn("w:color")).get(qn("w:val")) == "FFFFFF" and run.rPr.find(qn("w:b")) is not None
    borders = table._tbl.tblPr.find(qn("w:tblBorders"))
    edges = ("top", "left", "bottom", "right", "insideH", "insideV")
    assert {b.tag.split("}")[1]: b.get(qn("w:val")) for b in borders} == {name: "single" for name in edges}


@pytest.mark.parametrize(
    ("borders", "drawn"), [("outer", {"top", "left", "bottom", "right"}), ("horizontal", {"top", "bottom", "insideH"}), ("none", set())],
)
def test_docx_border_choice(borders, drawn):
    table = docx_of(square([row(*[cell("a")] * 4)], borders=borders))
    found = {b.tag.split("}")[1] for b in table._tbl.tblPr.find(qn("w:tblBorders")) if b.get(qn("w:val")) == "single"}
    assert found == drawn


def test_docx_a_vertical_merge_group_is_kept_on_one_page():
    table = docx_of(case_set())
    first = [p for tc in table._tbl.tr_lst[2].tc_lst for p in tc.p_lst]
    last = [p for tc in table._tbl.tr_lst[3].tc_lst for p in tc.p_lst]
    assert all(p.pPr.find(qn("w:keepNext")) is not None for p in first)
    assert all(p.pPr is None or p.pPr.find(qn("w:keepNext")) is None for p in last)


def test_docx_text_is_text_not_markup_and_paragraphs_stay_separate():
    table = docx_of(square([row(cell("<w:p/>&amp; {{x}}\nsecond"), cell("b"), cell("c"), cell("d"))]))
    paragraphs = table._tbl.tr_lst[0].tc_lst[0].p_lst
    assert [p.r_lst[0].t_lst[0].text for p in paragraphs] == ["<w:p/>&amp; {{x}}", "second"]


def odt_tree(grid: Grid, inline=xml_text):
    styles: list[str] = []
    markup_ = odt_grid(grid, "G1", USABLE, inline, styles)
    return etree.fromstring(f"<root {ODF_NS}>{''.join(styles)}{markup_}</root>")


def test_odt_merges_use_spans_and_covered_cells():
    root = odt_tree(case_set())
    rows = root.findall(".//table:table-row", NS)
    first = rows[0].findall("table:table-cell", NS)
    assert len(first) == 1 and first[0].get(f"{{{NS['table']}}}number-columns-spanned") == "4"
    assert len(rows[0].findall("table:covered-table-cell", NS)) == 3
    assert rows[2].findall("table:table-cell", NS)[0].get(f"{{{NS['table']}}}number-rows-spanned") == "2"
    assert len(rows[3].findall("table:covered-table-cell", NS)) == 1
    for r in rows:
        assert len(r.findall("table:table-cell", NS)) + len(r.findall("table:covered-table-cell", NS)) == 4


def test_odt_row_height_header_group_cell_style_and_shared_styles():
    root = odt_tree(case_set())
    assert len(root.findall(".//table:table-header-rows/table:table-row", NS)) == 1
    rows = {s.get(f"{{{NS['style']}}}name"): s.find("style:table-row-properties", NS) for s in root.findall("style:style", NS)
            if s.get(f"{{{NS['style']}}}family") == "table-row"}
    assert rows["G1_r4"].get(f"{{{NS['style']}}}min-row-height") == "2.000cm"
    assert all(p.get(f"{{{NS['fo']}}}keep-together") == "always" for p in rows.values())
    cell_style = root.findall(".//table:table-row", NS)[1].find("table:table-cell", NS).get(f"{{{NS['table']}}}style-name")
    props = next(s for s in root.findall("style:style", NS) if s.get(f"{{{NS['style']}}}name") == cell_style).find("style:table-cell-properties", NS)
    assert props.get(f"{{{NS['fo']}}}background-color") == "#000000" and props.get(f"{{{NS['style']}}}vertical-align") == "top"
    cell_styles = [s for s in root.findall("style:style", NS) if s.get(f"{{{NS['style']}}}family") == "table-cell"]
    assert len(cell_styles) < 16  # cells that look alike share a style


def test_odt_borders_follow_the_border_choice():
    root = odt_tree(square([row(*[cell("a")] * 4)] * 2, borders="outer"))
    styles = [s.find("style:table-cell-properties", NS) for s in root.findall("style:style", NS) if s.get(f"{{{NS['style']}}}family") == "table-cell"]
    edges = [{side: p.get(f"{{{NS['fo']}}}border-{side}") for side in ("top", "right", "bottom", "left")} for p in styles]
    assert any(e["top"] != "none" and e["bottom"] == "none" for e in edges)  # an edge cell draws only its outside edges
    assert any(e["bottom"] != "none" and e["top"] == "none" for e in edges)


def test_odt_text_is_escaped_keeps_line_breaks_and_paragraphs():
    root = odt_tree(square([row(cell("a <b> & c\nsecond"), cell("b"), cell("c"), cell("d"))]))
    paragraphs = root.findall(".//table:table-cell/text:p", NS)[:2]
    assert ["".join(p.itertext()) for p in paragraphs] == ["a <b> & c", "second"]


def html_root(grid: Grid):
    return lxml_html.fragment_fromstring(html_grid(grid, html.escape), create_parent="root")


def test_html_spans_omit_covered_cells_and_alignment_is_a_class():
    root = html_root(case_set())
    rows = root.findall(".//tr")
    assert [len(r.findall("td")) for r in rows] == [1, 4, 4, 3, 4]
    assert rows[0].find("td").get("colspan") == "4" and rows[2].find("td").get("rowspan") == "2"
    assert "a-right" in rows[1].findall("td")[3].get("class") and "v-middle" in rows[2].find("td").get("class")
    assert root.find(".//thead/tr") is not None and "height:2.000cm" in rows[4].get("style")
    assert [round(float(c.get("style").split(":")[1].rstrip("%;"))) for c in root.findall(".//col")] == [20, 30, 20, 30]


def test_html_style_only_ever_holds_validated_colours_and_text_is_escaped():
    out = html_grid(square([row(cell('<script>alert(1)</script>"x', fill="#ABCDEF"), cell("b"), cell("c"), cell("d"))]), html.escape)
    assert "<script>" not in out and "&lt;script&gt;" in out and 'style="background-color:#abcdef"' in out
    bad = cell("a", fill='#fff" onload="x', color="red;x:y")
    hostile = html_grid(square([row(bad, cell("b"), cell("c"), cell("d"))], border_color="#zzz"), html.escape)
    assert "onload" not in hostile and "red" not in hostile and "--grid-line:#999999" in hostile


def test_html_border_edges_are_classes():
    root = html_root(square([row(*[cell("a")] * 4)] * 2, borders="horizontal"))
    for td in root.findall(".//td"):
        classes = td.get("class").split()
        assert "bt" in classes and "bb" in classes and "bl" not in classes and "br" not in classes


def test_the_grid_is_in_every_rendered_document():
    document = ReportDocument(title="Grid", blocks=[Paragraph("before"), case_set(), Paragraph("after")])
    assert render_pdf_document(document).startswith(b"%PDF")
    word = DocxDocument(io.BytesIO(render_docx_document(document)))
    assert len(word.tables) == 1 and word.tables[0].cell(0, 0).text == "Document details"
    content = etree.fromstring(zipfile.ZipFile(io.BytesIO(render_odt_document(document))).read("content.xml"))
    assert len(content.findall(".//table:table", NS)) == 1
    assert b'<table class="grid"' in render_html_document(document)


def test_styled_text_and_links_in_a_cell_are_drawn_by_the_renderers_own_text_writer():
    value = MathText(["see ", Styled("this", bold=True), " and ", Styled("there", href="https://example.com/x")])
    document = ReportDocument(title="Grid", blocks=[Grid(["100%"], [GridRow([GridCell((value,))])])])
    page = render_html_document(document).decode()
    assert "<strong>this</strong>" in page and 'href="https://example.com/x"' in page
    content = zipfile.ZipFile(io.BytesIO(render_odt_document(document))).read("content.xml").decode()
    assert "https://example.com/x" in content


# ---- the evaluator -----------------------------------------------------------------------------------------------


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Grid Eval Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def run(db, world: World, project: dict, tree: dict[str, Any], **kwargs: Any):
    row_ = db.get(Project, uuid.UUID(project["id"]))
    org = db.get(Organization, uuid.UUID(world.org["id"]))
    resolver = ArtefactResolver(db, row_, world.user_id, include_related=True)
    ctx = ReportContext(module_key="reporting", organization=org, projects=[row_], root_project=row_)
    return evaluate_layout(db, resolver, ctx, tree, title="Report", **kwargs)


def grids_of(result) -> list[Grid]:
    return [b for b in result.document.blocks if isinstance(b, Grid)]


def test_the_style_cascade_is_cell_then_row_then_column_then_grid(world, db):
    project = world.project("Cascade P")
    node = {
        "type": "grid", "columns": [{"fill": "#0000ff"}, {}, {"align": "right"}], "fill": "#111111", "align": "center",
        "rows": [
            {"fill": "#ff0000", "cells": [{"text": "a"}, {"text": "b", "fill": "#00ff00"}, {"text": "c"}]},
            {"cells": [{"text": "d"}, {"text": "e"}, {"text": "f", "align": "left"}]},
        ],
    }
    (grid,) = grids_of(run(db, world, project, doc(node)))
    assert [[c.fill for c in r.cells] for r in grid.rows] == [["#ff0000", "#00ff00", "#ff0000"], ["#0000ff", "#111111", "#111111"]]
    assert [[c.align for c in r.cells] for r in grid.rows] == [["center", "center", "right"], ["center", "center", "left"]]


def test_a_column_style_follows_the_cell_that_starts_there_after_a_merge(world, db):
    project = world.project("Merge P")
    node = {"type": "grid", "columns": [{}, {"bold": True}, {}],
            "rows": [{"cells": [{"text": "a", "colspan": 2}, {"text": "b"}]}, {"cells": [{"text": "c"}, {"text": "d"}, {"text": "e"}]}]}
    (grid,) = grids_of(run(db, world, project, doc(node)))
    assert [c.bold for c in grid.rows[0].cells] == [False, False] and [c.bold for c in grid.rows[1].cells] == [False, True, False]


def test_colour_words_become_hex_and_the_scheme_and_branding_colour_resolve(world, db):
    project = world.project("Colour P")
    tree = {**doc({"type": "grid", "columns": [{}, {}], "border_color": "brand",
                   "rows": [{"cells": [{"text": "a", "fill": "brand"}, {"text": "b", "fill": "accent", "color": "white"}]}]}),
            "palette": [{"name": "brand", "colour": "#1f4e79"}]}
    result = run(db, world, project, tree)
    (grid,) = grids_of(result)
    assert grid.rows[0].cells[0].fill == "#1f4e79" and grid.border_color == "#1f4e79"
    assert grid.rows[0].cells[1].fill.startswith("#") and len(grid.rows[0].cells[1].fill) == 7 and grid.rows[0].cells[1].color == "#ffffff"
    assert result.colours == {"brand": "#1f4e79"}


def test_unreadable_colours_make_one_warning_not_an_error(world, db):
    project = world.project("Contrast P")
    node = grid_node([cells("a", fill="#777777", color="#888888"), cells("b", fill="#000000")], columns=1)
    result = run(db, world, project, doc(node))
    message = "2 cells of a custom table have text and fill colours that are hard to read together."
    assert [w for w in result.warnings if "hard to read" in w] == [message]
    fine = run(db, world, project, doc(grid_node([cells("a", fill="#000000", color="#ffffff")], columns=1)))
    assert not [w for w in fine.warnings if "hard to read" in w]


def test_cell_text_is_markdown_with_placeholders_and_a_blank_cell_stays_blank(world, db):
    project = world.project("Text P")
    node = grid_node([{"cells": [{"text": "**Bold** in {{report_title}}\nnext line"}, {"text": ""}, {"text": "- one\n- two"}]}], columns=3)
    (grid,) = grids_of(run(db, world, project, doc(node)))
    first, blank, items = grid.rows[0].cells
    assert [str(p) for p in first.paragraphs] == ["Bold in Report", "next line"] and isinstance(first.paragraphs[0], MathText)
    assert blank.paragraphs == ("",)
    assert [str(p) for p in items.paragraphs] == ["• one", "• two"]


def test_a_grid_in_a_loop_fills_the_record_and_is_drawn_once_per_record(world, db):
    project = world.project("Loop P")
    for name in ("alpha", "beta"):
        resp = world.client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "description": "", "component_id": project["component_id"], "category_id": project["category_id"]},
            headers=auth_headers(world.token),
        )
        assert resp.status_code == 201, resp.text
    node = {"type": "each", "source": {"record_type": REQ, "sort": [{"field": "title"}]},
            "children": [grid_node([cells("{{record.title}}", "x")], columns=2)]}
    found = grids_of(run(db, world, project, doc(node)))
    assert [str(g.rows[0].cells[0].paragraphs[0]) for g in found] == ["alpha", "beta"]


def test_header_rows_repeat_unless_the_layout_says_not_to(world, db):
    project = world.project("Header P")
    node = grid_node([cells("h"), cells("b")], columns=1, header_rows=1)
    (repeating,) = grids_of(run(db, world, project, doc(node)))
    (plain,) = grids_of(run(db, world, project, {**doc(node), "repeat_table_header": False}))
    assert (repeating.header_rows, repeating.repeat_header, plain.header_rows, plain.repeat_header) == (1, True, 1, False)


def test_a_row_height_in_millimetres_is_converted_to_centimetres(world, db):
    project = world.project("Height P")
    node = grid_node([{"height": 25, "height_unit": "mm", "cells": [{"text": "a"}]}, {"height": 2, "cells": [{"text": "b"}]}, cells("c")], columns=1)
    (grid,) = grids_of(run(db, world, project, doc(node)))
    assert [r.height_cm for r in grid.rows] == [2.5, 2, None]
