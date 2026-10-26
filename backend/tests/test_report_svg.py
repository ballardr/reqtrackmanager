"""Tests for SVG figures in reports (`services.report_svg`) and their rendering in the PDF, Word and HTML
renderers: hostile markup is refused or stripped, and a clean figure is drawn in every format."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_model import Heading, Image, ReportDocument
from app.services.report_pdf import render_pdf_document
from app.services.report_svg import MAX_SVG_CHARS, UnsafeSvgError, sanitize_svg, svg_flowable, svg_png

NS = 'xmlns="http://www.w3.org/2000/svg"'
FIGURE = f'<svg {NS} width="200" height="80"><rect width="200" height="80" fill="#2f855a"/><text x="10" y="40" fill="#fff">Hello</text></svg>'


def test_a_clean_figure_passes_unchanged_in_substance():
    cleaned = sanitize_svg(FIGURE)

    assert "<rect" in cleaned and "<text" in cleaned and "Hello" in cleaned and cleaned.startswith("<svg")


@pytest.mark.parametrize("markup", [
    f'<!DOCTYPE svg [<!ENTITY a "boom">]><svg {NS}><text>&a;</text></svg>',
    f'<svg {NS}><!ENTITY x "y"></svg>',
    "<html><body/></html>",
    f'<svg {NS}',  # not well-formed
    f'<svg {NS}><rect fill="url(http://evil/x)"/></svg>',
    f'<svg {NS}><rect fill="url( \'https://evil/x\')"/></svg>',
    f'<svg {NS}><rect style="fill:url(javascript:alert(1))"/></svg>',
    f'<svg {NS}><rect fill="data:text/html,x"/></svg>',
    "x" * (MAX_SVG_CHARS + 1),
])
def test_hostile_or_malformed_markup_is_refused(markup):
    with pytest.raises(UnsafeSvgError):
        sanitize_svg(markup)


def test_scripts_handlers_images_and_external_links_are_stripped():
    hostile = (
        f'<svg {NS} xmlns:xlink="http://www.w3.org/1999/xlink" onload="alert(1)">'
        '<script>alert(1)</script><foreignObject><div>x</div></foreignObject><image href="http://evil/p.png"/>'
        '<style>@import url(http://evil/a.css);</style><a href="javascript:alert(1)"><rect width="9" height="9"/></a>'
        '<rect width="5" height="5" onclick="alert(2)" xlink:href="http://evil/y" fill="red"/>'
        '<use xlink:href="#ok"/><circle id="ok" r="2"/></svg>'
    )

    cleaned = sanitize_svg(hostile)

    for forbidden in ("script", "foreignObject", "<image", "<style", "onload", "onclick", "evil", "javascript", "<a "):
        assert forbidden not in cleaned, forbidden
    assert 'fill="red"' in cleaned and 'href="#ok"' in cleaned and "<circle" in cleaned


def test_a_figure_is_drawn_as_vector_and_as_png():
    assert svg_flowable(FIGURE, 400).width <= 400
    assert svg_flowable(FIGURE, 50).width <= 50  # shrunk to fit
    assert svg_png(FIGURE).startswith(b"\x89PNG")
    assert svg_flowable(f'<!DOCTYPE x><svg {NS}/>', 400) is None  # unacceptable markup is skipped, not raised


def document(*blocks) -> ReportDocument:
    return ReportDocument(title="Figures", blocks=[Heading("Diagram", 1), *blocks])


def test_the_pdf_draws_an_svg_figure_and_survives_a_bad_one():
    plain = render_pdf_document(document())
    with_figure = render_pdf_document(document(Image(svg=FIGURE)))
    hostile = render_pdf_document(document(Image(svg=f'<!DOCTYPE x><svg {NS}/>'), Image(svg="not svg")))

    assert with_figure.startswith(b"%PDF") and len(with_figure) > len(plain)
    assert hostile.startswith(b"%PDF")


def test_word_gets_a_png_of_an_svg_figure_and_survives_a_bad_one():
    with_figure = render_docx_document(document(Image(svg=FIGURE)))
    hostile = render_docx_document(document(Image(svg="not svg")))

    with zipfile.ZipFile(io.BytesIO(with_figure)) as archive:
        media = [n for n in archive.namelist() if n.startswith("word/media/")]
        assert media and archive.read(media[0]).startswith(b"\x89PNG")
    with zipfile.ZipFile(io.BytesIO(hostile)) as archive:
        assert not [n for n in archive.namelist() if n.startswith("word/media/")]


def test_html_inlines_only_the_sanitised_figure():
    page = render_html_document(document(Image(svg=FIGURE.replace("</svg>", "<script>alert(1)</script></svg>"), alt="Hello figure"))).decode()

    assert "<svg" in page and "Hello" in page and "<script" not in page and 'aria-label="Hello figure"' in page
    assert "<svg" not in render_html_document(document(Image(svg=f"<!DOCTYPE x><svg {NS}/>"))).decode().split("<body>")[1]
