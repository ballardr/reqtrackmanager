"""Tests for the layout `shape` block: the tree check, the text view, the generated SVG, the four document renderers (a
shape layers like a picture, and is transparent where Word and OpenDocument have to draw it) and a run.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from typing import Any

import pytest
from docx import Document as DocxDocument
from PIL import Image as PilImage

from app.models.organization import Organization
from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import InvalidLayoutError, assert_valid, empty_tree
from app.services.report_model import Image, Paragraph, ReportDocument
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from app.services.report_shapes import colour_hex, shape_svg
from app.services.report_svg import sanitize_svg
from tests.conftest import auth_headers
from tests.test_report_images import db, pdf_content, world  # noqa: F401 - the world and db fixtures

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="#cc3333"/></svg>'


def shape_tree(**keys: Any) -> dict[str, Any]:
    return {**empty_tree("document"), "nodes": [{"type": "shape", "shape": "rectangle", "width": 5, "height": 2, **keys}]}


def errors_of(tree: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(InvalidLayoutError) as caught:
        assert_valid(tree)
    return [(e.path, e.message) for e in caught.value.errors]


def picture_of(**keys: Any) -> Image:
    """The report-model picture the evaluator builds for a rounded shape, with `keys` overriding its settings."""
    node = {"type": "shape", "shape": "ellipse", "width": 4, "height": 4, "fill": "#336699", **keys}
    return Image(svg=shape_svg(node, accent="#112233"), decorative=True, width=4, height_cm=4, **{
        k: v for k, v in keys.items() if k in ("placement", "anchor", "offset_x_cm", "offset_y_cm", "align")
    })


# ---- the tree ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["rectangle", "rounded", "ellipse", "triangle", "line", "arrow"])
def test_every_preset_with_a_size_is_valid(kind):
    assert_valid(shape_tree(shape=kind))


def test_a_shape_with_every_setting_is_valid():
    assert_valid(shape_tree(
        shape="rounded", fill="#475569", outline="accent", outline_width=1.5, width=50, width_unit="mm", height=2, alt="A plate",
        placement="behind", anchor="page", offset_x=1, offset_y=-2,
    ))


def test_a_custom_shape_needs_svg_and_keeps_its_own_size_without_width_and_height():
    assert_valid({**empty_tree("document"), "nodes": [{"type": "shape", "shape": "custom", "svg": SVG}]})
    assert ("nodes[0].svg", "A custom shape needs its SVG markup.") in errors_of(
        {**empty_tree("document"), "nodes": [{"type": "shape", "shape": "custom"}]}
    )


@pytest.mark.parametrize(
    ("keys", "path"),
    [
        ({"shape": "star"}, "nodes[0].shape"),
        ({"width_unit": "percent"}, "nodes[0].width_unit"),
        ({"width": 0}, "nodes[0].width"),
        ({"height": 101}, "nodes[0].height"),
        ({"fill": "red"}, "nodes[0].fill"),
        ({"fill": "#12345"}, "nodes[0].fill"),
        ({"outline": "javascript:1"}, "nodes[0].outline"),
        ({"outline_width": 1}, "nodes[0].outline_width"),
        ({"outline": "black", "outline_width": 100}, "nodes[0].outline_width"),
        ({"svg": SVG}, "nodes[0].svg"),
        ({"alt": 5}, "nodes[0].alt"),
        ({"placement": "behind", "align": "left"}, "nodes[0].align"),
        ({"placement": "inline", "anchor": "page"}, "nodes[0].anchor"),
        ({"placement": "wrap"}, "nodes[0].align"),
        ({"caption": "no"}, "nodes[0].caption"),
    ],
)
def test_a_bad_shape_setting_is_refused_with_its_path(keys, path):
    assert path in [p for p, _ in errors_of(shape_tree(**keys))]


def test_a_preset_without_a_size_is_refused():
    tree = {**empty_tree("document"), "nodes": [{"type": "shape", "shape": "ellipse"}]}
    assert {p for p, _ in errors_of(tree)} == {"nodes[0].width", "nodes[0].height"}


@pytest.mark.parametrize("kind", ["line", "arrow"])
def test_a_line_is_coloured_by_its_outline_not_a_fill(kind):
    assert "nodes[0].fill" in [p for p, _ in errors_of(shape_tree(shape=kind, fill="#000000"))]
    assert "nodes[0].outline" in [p for p, _ in errors_of(shape_tree(shape=kind, outline="none"))]


@pytest.mark.parametrize(
    "svg",
    [
        "", "not svg", "<svg xmlns='http://www.w3.org/2000/svg'><rect width='1' height='1'/></svg>",
        '<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect fill="url(http://evil/x)" width="1" height="1"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect style="fill:url(//evil)" width="1" height="1"/></svg>',
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1' onload='alert(1)'>" + "x" * 50_000 + "</svg>",
    ],
)
def test_a_custom_svg_that_is_unsafe_malformed_or_unsized_is_refused(svg):
    assert "nodes[0].svg" in [p for p, _ in errors_of({**empty_tree("document"), "nodes": [{"type": "shape", "shape": "custom", "svg": svg}]})]


def test_a_shape_cannot_be_part_of_a_table_layout():
    tree = {**empty_tree("table"), "nodes": [{"type": "shape", "shape": "rectangle", "width": 1, "height": 1}]}
    with pytest.raises(InvalidLayoutError) as caught:
        assert_valid(tree)
    assert any("nodes[0]" in e.path for e in caught.value.errors)


# ---- the text view ----------------------------------------------------------------------------------------------


def test_the_text_view_round_trips_a_shape():
    tree = shape_tree(
        shape="rounded", fill="#475569", outline="black", outline_width=0.5, width=5, width_unit="cm", height=20, height_unit="mm",
        alt="A plate", placement="behind", anchor="page", offset_x=1, offset_y=-1.5,
    )
    text = format_tree(tree)
    assert "@shape rounded fill #475569 outline black outline_width 0.5 width 5 cm height 20 mm" in text
    parsed = parse_text(text)
    assert not parsed.errors and parsed.tree["nodes"] == tree["nodes"]


def test_the_text_view_round_trips_a_custom_svg():
    tree = {**empty_tree("document"), "nodes": [{"type": "shape", "shape": "custom", "svg": SVG, "width": 3}]}
    parsed = parse_text(format_tree(tree))
    assert not parsed.errors and parsed.tree["nodes"] == tree["nodes"]


@pytest.mark.parametrize(
    "line", ["@shape", "@shape star width", "@shape rectangle width wide", "@shape rectangle fill #fff fill #000", "@shape rectangle colour red"],
)
def test_the_text_view_reports_a_bad_shape_line(line):
    assert parse_text(line).errors


# ---- the drawing ------------------------------------------------------------------------------------------------


def test_colours_resolve_tokens_and_short_hex():
    assert colour_hex("accent", "#112233") == "#112233" and colour_hex("white", "#112233") == "#ffffff"
    assert colour_hex("black", "#112233") == "#000000" and colour_hex("#ABC", "#112233") == "#aabbcc"
    assert colour_hex("none", "#112233") is None


def test_a_preset_is_drawn_at_its_size_in_the_resolved_colours_and_is_safe_markup():
    svg = shape_svg({"shape": "rounded", "fill": "accent", "outline": "black", "outline_width": 1, "width": 5, "height": 20,
                     "height_unit": "mm"}, accent="#0a1b2c")
    assert 'fill="#0a1b2c"' in svg and 'stroke="#000000"' in svg and " rx=" in svg
    assert 'width="188.98"' in svg and 'height="75.59"' in svg
    assert sanitize_svg(svg)


@pytest.mark.parametrize(("kind", "element"), [("ellipse", "<ellipse"), ("triangle", "<polygon"), ("line", "<line"), ("arrow", "<polygon")])
def test_each_preset_draws_its_element(kind, element):
    assert element in shape_svg({"shape": kind, "width": 4, "height": 1}, accent="#112233")


# ---- the four formats -------------------------------------------------------------------------------------------


def document_with(*blocks: Image) -> ReportDocument:
    return ReportDocument(title="Shapes", blocks=[*blocks, Paragraph("text")])


def test_html_draws_a_shape_inline_and_a_layered_shape_over_the_page():
    html = render_html_document(document_with(
        picture_of(), picture_of(placement="behind", anchor="page", offset_x_cm=2, offset_y_cm=3),
    )).decode()
    assert html.count("<ellipse") == 2 and '<div class="layer-anchor behind">' in html and "left:2cm;top:3cm" in html


def plate(colour: str, **keys: Any) -> Image:
    svg = shape_svg({"shape": "rectangle", "width": 3, "height": 1, "fill": colour}, accent="#000000")
    return Image(svg=svg, decorative=True, width=3, height_cm=1, **keys)


def test_pdf_draws_a_shape_behind_the_text_and_one_in_front_as_vectors_in_document_order():
    content = pdf_content(render_pdf_document(document_with(
        plate("#ff0000", placement="behind", anchor="page", offset_x_cm=2, offset_y_cm=3),
        plate("#0000ff", placement="front", anchor="page", offset_x_cm=5, offset_y_cm=5),
    )))
    assert content.index("1 0 0 rg") < content.index("(Shapes) Tj") < content.index("(text) Tj") < content.index("0 0 1 rg")
    assert "<IMG>" not in content


def png_of_word_media(document: ReportDocument) -> list[PilImage.Image]:
    with zipfile.ZipFile(io.BytesIO(render_docx_document(document))) as docx:
        return [PilImage.open(io.BytesIO(docx.read(n))).convert("RGBA") for n in docx.namelist() if n.startswith("word/media/")]


def test_word_draws_a_shape_as_a_transparent_picture_sized_for_print():
    (image,) = png_of_word_media(document_with(picture_of()))
    assert image.getpixel((0, 0))[3] == 0 and image.getpixel((image.width // 2, image.height // 2))[:3] == (0x33, 0x66, 0x99)
    assert image.width == 472  # 4 cm at 300 dpi


def test_word_and_opendocument_keep_the_document_order_of_layers():
    document = document_with(picture_of(placement="behind", anchor="page"), picture_of(placement="behind", anchor="page", offset_x_cm=1))
    anchors = DocxDocument(io.BytesIO(render_docx_document(document))).element.body.xpath(".//wp:anchor")
    heights = [int(a.get("relativeHeight")) for a in anchors]
    assert len(heights) == 2 and heights[0] < heights[1]
    with zipfile.ZipFile(io.BytesIO(render_odt_document(document))) as odt:
        content = odt.read("content.xml").decode()
    assert content.index('draw:z-index="1"') < content.index('draw:z-index="2"')


def test_opendocument_draws_a_shape_as_a_frame():
    with zipfile.ZipFile(io.BytesIO(render_odt_document(document_with(picture_of(placement="front", anchor="margin"))))) as odt:
        assert "fr_front_margin" in odt.read("content.xml").decode()


# ---- a run ------------------------------------------------------------------------------------------------------


def preview(world, project: dict, tree: dict) -> dict:  # noqa: F811
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts/preview", json={"tree": tree}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_run_draws_a_shape_in_the_organisations_accent_and_a_custom_one_as_written(world, db):  # noqa: F811
    organization = db.get(Organization, uuid.UUID(world.org["id"]))
    organization.report_accent_color_hex = "#0a1b2c"
    db.commit()
    project = world.project("Alpha")
    tree = {**empty_tree("document"), "nodes": [
        {"type": "shape", "shape": "rounded", "width": 5, "height": 2, "placement": "behind", "anchor": "page"},
        {"type": "shape", "shape": "custom", "svg": SVG, "width": 3, "alt": "A red dot"},
    ]}
    html = preview(world, project, tree)["html"]
    assert 'class="layer-anchor behind"' in html and 'fill="#0a1b2c"' in html and "<circle" in html and 'aria-label="A red dot"' in html


def test_saving_a_layout_with_an_unsafe_custom_svg_is_refused_with_the_path(world):  # noqa: F811
    project = world.project("Alpha")
    bad = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect fill="url(http://evil/x)" width="1" height="1"/></svg>'
    body = {"name": "Bad", "description": "", "family": "document",
            "tree": {**empty_tree("document"), "nodes": [{"type": "shape", "shape": "custom", "svg": bad}]}}
    resp = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts", json=body, headers=auth_headers(world.token))
    assert resp.status_code == 422 and "nodes[0].svg" in resp.text
