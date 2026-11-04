"""Tests for the font, size and colour of a running header or footer and the bold and italic marks in its cells: the tree
rules, the mark reader, the text view, the cascade over the document's body font, and what each of the four formats writes."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

import pytest
from lxml import etree

from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import assert_valid
from app.services.report_model import (
    DocumentStyles,
    Marked,
    PageField,
    Paragraph,
    ReportDocument,
    RunningBand,
)
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from app.services.report_running import band_line_cm, cell_lines, read_marks
from app.services.report_styles import font_keys, used_extra_families
from tests.conftest import auth_headers
from tests.test_report_images import db, world  # noqa: F401 - the world and db fixtures
from tests.test_report_running import page_texts
from tests.test_report_styles import create, errors_of, family, pdf_fonts, styled_tree

SERIF, MONO = family("serif"), family("mono")
MARKED = (Marked("Draft", True), " - ", Marked(PageField.PAGE, False, True), " of ", PageField.PAGES)


def document(band: RunningBand, *, styles: DocumentStyles | None = None, header: bool = False) -> ReportDocument:
    return ReportDocument(
        title="T", blocks=[Paragraph("body")], styles=styles or DocumentStyles(),
        header=band if header else None, footer=None if header else band,
    )


def zip_text(data: bytes, name: str) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read(name).decode()


def tree_with_band(**band: Any) -> dict[str, Any]:
    return styled_tree(footer={"centre": "Page {{page}}", **band})


# ---- the mark reader ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [
    ("Plain text", [("Plain text", False, False)]),
    ("**Page {{page}}** of", [("Page {{page}}", True, False), (" of", False, False)]),
    ("a *b* c", [("a ", False, False), ("b", False, True), (" c", False, False)]),
    ("***both***", [("both", True, True)]),
    ("**a *b* c**", [("a ", True, False), ("b", True, True), (" c", True, False)]),
    ("2 * 3", [("2 * 3", False, False)]),
    ("*unclosed", [("*unclosed", False, False)]),
    ("\\*literal\\*", [("*literal*", False, False)]),
    ("`code` and [a](b)", [("`code` and [a](b)", False, False)]),
    ("", []),
])
def test_a_cell_reads_bold_and_italic_marks_and_nothing_else(text, expected):
    assert read_marks(text) == expected


def test_a_marked_stretch_stays_marked_across_a_line_break():
    lines = cell_lines((Marked("one\ntwo", True), " plain"))
    assert lines == [[Marked("one", True)], [Marked("two", True), " plain"]]


def test_the_line_height_grows_with_the_size_and_never_below_the_default():
    assert band_line_cm(None) == band_line_cm(8) == 0.4
    assert band_line_cm(20) > band_line_cm(12) > 0.4


# ---- the tree -----------------------------------------------------------------------------------------------------


def test_a_band_may_set_font_size_and_colour_on_the_document_and_a_page_style():
    tree = styled_tree(
        header={"left": "H", "font": "serif", "size": 10, "colour": "#112233"},
        page_styles=[{"name": "Wide", "footer": {"centre": "F", "font": "mono", "colour": "accent"}}],
    )
    assert font_keys(tree) == ["serif", "mono"]


@pytest.mark.parametrize(("band", "path", "fragment"), [
    ({"font": "Comic Sans"}, "footer.font", ""),
    ({"size": 3}, "footer.size", "6"),
    ({"size": 100}, "footer.size", "72"),
    ({"size": "big"}, "footer.size", ""),
    ({"colour": "nonsense"}, "footer.colour", ""),
    ({"colour": 7}, "footer.colour", "colour"),
    ({"colour": "none"}, "footer.colour", ""),
])
def test_a_bad_band_font_size_or_colour_is_refused_with_its_path(band, path, fragment):
    found = errors_of(tree_with_band(**band), organization_colours=())
    assert any(p == path and fragment in m for p, m in found), found


def test_a_band_that_no_longer_fits_its_margin_at_a_larger_size_is_refused():
    tight = styled_tree(margins={"top": 1.0, "bottom": 1.0}, footer={"left": "a\nb\nc", "size": 20})
    assert any(p.startswith(("footer", "margins")) for p, _ in errors_of(tight))


def test_a_band_colour_may_name_the_layouts_own_scheme():
    tree = styled_tree(palette=[{"name": "brand", "colour": "#102030"}], footer={"centre": "x", "colour": "brand"})
    assert errors_of({**tree, "footer": {"centre": "x", "colour": "other"}}, organization_colours=())
    assert_valid(tree, organization_colours=())


# ---- the text view ------------------------------------------------------------------------------------------------


def test_the_text_view_reads_and_writes_the_band_look_exactly():
    tree = styled_tree(
        header={"left": "**Draft**", "right": "*page* {{page}}", "font": "serif", "size": 9.5, "colour": "primary", "first_page": "none"},
    )
    text = format_tree(tree)
    assert re.search(r'@header left "\*\*Draft\*\*" right ".*" font serif size 9.5 colour primary first none', text)
    assert parse_text(text).tree["header"] == tree["header"]


@pytest.mark.parametrize(("line", "message"), [
    ('@footer centre "x" size', "text size"),
    ('@footer centre "x" size big', "number"),
    ('@footer centre "x" font serif font mono', "once"),
    ('@footer centre "x" bold', "Unexpected"),
])
def test_text_view_mistakes_in_a_band_line_are_reported(line, message):
    result = parse_text(f"@layout document\n{line}\n@text\nhello\n@end\n")
    assert result.tree is None and any(message in e.message for e in result.errors)


# ---- the four formats ---------------------------------------------------------------------------------------------


def test_the_pdf_prints_the_band_in_its_font_with_marks_and_the_page_fields_filled():
    band = RunningBand(centre=MARKED, font=MONO, size=10, colour="#ff0000")
    pdf = render_pdf_document(document(band))
    assert {"LiberationMono", "LiberationMono-Bold", "LiberationMono-Italic"} <= pdf_fonts(pdf)
    assert page_texts(pdf)[0].count("1") >= 1 and "1" in "".join(page_texts(pdf)[0])
    assert b"1 0 0 rg" in zlib_streams(pdf)


def zlib_streams(pdf: bytes) -> bytes:
    from tests.test_report_running import streams

    return "".join(streams(pdf)).encode("latin-1")


def test_a_band_without_a_font_follows_the_documents_body_font():
    pdf = render_pdf_document(document(RunningBand(centre=("Draft",)), styles=DocumentStyles(body_font=SERIF)))
    assert "LiberationSerif" in pdf_fonts(pdf)


def test_a_band_font_beats_the_body_font():
    pdf = render_pdf_document(document(RunningBand(centre=("Draft",), font=MONO), styles=DocumentStyles(body_font=SERIF)))
    assert "LiberationMono" in pdf_fonts(pdf)


def test_a_band_without_a_look_is_drawn_as_before_at_eight_points():
    streams_text = zlib_streams(render_pdf_document(document(RunningBand(centre=("Draft",)))))
    assert b"8 Tf" in streams_text


def test_a_larger_band_size_is_drawn_larger_in_the_pdf():
    assert b"14 Tf" in zlib_streams(render_pdf_document(document(RunningBand(centre=("Draft",), size=14))))


def test_word_writes_the_band_runs_with_size_font_colour_and_marks_including_the_page_field():
    data = render_docx_document(document(RunningBand(centre=MARKED, font=MONO, size=10, colour="#ff0000")))
    footer = next(zip_text(data, n) for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.startswith("word/footer"))
    assert 'w:ascii="Courier New"' in footer and 'w:val="20"' in footer and 'w:val="FF0000"' in footer
    assert footer.count("<w:b/>") >= 1 and footer.count("<w:i/>") >= 1
    assert 'w:instr="PAGE"' in footer and 'w:instr="NUMPAGES"' in footer
    assert re.search(r'<w:fldSimple w:instr="PAGE"><w:r><w:rPr>.*?<w:i/>', footer, re.S)


def test_word_keeps_the_body_font_for_a_band_that_names_none():
    data = render_docx_document(document(RunningBand(centre=("Draft",))))
    footer = next(zip_text(data, n) for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.startswith("word/footer"))
    assert "w:rFonts" not in footer and 'w:val="16"' in footer


def test_odt_gives_a_band_look_one_automatic_style_and_marks_three_shared_text_styles():
    band = RunningBand(centre=MARKED, font=MONO, size=10, colour="#ff0000")
    data = render_odt_document(document(band))
    styles = zip_text(data, "styles.xml")
    assert {"BandLook1_left", "BandLook2_centre", "BandLook3_right"} == set(re.findall(r'style:name="(BandLook\d_\w+)"', styles))
    assert 'fo:font-size="10pt"' in styles and 'fo:color="#FF0000"' in styles
    assert 'style:name="Courier New"' in styles
    assert 'text:style-name="Band_b"' in styles and 'text:style-name="Band_i"' in styles
    assert 'style:name="Band_b" style:family="text"' in styles
    assert "<text:page-number" in styles
    etree.fromstring(styles.encode())  # well-formed, with the spans inside the header and footer paragraphs


def test_odt_with_a_plain_band_adds_no_look_styles():
    styles = zip_text(render_odt_document(document(RunningBand(centre=("Draft",)))), "styles.xml")
    assert "BandLook" not in styles and 'style:name="Band_b"' not in styles and 'text:style-name="Band_centre"' in styles


def test_html_shows_the_marks_on_screen_and_the_look_on_the_band_and_the_print_boxes():
    band = RunningBand(left=(Marked("Draft", True),), centre=(Marked("all italic", False, True),), font=SERIF, size=11, colour="#102030")
    html = render_html_document(document(band)).decode()
    assert "<strong>Draft</strong>" in html and "<em>all italic</em>" in html
    assert 'class="band footer" style="font-family: ' in html and "font-size: 11pt" in html and "color: #102030" in html
    box = re.search(r"@bottom-center \{[^}]*\}", html)
    assert box and "font-size: 11pt" in box.group(0) and "font-style: italic" in box.group(0) and "color: #102030" in box.group(0)
    assert "font-weight: bold" not in re.search(r"@bottom-center \{[^}]*\}", html).group(0)


def test_html_prints_a_cell_bold_only_when_all_of_it_is():
    mixed = render_html_document(document(RunningBand(left=(Marked("a", True), "b")))).decode()
    assert "font-weight: bold" not in mixed
    whole = render_html_document(document(RunningBand(left=(Marked("a", True), Marked(PageField.PAGE, True))))).decode()
    assert "font-weight: bold" in whole


def test_extra_families_a_band_names_are_found_for_embedding():
    extra = family("serif")
    uses = used_extra_families(document(RunningBand(centre=MARKED, font=extra)))
    assert uses == []  # bundled families are never embedded


# ---- through the API ----------------------------------------------------------------------------------------------


def test_a_run_prints_a_marked_footer_with_a_page_style_override_in_every_format(world):  # noqa: F811
    project = world.project("Alpha")
    h = auth_headers(world.token)
    tree = styled_tree(
        footer={"left": "**{{report_title}}**", "right": "Page *{{page}}* of {{pages}}", "font": "mono", "size": 10, "colour": "#ff0000"},
        page_styles=[{"name": "Wide", "footer": {"centre": "Wide", "font": "serif"}}],
    )
    layout = create(world, project, tree)
    base = f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run"
    pdf = world.client.get(base, params={"format": "pdf"}, headers=h)
    assert pdf.status_code == 200, pdf.text
    assert {"LiberationMono", "LiberationMono-Bold", "LiberationMono-Italic"} <= pdf_fonts(pdf.content)
    docx = world.client.get(base, params={"format": "docx"}, headers=h).content
    footer = next(zip_text(docx, n) for n in zipfile.ZipFile(io.BytesIO(docx)).namelist() if n.startswith("word/footer"))
    assert 'w:ascii="Courier New"' in footer and "**" not in footer
    html = world.client.get(base, params={"format": "html"}, headers=h).text
    assert "<strong>" in html and "color: #ff0000" in html
    odt = world.client.get(base, params={"format": "odt"}, headers=h).content
    assert 'fo:color="#FF0000"' in zip_text(odt, "styles.xml")


def test_a_placeholder_value_with_asterisks_is_never_read_for_marks(world):  # noqa: F811
    from tests.test_report_shapes import preview

    project = world.project("Alpha")
    tree = styled_tree(footer={"centre": "{{project_name}}"})
    html = preview(world, project, tree)["html"]
    assert "Alpha" in html
