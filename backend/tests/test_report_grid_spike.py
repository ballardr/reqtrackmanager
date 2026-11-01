"""Tests for the custom-table (grid) spike: the span checks and style cascade, and the four drawings read back (PDF, Word,
ODT, HTML) for merged cells, per-cell alignment and colour, row heights, header rows, and safe values. No database.

The same case set was also opened in LibreOffice (Word and ODT) and the PDF rendered; see the decisions log's custom tables spike."""

from __future__ import annotations

import io
import zipfile

import pytest
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from lxml import etree
from lxml import html as lxml_html
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate

from app.services import report_odt
from app.services.report_model import PageStyle, ReportDocument
from tests.report_grid_spike import (
    Grid,
    GridCell,
    GridError,
    GridRow,
    draw_docx,
    draw_html,
    draw_odt,
    draw_pdf,
    low_contrast,
    place,
    the_case_set,
)

C, R = GridCell, GridRow
USABLE = PageStyle().usable_width_cm
ODF_NS = (
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
)
NS = {"table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0", "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
      "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0", "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"}


def square(rows: list[GridRow], **kwargs) -> Grid:
    return Grid(widths_cm=[4, 4, 4, 4], rows=rows, **kwargs)


# ---- spans, checks and the cascade -------------------------------------------------------------------------------


def test_the_case_set_places_every_position_once():
    placed, owner = place(the_case_set())
    assert len(placed) == 16  # 20 positions: the title merge covers 3 more, the label's merge covers 1
    assert owner[3][0] == (2, 0)  # the row-spanning label covers the row below it
    assert owner[0] == [(0, 0)] * 4


def test_column_style_reaches_every_cell_and_a_cell_overrides_it():
    placed = {(p.row, p.col): p for p in place(the_case_set())[0]}
    assert (placed[(1, 0)].fill, placed[(1, 0)].color, placed[(1, 0)].bold) == ("#000000", "#ffffff", True)
    assert placed[(1, 2)].fill == "#000000"  # the third column, one setting
    assert placed[(1, 1)].fill is None
    assert placed[(0, 0)].fill == "#1f4e79"  # the title cell's own fill beats the column's
    assert placed[(1, 3)].align == "right" and placed[(3, 3)].valign == "middle"


def test_a_row_style_sits_between_the_column_and_the_cell():
    grid = square([R([C("a"), C("b", fill="#00ff00"), C("c"), C("d")], style=C(fill="#ff0000"))], columns=[C(fill="#0000ff")] * 4,
                  default=C(fill="#111111"))
    fills = [p.fill for p in place(grid)[0]]
    assert fills == ["#ff0000", "#00ff00", "#ff0000", "#ff0000"]


@pytest.mark.parametrize(
    ("rows", "kwargs", "message"),
    [
        ([R([C("a", colspan=3), C("b", colspan=2)])], {}, "row 1, cell 4"),
        ([R([C("a"), C("b", rowspan=2), C("c"), C("d")]), R([C("x", colspan=2), C("y"), C("z")])], {}, "overlaps another"),
        ([R([C("a", rowspan=2), C("b"), C("c"), C("d")])], {}, "past the grid"),
        ([R([C("a"), C("b")])], {}, "fewer cells"),
        ([R([C("a"), C("b"), C("c"), C("d"), C("e")])], {}, "more cells"),
        ([R([C("a", colspan=0), C("b"), C("c"), C("d")])], {}, "below 1"),
        ([R([C("a", rowspan=2), C("b"), C("c"), C("d")]), R([C("b"), C("c"), C("d")])], {"header_rows": 1}, "header rows"),
        ([R([C("a", align="diagonal"), C("b"), C("c"), C("d")])], {}, "align must be one of"),
        ([R([C("a", fill="red"), C("b"), C("c"), C("d")])], {}, "not a colour"),
        ([R([C("a", color="#fff;background:url(x)"), C("b"), C("c"), C("d")])], {}, "not a colour"),
    ],
)
def test_a_bad_grid_is_refused_naming_the_cell(rows, kwargs, message):
    with pytest.raises(GridError, match=message):
        place(square(rows, **kwargs))


def test_low_contrast_is_flagged_but_not_refused():
    placed = place(square([R([C("a", fill="#777777", color="#888888"), C("b", fill="#000000", color="#ffffff"), C("c"), C("d")])]))[0]
    assert [low_contrast(p) for p in placed] == [True, False, False, False]


# ---- PDF ----------------------------------------------------------------------------------------------------------


def build_pdf(*flowables) -> bytes:
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm).build(list(flowables))
    return buffer.getvalue()


def test_pdf_spans_fills_and_alignment():
    table = draw_pdf(the_case_set())
    commands = table._bkgrndcmds
    assert ((0, 0), (3, 0)) in [(c[1], c[2]) for c in table._spanCmds]  # the title cell across four columns
    assert ((0, 2), (0, 3)) in [(c[1], c[2]) for c in table._spanCmds]  # the label down two rows
    assert [c for c in commands if c[0] == "BACKGROUND" and c[1] == (0, 1) and c[2] == (0, 1)]
    assert build_pdf(table).startswith(b"%PDF")


def test_pdf_blank_row_keeps_its_minimum_height_and_a_taller_one_grows():
    table = draw_pdf(the_case_set())
    assert table._rowHeights[4] == pytest.approx(2 * cm)
    assert table._rowHeights[2] > table._rowHeights[1]  # the wrapped justified note makes its row taller


def test_pdf_rows_stay_whole_and_the_header_repeats_across_pages():
    rows = [R([C("Head"), C("h"), C("h"), C("h")])] + [R([C(f"r{i}"), C("two\nlines"), C(""), C("")]) for i in range(80)]
    table = draw_pdf(square(rows, header_rows=1))
    assert table.splitInRow == 0 and table.repeatRows == 1
    assert build_pdf(table).count(b"/Type /Page\n") >= 3


def test_pdf_row_taller_than_a_page_is_split_instead_of_failing_the_run():
    rows = [R([C("Head"), C("h"), C("h"), C("h")]), R([C("Tall"), C("\n".join(f"line {i}" for i in range(150))), C(""), C("")])]
    table = draw_pdf(square(rows, header_rows=1), frame_height=700)
    assert table.splitInRow == 1
    assert build_pdf(table).startswith(b"%PDF")  # without the split, ReportLab raises LayoutError


# ---- Word ---------------------------------------------------------------------------------------------------------


def docx_of(grid: Grid):
    document = DocxDocument()
    return draw_docx(document, grid, USABLE)


def test_docx_merges_are_gridspan_and_vmerge_and_the_structure_is_consistent():
    from tests.report_grid_spike import docx_problems

    table = docx_of(the_case_set())
    tcs = [list(tr.tc_lst) for tr in table._tbl.tr_lst]
    title = tcs[0][0].tcPr
    assert len(tcs[0]) == 1 and title.find(qn("w:gridSpan")).get(qn("w:val")) == "4"
    assert tcs[2][0].tcPr.find(qn("w:vMerge")).get(qn("w:val")) == "restart"
    assert tcs[3][0].tcPr.find(qn("w:vMerge")) is not None  # the continuation, present in the row below
    assert docx_problems(table) == []


def test_docx_cell_style_row_height_and_header():
    table = docx_of(the_case_set())
    rows = table._tbl.tr_lst
    cell = rows[1].tc_lst[0]
    assert cell.tcPr.find(qn("w:shd")).get(qn("w:fill")) == "000000"
    assert cell.tcPr.find(qn("w:vAlign")).get(qn("w:val")) == "top"
    assert rows[1].tc_lst[3].p_lst[0].pPr.find(qn("w:jc")).get(qn("w:val")) == "right"
    assert rows[2].tc_lst[1].p_lst[0].pPr.find(qn("w:jc")).get(qn("w:val")) == "both"  # justified
    assert rows[2].tc_lst[0].tcPr.find(qn("w:vAlign")).get(qn("w:val")) == "center"  # middle
    height = rows[4].trPr.find(qn("w:trHeight"))
    assert (height.get(qn("w:hRule")), int(height.get(qn("w:val")))) == ("atLeast", round(2 * 567))
    assert all(tr.trPr.find(qn("w:cantSplit")) is not None for tr in rows)
    assert rows[0].trPr.find(qn("w:tblHeader")) is not None and rows[1].trPr.find(qn("w:tblHeader")) is None
    assert rows[1].tc_lst[0].p_lst[0].r_lst[0].rPr.find(qn("w:color")).get(qn("w:val")) == "FFFFFF"


def test_docx_vertical_merge_group_is_kept_on_one_page():
    table = docx_of(the_case_set())
    first_row_paragraphs = [p for tc in table._tbl.tr_lst[2].tc_lst for p in tc.p_lst]
    last_row_paragraphs = [p for tc in table._tbl.tr_lst[3].tc_lst for p in tc.p_lst]
    assert all(p.pPr.find(qn("w:keepNext")) is not None for p in first_row_paragraphs)
    assert all(p.pPr is None or p.pPr.find(qn("w:keepNext")) is None for p in last_row_paragraphs)


def test_docx_structure_check_catches_a_row_that_does_not_add_up():
    from tests.report_grid_spike import docx_problems

    table = docx_of(the_case_set())
    row = table._tbl.tr_lst[1]
    row.remove(row.tc_lst[3])
    assert any("add up" in problem for problem in docx_problems(table))


def test_docx_text_is_text_not_markup():
    table = docx_of(square([R([C("<w:p/>&amp; {{x}}"), C("b"), C("c"), C("d")])]))
    assert table._tbl.tr_lst[0].tc_lst[0].p_lst[0].r_lst[0].t_lst[0].text == "<w:p/>&amp; {{x}}"
    assert len(table._tbl.tr_lst[0].tc_lst[0].p_lst) == 1


# ---- ODT ----------------------------------------------------------------------------------------------------------


def odt_tree(grid: Grid):
    styles: list[str] = []
    markup = draw_odt(grid, USABLE, "G1", styles)
    root = etree.fromstring(f"<root {ODF_NS}>{''.join(styles)}{markup}</root>")
    return root


def test_odt_merges_use_spans_and_covered_cells():
    root = odt_tree(the_case_set())
    rows = root.findall(".//table:table-row", NS)
    first = rows[0].findall("table:table-cell", NS)
    assert len(first) == 1 and first[0].get(f"{{{NS['table']}}}number-columns-spanned") == "4"
    assert len(rows[0].findall("table:covered-table-cell", NS)) == 3
    label = rows[2].findall("table:table-cell", NS)[0]
    assert label.get(f"{{{NS['table']}}}number-rows-spanned") == "2"
    assert len(rows[3].findall("table:covered-table-cell", NS)) == 1  # the covered position under the label
    for row in rows:  # every row accounts for all four columns
        assert len(row) == 4 or len(row.findall("table:table-cell", NS)) + len(row.findall("table:covered-table-cell", NS)) == 4


def test_odt_row_height_header_group_and_cell_style():
    root = odt_tree(the_case_set())
    assert len(root.findall(".//table:table-header-rows/table:table-row", NS)) == 1
    heights = {s.get(f"{{{NS['style']}}}name"): s.find("style:table-row-properties", NS) for s in root.findall("style:style", NS)
               if s.get(f"{{{NS['style']}}}family") == "table-row"}
    assert heights["G1_r4"].get(f"{{{NS['style']}}}min-row-height") == "2.000cm"
    assert all(p.get(f"{{{NS['fo']}}}keep-together") == "always" for p in heights.values())
    cell = next(s for s in root.findall("style:style", NS) if s.get(f"{{{NS['style']}}}name") == "G1_1_0")
    props = cell.find("style:table-cell-properties", NS)
    assert props.get(f"{{{NS['fo']}}}background-color") == "#000000" and props.get(f"{{{NS['style']}}}vertical-align") == "top"


def test_odt_text_is_escaped_and_keeps_line_breaks():
    root = odt_tree(square([R([C("a <b> & c\nsecond"), C("b"), C("c"), C("d")])]))
    paragraph = root.find(".//table:table-cell/text:p", NS)
    assert "".join(paragraph.itertext()) == "a <b> & csecond"
    assert paragraph.find("text:line-break", NS) is not None


def test_odt_real_renderer_accepts_the_grid_and_zips(monkeypatch):
    class Body(report_odt._Body):
        def block(self, block):
            if isinstance(block, Grid):
                self.chunks.append(draw_odt(block, self.usable_cm, "Grid1", self.styles))
            else:
                super().block(block)

    monkeypatch.setattr(report_odt, "_Body", Body)
    data = report_odt.render_odt_document(ReportDocument(title="Grid", blocks=[the_case_set()]))
    content = etree.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("content.xml"))  # well-formed
    assert content.findall(".//table:table", NS)


# ---- HTML ---------------------------------------------------------------------------------------------------------


def test_html_spans_omit_covered_cells_and_alignment_is_a_class():
    markup = draw_html(the_case_set(), USABLE)
    root = lxml_html.fragment_fromstring(markup, create_parent="root")
    rows = root.findall(".//tr")
    assert [len(r.findall("td")) for r in rows] == [1, 4, 4, 3, 4]
    assert rows[0].find("td").get("colspan") == "4" and rows[2].find("td").get("rowspan") == "2"
    assert "a-right" in rows[1].findall("td")[3].get("class") and "v-middle" in rows[2].find("td").get("class")
    assert root.find(".//thead/tr") is not None and "height:2.000cm" in rows[4].get("style")


def test_html_style_only_ever_holds_validated_values_and_text_is_escaped():
    markup = draw_html(square([R([C('<script>alert(1)</script>"x', fill="#ABCDEF"), C("b"), C("c"), C("d")])]), USABLE)
    assert "<script>" not in markup and "&lt;script&gt;" in markup
    assert 'style="background-color:#abcdef"' in markup
    with pytest.raises(GridError):
        draw_html(square([R([C("a", fill='#fff" onload="x'), C("b"), C("c"), C("d")])]), USABLE)
