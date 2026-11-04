"""Tests for the page-bottom block: tree validation, the text view, the block form and the four renderers (PDF, Word,
ODT, HTML). No database."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

import pytest
from docx import Document as DocxDocument
from docx.oxml.ns import qn

from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import BLOCK_SPECS, FAMILY_DOCUMENT, empty_tree, validate_tree
from app.services.report_model import (
    BottomEnd,
    BottomStart,
    Heading,
    Margins,
    PageBreak,
    Paragraph,
    ReportDocument,
    RunningBand,
    Table,
)
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from tests.test_report_spacer import pdf_positions

A4_BOTTOM_MARGIN_PT = 1.5 * 72 / 2.54  # the default margin


def tree(*nodes: dict[str, Any], family: str = "document") -> dict[str, Any]:
    return {**empty_tree(family), "nodes": list(nodes)}


def problems(*nodes: dict[str, Any], family: str = "document") -> dict[str, str]:
    return {e.path: e.message for e in validate_tree(tree(*nodes, family=family)).errors}


def bottom(*children: dict[str, Any]) -> dict[str, Any]:
    return {"type": "bottom", "children": list(children)}


TEXT = {"type": "text", "text": "Signed"}


# ---- the tree ---------------------------------------------------------------------------------------------------


def test_a_bottom_block_holds_ordinary_blocks_and_may_sit_inside_a_section_or_a_loop():
    assert BLOCK_SPECS["bottom"].families == (FAMILY_DOCUMENT,)
    assert problems(bottom(TEXT, {"type": "spacer", "height": 1})) == {}
    loop = {"type": "group", "source": {"record_type": "requirement"}, "by": "status", "as": "g", "children": [bottom(TEXT)]}
    assert problems(loop) == {}


@pytest.mark.parametrize(
    ("child", "word"),
    [({"type": "page_break"}, "A page break"), ({"type": "bottom", "children": []}, "cannot be inside another"),
     ({"type": "widget", "key": "x"}, "A widget"), ({"type": "section", "page_style": "x", "children": []}, "A section")],
)
def test_a_bottom_block_refuses_a_block_that_starts_a_page_or_another_bottom_block(child, word):
    found = problems(bottom(child))
    assert any(word in message for message in found.values()), found


def test_a_table_layout_refuses_it_and_unknown_keys_are_errors():
    assert problems(bottom(TEXT), family="table")
    assert "nodes[0].colour" in problems({**bottom(TEXT), "colour": "red"})


def test_the_block_form_is_served_from_the_schema():
    schema = BLOCK_SPECS["bottom"].schema
    assert schema.label == "At page bottom" and [c.key for c in schema.containers] == ["children"]
    assert "browser preview" in schema.description


# ---- the text view ----------------------------------------------------------------------------------------------


def test_the_text_view_round_trips_a_bottom_block_with_its_contents():
    source = tree({"type": "heading", "text": "Head"}, bottom(TEXT, {"type": "spacer", "height": 1}))
    text = format_tree(source)
    assert "@bottom" in text and "@end" in text
    result = parse_text(text)
    assert result.errors == [] and result.tree == source


def test_an_unclosed_bottom_block_is_a_text_error():
    assert parse_text("@bottom\nSome text.\n").errors


# ---- PDF --------------------------------------------------------------------------------------------------------


def document(*blocks: Any) -> ReportDocument:
    return ReportDocument(title="Bottom", blocks=list(blocks))


def test_pdf_puts_the_run_at_the_foot_of_the_page_and_what_follows_on_a_new_page():
    positions = pdf_positions(render_pdf_document(document(
        Paragraph("above"), BottomStart(), Paragraph("signed"), BottomEnd(), Paragraph("after"),
    )))
    assert positions["above"] > 700  # the top of the page
    assert positions["signed"] < A4_BOTTOM_MARGIN_PT + 25  # one line above the bottom margin
    pdf = render_pdf_document(document(Paragraph("above"), BottomStart(), Paragraph("signed"), BottomEnd(), Paragraph("after")))
    assert pdf.count(b"/Type /Page\n") == 2


def test_pdf_keeps_a_table_at_the_bottom_however_long_the_header_before_it_is():
    short = pdf_positions(render_pdf_document(document(
        Paragraph("top"), BottomStart(), Table(columns=["A"], rows=[["cell"]]), BottomEnd(),
    )))
    long = pdf_positions(render_pdf_document(document(
        Heading("Heading", 1), *[Paragraph(f"line {n} " * 12) for n in range(30)],
        BottomStart(), Table(columns=["A"], rows=[["cell"]]), BottomEnd(),
    )))
    assert long["cell"] == pytest.approx(short["cell"], abs=0.5)


def test_pdf_moves_the_run_to_a_new_page_when_it_does_not_fit_in_the_room_left():
    filler = [Paragraph("word " * 30) for _ in range(60)]
    pdf = render_pdf_document(document(*filler, BottomStart(), Paragraph("signed"), BottomEnd()))
    positions = pdf_positions(pdf)
    assert positions["signed"] < A4_BOTTOM_MARGIN_PT + 25 and pdf.count(b"/Type /Page\n") >= 2


def test_pdf_lets_a_run_too_tall_for_a_page_flow_as_ordinary_content():
    rows = [[f"row {n}"] for n in range(120)]
    pdf = render_pdf_document(document(Paragraph("above"), BottomStart(), Table(columns=["A"], rows=rows), BottomEnd(), Paragraph("after")))
    positions = pdf_positions(pdf)
    assert "above" in positions and pdf.count(b"/Type /Page\n") >= 2


def test_pdf_ignores_an_empty_run():
    pdf = render_pdf_document(document(Paragraph("above"), BottomStart(), BottomEnd(), Paragraph("after")))
    assert pdf.count(b"/Type /Page\n") == 1


# ---- Word -------------------------------------------------------------------------------------------------------


def word_of(*blocks: Any):
    return DocxDocument(io.BytesIO(render_docx_document(document(*blocks))))


def test_docx_moves_the_run_into_a_borderless_floating_table_anchored_to_the_bottom_of_the_page():
    word = word_of(Paragraph("above"), BottomStart(), Paragraph("signed"), Table(columns=["A"], rows=[["cell"]]), BottomEnd(), Paragraph("after"))
    outer = [t for t in word.tables if t._tbl.tblPr.find(qn("w:tblpPr")) is not None]
    assert len(outer) == 1
    position = outer[0]._tbl.tblPr.find(qn("w:tblpPr"))
    assert position.get(qn("w:tblpYSpec")) == "bottom" and position.get(qn("w:vertAnchor")) == "page"
    cell = outer[0].cell(0, 0)
    assert [p.text for p in cell.paragraphs if p.text] == ["signed"] and len(cell.tables) == 1  # text and a nested table
    assert [p.text for p in word.paragraphs if p.text] == ["Bottom", "above", "after"]  # the text before and after stay in the flow


def test_docx_ends_the_cell_with_a_paragraph_and_starts_what_follows_on_a_new_page():
    word = word_of(BottomStart(), Table(columns=["A"], rows=[["cell"]]), BottomEnd(), Paragraph("after"))
    cell = next(t for t in word.tables if t._tbl.tblPr.find(qn("w:tblpPr")) is not None).cell(0, 0)
    assert cell._tc[-1].tag == qn("w:p")  # a table cell must end with a paragraph
    breaks = word.element.body.xpath('.//w:br[@w:type="page"]')
    assert len(breaks) == 1


def clearance_twips(word) -> int:
    """The bottom margin of the floating table's cell (twentieths of a point): its distance from the sheet's edge."""
    outer = next(t for t in word.tables if t._tbl.tblPr.find(qn("w:tblpPr")) is not None)
    return int(outer.cell(0, 0)._tc.tcPr.find(qn("w:tcMar")).find(qn("w:bottom")).get(qn("w:w")))


def test_docx_ends_the_run_above_a_page_number_footer_that_reaches_above_the_margin():
    # The plain footer sits 1.27 cm up and is about 0.7 cm tall, in a 1.5 cm margin: the run ends 0.3 cm above its top.
    word = word_of(Paragraph("above"), BottomStart(), Paragraph("signed"), BottomEnd())
    assert clearance_twips(word) == pytest.approx((1.27 + 0.7 + 0.3) * 567, abs=6)


def test_docx_ends_the_run_at_the_bottom_margin_when_the_footer_stays_inside_it_or_there_is_none():
    def offset(**keys):
        word = DocxDocument(io.BytesIO(render_docx_document(ReportDocument(
            title="x", blocks=[Paragraph("above"), BottomStart(), Paragraph("signed"), BottomEnd()], **keys,
        ))))
        return clearance_twips(word)

    assert offset(margins=Margins(bottom=2.5), footer=RunningBand(centre=("Page",))) == pytest.approx(2.5 * 567, abs=6)
    assert offset(margins=Margins(bottom=2.5), footer=RunningBand()) == pytest.approx(2.5 * 567, abs=6)


def test_docx_drops_the_blank_spacer_a_table_leaves_so_no_blank_space_sits_under_the_run():
    word = word_of(BottomStart(), Table(columns=["A"], rows=[["cell"]]), BottomEnd())
    cell = next(t for t in word.tables if t._tbl.tblPr.find(qn("w:tblpPr")) is not None).cell(0, 0)
    assert [child.tag for child in cell._tc][-2:] == [qn("w:tbl"), qn("w:p")]  # the table, then only the closing paragraph
    spacing = cell._tc[-1].find(qn("w:pPr")).find(qn("w:spacing"))
    assert spacing.get(qn("w:line")) == "20"


def test_docx_writes_nothing_for_an_empty_run():
    word = word_of(Paragraph("above"), BottomStart(), BottomEnd())
    assert not [t for t in word.tables if t._tbl.tblPr.find(qn("w:tblpPr")) is not None]


# ---- ODT --------------------------------------------------------------------------------------------------------


def test_odt_holds_the_run_in_a_text_frame_fixed_to_the_foot_of_the_text_area_and_ends_the_page():
    package = zipfile.ZipFile(io.BytesIO(render_odt_document(document(
        Paragraph("above"), BottomStart(), Paragraph("signed"), Table(columns=["A"], rows=[["cell"]]), BottomEnd(), Paragraph("after"),
    ))))
    content = package.read("content.xml").decode()
    frame = re.search(r'<text:p text:style-name="P_Break"><draw:frame draw:style-name="fr_page_bottom".*?</draw:frame>', content, re.S)
    assert frame and "signed" in frame.group(0) and "<table:table " in frame.group(0)
    assert content.index(">above<") < content.index('draw:name="PageBottom1"') < content.index(">after<")
    style = re.search(r'<style:style style:name="fr_page_bottom".*?</style:style>', content, re.S).group(0)
    assert 'style:vertical-pos="bottom"' in style and 'style:vertical-rel="page-content"' in style and 'draw:fill="none"' in style
    assert 'style:parent-style-name="Frame"' in style and 'style:name="Frame" style:family="graphic"' in package.read("styles.xml").decode()


def test_odt_drops_the_blank_spacer_a_table_leaves_inside_the_frame():
    package = zipfile.ZipFile(io.BytesIO(render_odt_document(document(
        BottomStart(), Table(columns=["A"], rows=[["cell"]]), BottomEnd(),
    ))))
    content = package.read("content.xml").decode()
    assert '</table:table><text:p text:style-name="P_Float"/></draw:text-box>' in content


def test_odt_writes_no_frame_for_an_empty_run():
    package = zipfile.ZipFile(io.BytesIO(render_odt_document(document(Paragraph("above"), BottomStart(), BottomEnd()))))
    assert "<draw:frame" not in package.read("content.xml").decode()


# ---- HTML -------------------------------------------------------------------------------------------------------


def test_html_has_no_pages_so_it_shows_the_run_in_place():
    html = render_html_document(document(Paragraph("above"), BottomStart(), Paragraph("signed"), BottomEnd(), Paragraph("after"))).decode()
    assert html.index("<p>above</p>") < html.index("<p>signed</p>") < html.index("<p>after</p>")


def test_a_run_with_a_page_break_inside_is_still_drawn_without_failing():
    assert render_pdf_document(document(BottomStart(), Paragraph("a"), PageBreak(), Paragraph("b"), BottomEnd())).startswith(b"%PDF")
