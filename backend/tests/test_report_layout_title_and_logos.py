"""
Module: tests.test_report_layout_title_and_logos

A custom layout's document prints a title only through a block of its own, and the preview (HTML) draws the same
pictures as the downloads (PDF, Word, OpenDocument):

- `ReportDocument.show_title` off prints no title or cover in any of the four formats, while the layout's name stays
  the file's metadata title; on (a built-in report) it prints as before.
- An evaluated layout's document has `show_title` off.
- A picture laid over the page is placed in the HTML view as a share of the page's width, so a narrow preview pane
  does not push a page-anchored logo off its edge.
- One fixture (a logo in the header, a picture in the body, a page-anchored picture over the page) is drawn in all
  four formats, with no title, so the preview cannot drift from the downloads.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile
import zlib
from types import SimpleNamespace

from docx import Document as DocxDocument
from PIL import Image as PilImage

from app.services.custom_report_run import document_for
from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_model import Heading, Image, Margins, PageStyle, Paragraph, ReportDocument, RunningBand
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document

TITLE = "Zebra Quarterly Title"


def picture(colour: str) -> bytes:
    out = io.BytesIO()
    PilImage.new("RGB", (60, 20), colour).save(out, "PNG")
    return out.getvalue()


def fixture(*, show_title: bool) -> ReportDocument:
    """A header logo, a body picture, a page-anchored picture over the page, and a heading of the layout's own."""
    band = RunningBand(centre=("Header text",), logo=Image(data=picture("red")), logo_slot="left", logo_height_cm=1.0)
    return ReportDocument(
        title=TITLE, show_title=show_title, header=band,
        blocks=[
            Image(data=picture("green"), alt="Body", width=4),
            Image(data=picture("blue"), alt="Over", width=2.25, height_cm=1.2, placement="front", anchor="page", offset_x_cm=17.25, offset_y_cm=0.5),
            Heading("Own heading", 1),
            Paragraph("Body text"),
        ],
    )


def pdf_text(pdf: bytes) -> str:
    """The text of every page content stream (the letters of a ReportLab string sit in `( )` runs)."""
    out = []
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            content = zlib.decompress(base64.a85decode(raw.strip(), adobe=True)).decode("latin-1")
        except Exception:  # noqa: BLE001 - not a page content stream
            continue
        out.append("".join(re.findall(r"\(((?:[^()\\]|\\.)*)\)", content)))
    return " ".join(out)


def odt_parts(odt: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(odt)) as package:
        return {name: package.read(name).decode("utf-8", "replace") for name in package.namelist() if name.endswith(".xml")}


def test_html_prints_the_title_only_when_the_document_asks():
    assert f"<h1>{TITLE}</h1>" in render_html_document(fixture(show_title=True)).decode()
    html = render_html_document(fixture(show_title=False)).decode()
    assert "<h1>" not in html
    assert f"<title>{TITLE}</title>" in html  # the name stays the page's metadata title
    assert "Own heading" in html


def test_pdf_prints_the_title_only_when_the_document_asks():
    assert TITLE in pdf_text(render_pdf_document(fixture(show_title=True)))
    pdf = render_pdf_document(fixture(show_title=False))
    assert TITLE not in pdf_text(pdf)
    assert "Own heading" in pdf_text(pdf)
    assert TITLE.encode() in pdf  # the document information keeps the name


def test_word_prints_the_title_only_when_the_document_asks():
    shown = DocxDocument(io.BytesIO(render_docx_document(fixture(show_title=True))))
    assert TITLE in [p.text for p in shown.paragraphs]
    hidden = DocxDocument(io.BytesIO(render_docx_document(fixture(show_title=False))))
    assert TITLE not in [p.text for p in hidden.paragraphs]
    assert "Own heading" in [p.text for p in hidden.paragraphs]
    assert hidden.core_properties.title == TITLE


def test_opendocument_prints_the_title_only_when_the_document_asks():
    assert TITLE in odt_parts(render_odt_document(fixture(show_title=True)))["content.xml"]
    hidden = odt_parts(render_odt_document(fixture(show_title=False)))
    assert TITLE not in hidden["content.xml"]
    assert "Own heading" in hidden["content.xml"]
    assert TITLE in hidden["meta.xml"]


def test_all_four_formats_draw_the_header_logo_the_body_picture_and_the_picture_over_the_page():
    document = fixture(show_title=False)
    html = render_html_document(document).decode()
    assert html.count("<img") == 3  # header logo, body picture, picture over the page
    pdf = render_pdf_document(document)
    assert len(re.findall(rb"/Subtype /Image", pdf)) == 3
    word = DocxDocument(io.BytesIO(render_docx_document(document)))
    assert sum(1 for part in word.part.package.iter_parts() if str(part.partname).startswith("/word/media/")) == 3
    # A logo in a header is stored once per master page that shows it, so the pictures are counted by their content.
    with zipfile.ZipFile(io.BytesIO(render_odt_document(document))) as package:
        assert len({package.read(n) for n in package.namelist() if n.startswith("Pictures/")}) == 3


def test_html_places_a_page_anchored_picture_as_a_share_of_the_page_width():
    html = render_html_document(fixture(show_title=False)).decode()
    left = float(re.search(r'<figure class="image" style="left:([\d.]+)%;top:0.5cm"', html).group(1))
    assert left == round(100 * 17.25 / 21.0, 2)  # A4 portrait is 21 cm wide


def test_html_measures_a_margin_anchor_from_the_text_area_and_a_paragraph_anchor_from_the_block():
    def left_of(anchor: str, offset: float, margins: Margins) -> str:
        over = Image(data=picture("blue"), placement="front", anchor=anchor, offset_x_cm=offset)
        document = ReportDocument(title="T", blocks=[over], margins=margins)
        return re.search(r'<figure class="image" style="left:([^;]+);', render_html_document(document).decode()).group(1)

    assert left_of("margin", 1.0, Margins(2, 2, 3, 2)) == f"{100 * 4 / 21:.2f}%"
    assert left_of("paragraph", 1.5, Margins()) == "1.5cm"
    assert PageStyle().dimensions_cm[0] == 21.0


def test_a_layouts_downloaded_document_holds_only_the_layouts_blocks():
    """No scope line and no run remarks are added in front of what the layout contains."""
    document = fixture(show_title=False)
    run = SimpleNamespace(
        evaluated=SimpleNamespace(document=document), layout=SimpleNamespace(name=TITLE),
        notes=["2 project(s) were left out because they have hidden this report."],
    )
    produced = document_for(run, branding=None)
    assert produced.blocks == document.blocks
    assert produced.show_title is False and produced.title == TITLE
