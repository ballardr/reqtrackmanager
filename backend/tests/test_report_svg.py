"""Tests for SVG figures in reports (`services.report_svg`) and their rendering in the PDF, Word and HTML
renderers: hostile markup is refused or stripped, and a clean figure is drawn in every format."""

from __future__ import annotations

import base64
import io
import re
import zipfile

import pytest
from PIL import Image as PilImage
from PIL.PngImagePlugin import PngInfo

from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_model import Heading, Image, ReportDocument
from app.services.report_pdf import render_pdf_document
from app.services.report_svg import (
    MAX_EMBEDDED_IMAGES,
    MAX_EMBEDDED_PIXELS,
    MAX_SVG_CHARS,
    UnsafeSvgError,
    sanitize_svg,
    svg_flowable,
    svg_png,
)

NS = 'xmlns="http://www.w3.org/2000/svg"'
FIGURE = f'<svg {NS} width="200" height="80"><rect width="200" height="80" fill="#2f855a"/><text x="10" y="40" fill="#fff">Hello</text></svg>'


def test_a_clean_figure_passes_unchanged_in_substance():
    cleaned = sanitize_svg(FIGURE)

    assert "<rect" in cleaned and "<text" in cleaned and "Hello" in cleaned and cleaned.startswith("<svg")


@pytest.mark.parametrize("markup", [
    f'<!DOCTYPE svg [<!ENTITY a "boom">]><svg {NS}><text>&a;</text></svg>',
    f'<svg {NS}><!ENTITY x "y"></svg>',
    f'<!DOCTYPE svg [<!ELEMENT svg ANY>]><svg {NS}/>',  # an internal subset, even with no entity
    f'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://evil/x.dtd" [<!ENTITY a "b">]><svg {NS}/>',
    f'<!DOCTYPE svg SYSTEM "file:///etc/passwd"><!DOCTYPE svg><svg {NS}/>',  # a second DOCTYPE is not the plain form
    "<html><body/></html>",
    f'<svg {NS}',  # not well-formed
    f'<svg {NS}><rect fill="url(http://evil/x)"/></svg>',
    f'<svg {NS}><rect fill="url( \'https://evil/x\')"/></svg>',
    f'<svg {NS}><rect style="fill:url(javascript:alert(1))"/></svg>',
    f'<svg {NS}><rect fill="data:text/html,x"/></svg>',
    f'<svg {NS}>' + "<g/>" * (MAX_SVG_CHARS // 4 + 10) + "</svg>",  # the markup itself is over the cap
    "x" * (MAX_SVG_CHARS * 20),  # anything beyond markup plus the bitmap allowance
])
def test_hostile_or_malformed_markup_is_refused(markup):
    with pytest.raises(UnsafeSvgError):
        sanitize_svg(markup)


@pytest.mark.parametrize("doctype", [
    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">',  # Illustrator, Affinity, Inkscape
    "<!DOCTYPE svg>",
    '<!DOCTYPE svg SYSTEM "svg.dtd">',
])
def test_the_plain_doctype_a_vector_editor_writes_is_accepted_and_not_carried_on(doctype):
    prolog = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    cleaned = sanitize_svg(f"{prolog}{doctype}\n<svg {NS}><rect width=\"1\" height=\"1\"/></svg>")

    assert cleaned.startswith("<svg") and "<rect" in cleaned and "DOCTYPE" not in cleaned.upper()


def test_scripts_handlers_and_external_images_and_links_are_stripped():
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
    assert svg_flowable(f'<!DOCTYPE x [<!ENTITY a "b">]><svg {NS}/>', 400) is None  # unacceptable markup is skipped, not raised


def document(*blocks) -> ReportDocument:
    return ReportDocument(title="Figures", blocks=[Heading("Diagram", 1), *blocks])


def test_the_pdf_draws_an_svg_figure_and_survives_a_bad_one():
    plain = render_pdf_document(document())
    with_figure = render_pdf_document(document(Image(svg=FIGURE)))
    hostile = render_pdf_document(document(Image(svg=f'<!DOCTYPE x [<!ENTITY a "b">]><svg {NS}/>'), Image(svg="not svg")))

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
    assert "<svg" not in render_html_document(document(Image(svg=f'<!DOCTYPE x [<!ENTITY a "b">]><svg {NS}/>'))).decode().split("<body>")[1]


XLINK = 'xmlns:xlink="http://www.w3.org/1999/xlink"'


def raster(fmt: str = "PNG", size: tuple[int, int] = (8, 6), colour=(200, 30, 30, 255), **save) -> bytes:
    out = io.BytesIO()
    PilImage.new("RGBA" if fmt != "JPEG" else "RGB", size, colour if fmt != "JPEG" else colour[:3]).save(out, fmt, **save)
    return out.getvalue()


def data_uri(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def image_svg(href: str, attr: str = "xlink:href") -> str:
    return f'<svg {NS} {XLINK} viewBox="0 0 8 6"><image width="8" height="6" {attr}="{href}"/></svg>'


def embedded(markup: str) -> list[bytes]:
    return [base64.b64decode(m) for m in re.findall(r'<image[^>]* href="data:image/[a-z]+;base64,([A-Za-z0-9+/=]+)"', markup)]


@pytest.mark.parametrize(("fmt", "mime"), [("PNG", "image/png"), ("GIF", "image/gif"), ("WEBP", "image/webp"), ("JPEG", "image/jpeg")])
@pytest.mark.parametrize("attr", ["xlink:href", "href"])
def test_an_embedded_bitmap_is_kept_with_a_plain_href(fmt, mime, attr):
    cleaned = sanitize_svg(image_svg(data_uri(raster(fmt), mime), attr))

    (picture,) = embedded(cleaned)
    assert PilImage.open(io.BytesIO(picture)).size == (8, 6)
    assert "xlink:href" not in cleaned and 'width="8"' in cleaned


def test_an_embedded_bitmap_is_re_encoded_without_its_metadata():
    exif = PilImage.Exif()
    exif[0x010E] = "GPS-and-owner-secret"
    jpeg = io.BytesIO()
    PilImage.new("RGB", (8, 6), (1, 2, 3)).save(jpeg, "JPEG", exif=exif)
    png = io.BytesIO()
    info = PngInfo()
    info.add_text("Comment", "private-note")
    PilImage.new("RGB", (8, 6)).save(png, "PNG", pnginfo=info)

    for original, mime in ((jpeg.getvalue(), "image/jpeg"), (png.getvalue(), "image/png")):
        assert b"secret" in original or b"private-note" in original
        (clean,) = embedded(sanitize_svg(image_svg(data_uri(original, mime))))
        assert b"secret" not in clean and b"private-note" not in clean


def test_an_embedded_bitmap_is_drawn_in_every_format():
    svg = image_svg(data_uri(raster()))

    assert svg_png(svg, width_px=80, background=None).startswith(b"\x89PNG")
    picture = PilImage.open(io.BytesIO(svg_png(svg, width_px=80, background=None))).convert("RGBA")
    assert picture.getpixel((40, 30))[:3] == (200, 30, 30)  # the bitmap's colour reached the page
    assert svg_flowable(svg, 300) is not None


@pytest.mark.parametrize("href", [
    "http://evil.example/p.png",
    "https://evil.example/p.png",
    "file:///etc/passwd",
    "//evil.example/p.png",
    "logo.png",
    "#local",
    "data:image/svg+xml;base64," + base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>").decode(),
    "data:text/html;base64," + base64.b64encode(b"<script>alert(1)</script>").decode(),
    "data:image/png;base64,not base64!!",
    "data:image/png;base64," + base64.b64encode(b"this is not a PNG").decode(),
    "data:image/png,%89PNG",  # not base64
    "javascript:alert(1)",
])
def test_an_image_that_is_not_a_decodable_embedded_bitmap_is_dropped_and_the_rest_kept(href):
    cleaned = sanitize_svg(f'<svg {NS} {XLINK}><rect width="2" height="2"/><image xlink:href="{href}"/></svg>')

    assert "<image" not in cleaned and "<rect" in cleaned


def test_a_bitmap_cannot_smuggle_anything_through_its_other_attributes_or_children():
    cleaned = sanitize_svg(
        f'<svg {NS} {XLINK}><image width="8" height="6" onload="alert(1)" style="behavior:{{evil}}" '
        f'xlink:href="{data_uri(raster())}"><script>alert(1)</script><image href="http://evil/y"/></image></svg>'
    )

    assert "onload" not in cleaned and "evil" not in cleaned and "script" not in cleaned
    assert cleaned.count("<image") == 1 and len(embedded(cleaned)) == 1


def test_a_picture_over_the_pixel_limit_refuses_the_whole_svg():
    big = io.BytesIO()
    PilImage.new("1", (MAX_EMBEDDED_PIXELS // 1000 + 1, 1000)).save(big, "PNG")

    with pytest.raises(UnsafeSvgError, match="too many pixels"):
        sanitize_svg(image_svg(data_uri(big.getvalue())))


def test_an_svg_with_too_many_bitmaps_keeps_the_first_ones():
    tiny = data_uri(raster(size=(2, 2)))
    markup = f'<svg {NS} {XLINK}>' + "".join(f'<image xlink:href="{tiny}"/>' for _ in range(MAX_EMBEDDED_IMAGES + 5)) + "</svg>"

    assert sanitize_svg(markup).count("<image") == MAX_EMBEDDED_IMAGES


def test_the_bitmap_allowance_does_not_raise_the_cap_on_the_markup_itself():
    uri = data_uri(raster(size=(300, 300)))
    markup = f'<svg {NS} {XLINK}><image xlink:href="{uri}"/>' + "<g/>" * (MAX_SVG_CHARS // 4 + 10) + "</svg>"

    with pytest.raises(UnsafeSvgError, match="too large"):
        sanitize_svg(markup)


def test_sanitising_twice_gives_the_same_bitmap():
    once = sanitize_svg(image_svg(data_uri(raster())))

    assert embedded(sanitize_svg(once)) == embedded(once)
