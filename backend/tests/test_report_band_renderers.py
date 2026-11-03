"""The header and footer cells in the four renderers: each draws the widths and vertical alignments that
`resolve_band_cells` decided (PDF geometry, Word and OpenDocument XML, HTML styles), a long centre wraps in the centre
only, and the logo sits at its cell's alignment.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile
import zlib

import pytest
from docx import Document as DocxDocument

from app.services.report_band_cells import resolve_band_cells
from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_model import Margins, PageStyle, PageStyleChange, Paragraph, ReportDocument, RunningBand
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from app.services.report_pdf_running import grow_margins_for_bands

LONG = " ".join(["Project overview - Ballard Engineering Programme Delivery Office quarterly status and forward look"] * 3)
CM = 72 / 2.54


def document(band: RunningBand) -> ReportDocument:
    return ReportDocument(title="T", blocks=[Paragraph("body")], header=band, footer=None)


def usable(doc: ReportDocument) -> float:
    return doc.style.usable_width_cm


def pdf_texts(pdf: bytes, low: bool = False) -> list[tuple[float, float, str]]:
    """`(x, y, text)` of every positioned text object on the first page that is a header (baseline over 700 pt on A4), or,
    with `low`, a footer (baseline under 100 pt)."""
    found: list[tuple[float, float, str]] = []
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            content = zlib.decompress(base64.a85decode(raw.strip(), adobe=True)).decode("latin-1")
        except Exception:  # noqa: BLE001 - a font or the document info, not a page
            continue
        found += [(float(x), float(y), t) for x, y, t in re.findall(r"1 0 0 1 ([\d.]+) ([\d.]+) Tm \((.*?)\) Tj", content)]
        break
    return [item for item in found if (item[1] < 100 if low else item[1] > 700)]


# ---- PDF ----------------------------------------------------------------------------------------------------------


def test_the_pdf_cells_start_where_the_resolver_puts_them():
    band = RunningBand(left=("L",), centre=("C",), right=("R",), widths=("25%", None, None))
    doc = document(band)
    cells = resolve_band_cells(band, usable(doc))
    margin = doc.style.margins.left * CM
    texts = {t: x for x, _, t in pdf_texts(render_pdf_document(doc))}
    assert texts["L"] == pytest.approx(margin, abs=0.5)
    assert cells[0].width_cm == pytest.approx(usable(doc) * 0.25)
    # the centre text is centred in the cell the resolver gave it
    centre_start = margin + cells[0].width_cm * CM
    assert centre_start < texts["C"] < centre_start + cells[1].width_cm * CM


def test_a_long_centre_wraps_inside_the_centre_and_the_sides_stay_on_one_line():
    band = RunningBand(left=("ACME-1",), centre=(LONG,), right=("Page 1",))
    doc = document(band)
    cells = resolve_band_cells(band, usable(doc))
    margin = doc.style.margins.left * CM
    texts = pdf_texts(render_pdf_document(doc))
    centre = [item for item in texts if item[2] not in ("ACME-1", "Page 1")]
    assert len(centre) >= 2 and len({y for _, y, _ in centre}) == len(centre)  # wrapped onto separate lines
    low, high = margin + cells[0].width_cm * CM, margin + (cells[0].width_cm + cells[1].width_cm) * CM
    assert all(low - 0.5 <= x <= high for x, _, _ in centre)
    assert " ".join(t for _, _, t in centre) == LONG
    assert [t for _, _, t in texts].count("ACME-1") == 1


@pytest.mark.parametrize("valign", ["top", "middle", "bottom"])
def test_a_one_line_cell_beside_a_wrapped_one_sits_at_the_alignment(valign: str):
    band = RunningBand(left=("ACME-1",), centre=(LONG,), right=("R",), valign=valign)
    texts = pdf_texts(render_pdf_document(document(band)))
    centre_ys = sorted((y for _, y, t in texts if t not in ("ACME-1", "R")), reverse=True)
    left_y = next(y for _, y, t in texts if t == "ACME-1")
    expected = {"top": centre_ys[0], "bottom": centre_ys[-1], "middle": (centre_ys[0] + centre_ys[-1]) / 2}[valign]
    assert left_y == pytest.approx(expected, abs=0.5)


def test_a_cells_own_alignment_wins_over_the_bands():
    band = RunningBand(left=("ACME-1",), centre=(LONG,), valign="top", valigns=("bottom", None, None))
    texts = pdf_texts(render_pdf_document(document(band)))
    centre_ys = sorted(y for _, y, t in texts if t != "ACME-1")
    assert next(y for _, y, t in texts if t == "ACME-1") == pytest.approx(centre_ys[0], abs=0.5)


# ---- Word ---------------------------------------------------------------------------------------------------------


def test_word_cells_carry_the_resolved_widths_and_alignments():
    band = RunningBand(left=("L",), centre=("C",), right=("R",), widths=("25%", None, "4 cm"), valigns=(None, "bottom", None))
    doc = document(band)
    cells = resolve_band_cells(band, usable(doc))
    word = DocxDocument(io.BytesIO(render_docx_document(doc)))
    xml = word.sections[0].header._element.xml
    expected = pytest.approx([c.width_cm * 567 for c in cells], abs=2)
    assert [int(w) for w in re.findall(r"<w:tcW [^>]*w:w=\"(\d+)\"", xml)] == expected
    assert [int(w) for w in re.findall(r"<w:gridCol [^>]*w:w=\"(\d+)\"", xml)] == expected
    assert re.findall(r"<w:vAlign w:val=\"(\w+)\"", xml) == ["top", "bottom", "top"]


# ---- OpenDocument text --------------------------------------------------------------------------------------------


def test_odt_columns_and_cells_carry_the_resolved_widths_and_alignments():
    band = RunningBand(left=("L",), centre=("C",), right=("R",), widths=("25%", None, None), valigns=(None, None, "middle"))
    doc = document(band)
    cells = resolve_band_cells(band, usable(doc))
    with zipfile.ZipFile(io.BytesIO(render_odt_document(doc))) as archive:
        styles = archive.read("styles.xml").decode()
    names = re.findall(r'<table:table-column table:style-name="(\w+)"/>', styles)[:3]  # the header; the default footer follows
    column = r'style:name="{}" style:family="table-column"><style:table-column-properties style:column-width="([\d.]+)cm"'
    widths = [float(re.search(column.format(n), styles).group(1)) for n in names]
    assert widths == pytest.approx([c.width_cm for c in cells], abs=0.01)
    cell_names = re.findall(r'<table:table-cell table:style-name="(\w+)" office:value-type="string"><text:p text:style-name="Band_', styles)[:3]
    aligns = [re.search(rf'style:name="{n}" style:family="table-cell">.*?style:vertical-align="(\w+)"', styles).group(1) for n in cell_names]
    assert aligns == ["top", "top", "middle"]


# ---- HTML ---------------------------------------------------------------------------------------------------------


def test_the_html_band_has_the_resolved_columns_and_alignments():
    band = RunningBand(left=("L",), centre=("C",), right=("R",), widths=("25%", None, None), valigns=(None, None, "bottom"))
    doc = document(band)
    cells = resolve_band_cells(band, usable(doc))
    html = render_html_document(doc).decode()
    fr = [float(v) for v in re.findall(r"minmax\(0, ([\d.]+)fr\)", html)]
    assert fr == pytest.approx([c.width_cm for c in cells], abs=0.001)
    assert re.findall(r'class="cell \w+" style="align-items: ([\w-]+)"', html) == ["flex-start", "flex-start", "flex-end"]


# ---- a footer defaults to the bottom, in every format -----------------------------------------------------------


def footer_document(band: RunningBand) -> ReportDocument:
    return ReportDocument(title="T", blocks=[Paragraph("body")], header=None, footer=band)


def test_an_unset_footer_sits_at_the_bottom_in_pdf_word_odt_and_html():
    band = RunningBand(left=("ACME-1",), centre=(LONG,), right=("R",), kind="footer")
    doc = footer_document(band)
    pdf = [(y, t) for x, y, t in pdf_texts(render_pdf_document(doc), low=True)]
    centre_ys = sorted(y for y, t in pdf if t not in ("ACME-1", "R"))
    assert len(centre_ys) >= 2
    assert next(y for y, t in pdf if t == "ACME-1") == pytest.approx(centre_ys[0], abs=0.5)  # the lowest line of the wrapped centre
    word = DocxDocument(io.BytesIO(render_docx_document(doc)))
    assert re.findall(r"<w:vAlign w:val=\"(\w+)\"", word.sections[0].footer._element.xml) == ["bottom"] * 3
    with zipfile.ZipFile(io.BytesIO(render_odt_document(doc))) as archive:
        styles = archive.read("styles.xml").decode()
    names = re.findall(r'<table:table-cell table:style-name="(\w+)" office:value-type="string"><text:p text:style-name="Band_', styles)[:3]
    assert [re.search(rf'style:name="{n}" style:family="table-cell">.*?style:vertical-align="(\w+)"', styles).group(1) for n in names] == ["bottom"] * 3
    assert re.findall(r'class="cell \w+" style="align-items: ([\w-]+)"', render_html_document(doc).decode()) == ["flex-end"] * 3


def test_a_footer_that_says_top_keeps_it_in_every_format():
    band = RunningBand(left=("ACME-1",), centre=(LONG,), right=("R",), kind="footer", valign="top")
    doc = footer_document(band)
    pdf = [(y, t) for x, y, t in pdf_texts(render_pdf_document(doc), low=True)]
    centre_ys = sorted((y for y, t in pdf if t not in ("ACME-1", "R")), reverse=True)
    assert next(y for y, t in pdf if t == "ACME-1") == pytest.approx(centre_ys[0], abs=0.5)  # the first line of the wrapped centre
    word = DocxDocument(io.BytesIO(render_docx_document(doc)))
    assert re.findall(r"<w:vAlign w:val=\"(\w+)\"", word.sections[0].footer._element.xml) == ["top"] * 3
    assert re.findall(r'class="cell \w+" style="align-items: ([\w-]+)"', render_html_document(doc).decode()) == ["flex-start"] * 3


# ---- margins grow to hold a wrapped band --------------------------------------------------------------------------

BODY_MARKER = "body"


def body_y(pdf: bytes) -> float:
    """The bottom edge of the first body paragraph on the first page (ReportLab places a paragraph by a `cm` translation)."""
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            content = zlib.decompress(base64.a85decode(raw.strip(), adobe=True)).decode("latin-1")
        except Exception:  # noqa: BLE001 - a font or the document info, not a page
            continue
        found = re.search(r"1 0 0 1 [\d.]+ ([\d.]+) cm\s+q\s+[^Q]*?\(body\) Tj", content)
        if found:
            return float(found.group(1))
    raise AssertionError("no body paragraph found")


def test_a_header_that_wraps_taller_than_its_margin_pushes_the_body_down_instead_of_overlapping_it():
    short = document(RunningBand(left=("L",), centre=("C",), right=("R",)))
    tall = document(RunningBand(left=("L",), centre=(LONG,), right=("R",)))
    assert grow_margins_for_bands(short).style.margins == short.style.margins
    grown = grow_margins_for_bands(tall)
    assert grown.style.margins.top > tall.style.margins.top
    assert grown.style.margins.bottom == tall.style.margins.bottom
    lines = len([1 for _, y, t in pdf_texts(render_pdf_document(tall)) if t not in ("L", "R")])
    band_bottom = grown.style.dimensions_cm[1] * CM - (0.5 + lines * 0.4) * CM
    assert body_y(render_pdf_document(tall)) < band_bottom  # the body starts under the wrapped band
    assert body_y(render_pdf_document(tall)) < body_y(render_pdf_document(short))


def test_a_margin_the_author_made_big_enough_is_kept():
    doc = ReportDocument(title="T", blocks=[Paragraph("body")], header=RunningBand(centre=(LONG,)), footer=None, margins=Margins(top=4.0))
    assert grow_margins_for_bands(doc).style.margins.top == 4.0


def test_a_wrapping_footer_grows_the_bottom_margin_and_a_mirrored_style_holds_both_sides():
    band = RunningBand(left=("L",), centre=(LONG,), right=("R",))
    doc = ReportDocument(title="T", blocks=[Paragraph("body")], header=None, footer=band, mirror=True)
    grown = grow_margins_for_bands(doc).style.margins
    assert grown.bottom > doc.style.margins.bottom and grown.top == doc.style.margins.top


def test_a_section_with_its_own_wrapping_band_grows_only_its_own_margin():
    wide = PageStyle("A3", True, Margins(), False, RunningBand(centre=(LONG * 2,)), None)
    doc = ReportDocument(title="T", blocks=[Paragraph("a"), PageStyleChange(wide), Paragraph("b")], header=None, footer=None)
    grown = grow_margins_for_bands(doc)
    assert grown.style.margins == doc.style.margins
    section = next(b for b in grown.blocks if isinstance(b, PageStyleChange))
    assert section.style.margins.top >= wide.margins.top
