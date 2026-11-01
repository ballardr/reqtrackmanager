"""Tests for the spacer block: tree validation, the text view, the block form and the four renderers (PDF, Word, ODT,
HTML), each measuring the same gap. No database."""

from __future__ import annotations

import base64
import io
import re
import zipfile
import zlib
from typing import Any

import pytest
from docx import Document as DocxDocument
from docx.oxml.ns import qn

from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import BLOCK_SPECS, FAMILY_DOCUMENT, empty_tree, validate_tree
from app.services.report_model import PageBreak, Paragraph, ReportDocument, VerticalSpace
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document

CM_PT = 72 / 2.54


def tree(*nodes: dict[str, Any], family: str = "document") -> dict[str, Any]:
    return {**empty_tree(family), "nodes": list(nodes)}


def problems(*nodes: dict[str, Any], family: str = "document") -> dict[str, str]:
    return {e.path: e.message for e in validate_tree(tree(*nodes, family=family)).errors}


def document(*blocks: Any) -> ReportDocument:
    return ReportDocument(title="Spacing", blocks=list(blocks))


# ---- the tree ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", [{"type": "spacer", "height": 1}, {"type": "spacer", "height": 1.5, "height_unit": "cm"},
                                  {"type": "spacer", "height": 10, "height_unit": "mm"}, {"type": "spacer", "height": 20},
                                  {"type": "spacer", "height": 200, "height_unit": "mm"}, {"type": "spacer", "height": 1, "height_unit": "mm"}])
def test_a_spacer_with_a_height_in_range_is_valid(node):
    assert problems(node) == {}


@pytest.mark.parametrize(
    ("node", "path"),
    [
        ({"type": "spacer"}, "nodes[0].height"),
        ({"type": "spacer", "height": 0}, "nodes[0].height"),
        ({"type": "spacer", "height": 20.1}, "nodes[0].height"),
        ({"type": "spacer", "height": 0.9, "height_unit": "mm"}, "nodes[0].height"),
        ({"type": "spacer", "height": 201, "height_unit": "mm"}, "nodes[0].height"),
        ({"type": "spacer", "height": "2"}, "nodes[0].height"),
        ({"type": "spacer", "height": True}, "nodes[0].height"),
        ({"type": "spacer", "height": 1, "height_unit": "percent"}, "nodes[0].height_unit"),
        ({"type": "spacer", "height": 1, "colour": "red"}, "nodes[0].colour"),
    ],
)
def test_a_spacer_outside_its_bounds_or_with_unknown_keys_is_refused(node, path):
    assert path in problems(node)


def test_a_spacer_is_a_document_block_inside_sections_and_loops_and_a_table_layout_refuses_it():
    assert BLOCK_SPECS["spacer"].families == (FAMILY_DOCUMENT,)
    nested = {"type": "group", "source": {"record_type": "requirement"}, "by": "status", "as": "g",
              "children": [{"type": "spacer", "height": 2}]}
    assert problems(nested) == {}
    assert problems({"type": "spacer", "height": 1}, family="table")


def test_the_block_form_is_served_from_the_schema_with_help():
    schema = BLOCK_SPECS["spacer"].schema
    assert schema.label == "Spacer" and [f.key for f in schema.fields] == ["height", "height_unit"]
    assert all(f.help for f in schema.fields)


# ---- the text view ----------------------------------------------------------------------------------------------


def test_the_text_view_round_trips_a_spacer_with_and_without_a_unit():
    source = tree({"type": "spacer", "height": 1.5, "height_unit": "cm"}, {"type": "spacer", "height": 8, "height_unit": "mm"},
                  {"type": "spacer", "height": 1})
    text = format_tree(source)
    assert "@spacer 1.5 cm" in text and "@spacer 8 mm" in text and "@spacer 1\n" in text
    result = parse_text(text)
    assert result.errors == [] and result.tree == source


@pytest.mark.parametrize("line", ["@spacer", "@spacer tall", "@spacer 1 cm extra", "@spacer 1 inch"])
def test_a_spacer_line_that_is_not_a_height_is_a_text_error(line):
    assert parse_text(f"@layout document\n{line}\n").errors or parse_text(f"{line}\n").errors


# ---- the renderers ----------------------------------------------------------------------------------------------


def pdf_positions(pdf: bytes) -> dict[str, float]:
    """The baseline y of each word printed in the PDF's content streams (text blocks of one word)."""
    streams = []
    for body in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        raw = body.strip()
        try:
            streams.append(zlib.decompress(base64.a85decode(raw[:-2] if raw.endswith(b"~>") else raw)).decode("latin1"))
        except Exception:  # noqa: BLE001 - an image or font stream: not content
            continue
    positions: dict[str, float] = {}
    for stream in streams:
        for match in re.finditer(r"1 0 0 1 [\d.]+ ([\d.]+) cm\nq\n0 0 0 rg\nBT 1 0 0 1 0 ([\d.]+) Tm [^(]*\((\w+)\) Tj", stream):
            positions[match.group(3)] = float(match.group(1)) + float(match.group(2))
    return positions


def test_pdf_leaves_exactly_the_gap_between_two_paragraphs():
    plain = pdf_positions(render_pdf_document(document(Paragraph("above"), Paragraph("below"))))
    spaced = pdf_positions(render_pdf_document(document(Paragraph("above"), VerticalSpace(2), Paragraph("below"))))
    assert plain["above"] == pytest.approx(spaced["above"])
    assert plain["below"] - spaced["below"] == pytest.approx(2 * CM_PT, abs=0.1)


def test_pdf_keeps_a_spacer_at_the_top_of_a_page():
    plain = pdf_positions(render_pdf_document(document(PageBreak(), Paragraph("top"))))
    spaced = pdf_positions(render_pdf_document(document(PageBreak(), VerticalSpace(3), Paragraph("top"))))
    # The space is kept; the paragraph's own space-before, which a frame drops at its very top, now applies after it (6 pt).
    assert plain["top"] - spaced["top"] == pytest.approx(3 * CM_PT + 6, abs=0.1)


def test_pdf_carries_a_spacer_taller_than_the_room_left_to_the_next_page_and_never_overflows_a_page():
    pdf = render_pdf_document(document(Paragraph("word " * 20), VerticalSpace(200 / 10), VerticalSpace(20), Paragraph("end")))
    assert pdf.count(b"/Type /Page\n") >= 2 and "end" in pdf_positions(pdf)


def test_docx_writes_an_empty_paragraph_with_an_exact_line_height():
    word = DocxDocument(io.BytesIO(render_docx_document(document(Paragraph("above"), VerticalSpace(1.5), Paragraph("below")))))
    spacing = [p._p.pPr.find(qn("w:spacing")) for p in word.paragraphs if not p.text.strip() and p._p.pPr is not None]
    exact = [s for s in spacing if s is not None and s.get(qn("w:lineRule")) == "exact"]
    assert len(exact) == 1
    assert int(exact[0].get(qn("w:line"))) == pytest.approx(1.5 * 567, abs=2)  # twentieths of a point
    assert exact[0].get(qn("w:before")) == "0" and exact[0].get(qn("w:after")) == "0"


def test_odt_writes_an_empty_paragraph_with_a_fixed_line_height_once_per_distinct_height():
    package = zipfile.ZipFile(io.BytesIO(render_odt_document(document(VerticalSpace(1.5), Paragraph("x"), VerticalSpace(1.5), VerticalSpace(0.5)))))
    content = package.read("content.xml").decode()
    assert content.count('fo:line-height="1.5cm"') == 1 and content.count('fo:line-height="0.5cm"') == 1
    assert len(re.findall(r'<text:p text:style-name="P_Space\d_5"/>', content)) == 3


def test_html_shows_a_hidden_block_of_that_height():
    html = render_html_document(document(Paragraph("above"), VerticalSpace(1.5), Paragraph("below")))
    assert b'<div class="spacer" aria-hidden="true" style="height: 1.5cm"></div>' in html
