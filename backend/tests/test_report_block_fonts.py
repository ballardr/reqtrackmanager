"""Tests for a text or heading block's own font and size (and a heading's colour), and for the bold, italic and code marks a
heading's words take: the tree rules, the text view, the cascade over the layout's styles, and what each of the four formats
actually writes."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import replace
from typing import Any

import pytest

from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_model import (
    BulletList,
    DocumentStyles,
    Heading,
    MathText,
    NumberedList,
    Paragraph,
    ReportDocument,
    Styled,
    finalize_links,
    inline_markdown,
)
from app.services.report_odt import render_odt_document
from app.services.report_pdf import _look_for, render_pdf_document
from app.services.report_styles import font_keys, used_extra_families
from tests.conftest import auth_headers
from tests.test_report_images import db, world  # noqa: F401 - the world and db fixtures
from tests.test_report_styles import (
    create,
    errors_of,
    family,
    pdf_fonts,
    styled_tree,
    word_styles,
)

MONO, SERIF = family("mono"), family("serif")


def tree_with(*nodes: dict[str, Any], styles: dict[str, Any] | None = None) -> dict[str, Any]:
    tree = styled_tree(styles)
    tree["nodes"] = list(nodes)
    return tree


def document(*blocks: Any, styles: DocumentStyles | None = None) -> ReportDocument:
    return ReportDocument(title="Title", blocks=list(blocks), styles=styles or DocumentStyles())


def content_xml(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("content.xml").decode()


def body_xml(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()


# ---- the tree ----------------------------------------------------------------------------------------------------


def test_a_block_may_set_its_own_font_size_and_a_heading_its_colour():
    from app.services.report_layout_tree import assert_valid

    assert_valid(tree_with(
        {"type": "heading", "text": "T", "level": 2, "font": "serif", "size": 18, "colour": "accent"},
        {"type": "text", "text": "Body", "font": "x-house-face", "size": 9.5},
    ))


@pytest.mark.parametrize(("node", "path", "text"), [
    ({"type": "text", "text": "x", "font": "Times"}, "nodes[0].font", "Must be a font"),
    ({"type": "text", "text": "x", "size": 5}, "nodes[0].size", "from 6 to 72"),
    ({"type": "text", "text": "x", "size": "11"}, "nodes[0].size", "number of points"),
    ({"type": "text", "text": "x", "size": 10.2}, "nodes[0].size", "whole or half"),
    ({"type": "text", "text": "x", "colour": "accent"}, "nodes[0].colour", "Unknown key"),
    ({"type": "heading", "text": "x", "font": 3}, "nodes[0].font", "Must be a font"),
    ({"type": "heading", "text": "x", "size": 73}, "nodes[0].size", "from 6 to 72"),
    ({"type": "heading", "text": "x", "colour": "none"}, "nodes[0].colour", "Must be a hex colour"),
    ({"type": "heading", "text": "x", "colour": "Red!"}, "nodes[0].colour", "Must be a hex colour"),
])
def test_a_bad_block_font_size_or_colour_is_refused_with_its_path(node, path, text):
    assert any(p == path and text in m for p, m in errors_of(tree_with(node)))


def test_the_fonts_a_tree_names_include_those_of_blocks_at_any_depth():
    tree = tree_with(
        {"type": "text", "text": "x", "font": "mono"},
        {"type": "section", "page_style": "A", "children": [{"type": "heading", "text": "y", "font": "x-house-face"}]},
        styles={"body": {"font": "serif"}},
    )
    assert font_keys(tree) == ["serif", "mono", "x-house-face"]


# ---- the text view -----------------------------------------------------------------------------------------------


def test_the_text_view_reads_and_writes_block_fonts_exactly():
    text = (
        "@layout document\n\n"
        "@heading level=2 font=serif size=18 colour=primary A *title*\n\n"
        "@text font=mono size=9\nSome text\n@end\n\n"
        '@text size=11 "quoted"\n'
    )
    parsed = parse_text(text)
    assert not parsed.errors
    nodes = parsed.tree["nodes"]
    assert nodes[0] == {"type": "heading", "level": 2, "font": "serif", "size": 18, "colour": "primary", "text": "A *title*"}
    assert nodes[1] == {"type": "text", "font": "mono", "size": 9, "text": "Some text"}
    assert nodes[2] == {"type": "text", "size": 11, "text": "quoted"}
    assert parse_text(format_tree(parsed.tree)).tree == parsed.tree


def test_a_text_block_without_a_look_is_still_written_as_plain_prose():
    tree = tree_with({"type": "text", "text": "Just words"})
    assert "@text" not in format_tree(tree)


@pytest.mark.parametrize(("line", "message"), [
    ("@heading size=big Title", "number of points"),
    ("@heading font= Title", "Write a font after font="),
    ("@heading colour= Title", "Write a colour after colour="),
    ("@heading size=9 size=10 Title", "given twice"),
    ("@heading level=x Title", "level must be a number"),
    ("@text colour=red\nbody\n@end", "Write @text on its own line"),
])
def test_text_view_mistakes_in_a_block_line_are_reported(line, message):
    result = parse_text(f"@layout document\n\n{line}\n")
    assert any(message in e.message for e in result.errors)


def test_a_heading_that_starts_like_an_attribute_is_quoted_so_it_reads_back_as_words():
    tree = tree_with({"type": "heading", "text": "font=bold is a style", "font": "serif"})
    assert parse_text(format_tree(tree)).tree["nodes"] == tree["nodes"]


# ---- marks in a heading ------------------------------------------------------------------------------------------


def test_a_heading_reads_bold_italic_and_code_marks_and_nothing_else():
    text = inline_markdown("A *word* and **bold** and `code`")
    assert isinstance(text, MathText) and str(text) == "A word and bold and code"
    assert [p for p in text.parts if isinstance(p, Styled)] == [
        Styled("word", italic=True), Styled("bold", bold=True), Styled("code", code=True),
    ]
    for plain in ("1. Not a list", "# Not a heading", "- Not a bullet", "a * b", "Plain words"):
        assert inline_markdown(plain) == plain and not isinstance(inline_markdown(plain), MathText)


def test_an_equation_in_a_heading_is_kept_unread_by_the_marks():
    text = inline_markdown(r"Area \(a*b*c\) is **big**")
    assert r"\(a*b*c\)" in str(text)


def test_marks_in_a_heading_reach_all_four_formats():
    heading = Heading(MathText(["Plan ", Styled("now", italic=True), " ", Styled("big", bold=True), " ", Styled("x", code=True)]), 1)
    doc = document(heading, styles=DocumentStyles(heading_bold=False))
    assert {"Helvetica-Oblique", "Helvetica-Bold", "Courier"} <= pdf_fonts(render_pdf_document(doc))
    word = body_xml(render_docx_document(doc))
    assert re.search(r"<w:i[ />].*?<w:t[^>]*>now</w:t>", word, re.S) and re.search(r"<w:b[ />].*?<w:t[^>]*>big</w:t>", word, re.S)
    assert "<text:span" in content_xml(render_odt_document(doc)) and "T_Italic" in content_xml(render_odt_document(doc))
    html = render_html_document(doc).decode()
    assert "<em>now</em>" in html or "<i>now</i>" in html
    assert "<code>x</code>" in html


def test_the_anchor_and_contents_words_of_a_heading_carry_no_marks():
    doc = finalize_links(document(Heading(MathText(["Plan ", Styled("now", italic=True)]), 1)))
    assert doc.blocks[0].anchor == "plan-now" and str(doc.blocks[0].text) == "Plan now"


# ---- the neutral model --------------------------------------------------------------------------------------------


def test_a_block_look_survives_the_link_check_that_rebuilds_text_blocks():
    blocks = [
        Paragraph("p", MONO, 9), BulletList(["a"], SERIF, 11), NumberedList(["b"], MONO, 8),
        Heading("h", 1, font=MONO, size=20, colour="#ff0000"),
    ]
    kept = finalize_links(document(*blocks)).blocks
    assert [(b.font, b.size) for b in kept] == [(MONO, 9), (SERIF, 11), (MONO, 8), (MONO, 20)]
    assert kept[3].colour == "#ff0000"


# ---- PDF ---------------------------------------------------------------------------------------------------------


def test_a_block_without_a_look_is_drawn_as_before():
    look = _look_for(DocumentStyles())
    assert look.body_for(None, None) is look.body
    assert pdf_fonts(render_pdf_document(document(Paragraph("x"), Heading("h", 1)))) == {"Helvetica", "Helvetica-Bold"}


def test_a_paragraph_list_and_heading_take_their_own_font_and_size_in_the_pdf():
    look = _look_for(DocumentStyles())
    assert look.body_for(MONO, 14).fontSize == 14 and look.body_for(MONO, 14).leading == pytest.approx(16.8)
    assert look.body_for(MONO, None).fontSize == look.body.fontSize
    heading = look.heading_for(Heading("h", 2, font=SERIF, size=30, colour="#00ff00"))
    assert heading.fontSize == 30 and heading.textColor.hexval() == "0x00ff00" and heading.fontName == "Report-serif-bold"
    plain = look.heading_for(Heading("h", 2))
    assert plain is look.headings[2]
    fonts = pdf_fonts(render_pdf_document(document(
        Paragraph("mono body", MONO, 9), BulletList(["serif item"], SERIF, 12), Heading("Serif heading", 1, font=SERIF),
    )))
    assert {"LiberationMono", "LiberationSerif", "LiberationSerif-Bold"} <= fonts


def test_a_block_font_beats_the_layouts_and_the_layout_beats_the_default():
    styles = DocumentStyles(body_font=SERIF)
    fonts = pdf_fonts(render_pdf_document(document(Paragraph("layout serif"), Paragraph("own mono", MONO), styles=styles)))
    assert {"LiberationSerif", "LiberationMono"} <= fonts


def test_a_block_size_alone_keeps_the_documents_font():
    styles = DocumentStyles(body_font=SERIF, body_size=11)
    fonts = pdf_fonts(render_pdf_document(document(Paragraph("bigger", None, 20), styles=styles)))
    assert "LiberationSerif" in fonts and "LiberationMono" not in fonts
    look = _look_for(styles)
    assert look.body_for(None, 20).fontName == look.body.fontName and look.body_for(None, 20).fontSize == 20


# ---- Word --------------------------------------------------------------------------------------------------------


def test_word_writes_a_block_look_on_the_runs_of_that_block_only():
    data = render_docx_document(document(
        Paragraph("plain words"), Paragraph("mono words", MONO, 9), BulletList(["bullet"], SERIF, 12),
        Heading("Big heading", 1, font=SERIF, size=30, colour="#ff0000"),
    ))
    body = body_xml(data)
    plain = re.search(r"<w:p>.*?plain words.*?</w:p>", body, re.S).group(0)
    assert "<w:rFonts" not in plain and "<w:sz " not in plain
    mono = re.search(r"<w:p>(?:(?!</w:p>).)*mono words.*?</w:p>", body, re.S).group(0)
    assert 'w:ascii="Courier New"' in mono and 'w:val="18"' in mono
    bullet = re.search(r"<w:p>(?:(?!</w:p>).)*bullet.*?</w:p>", body, re.S).group(0)
    assert 'w:ascii="Times New Roman"' in bullet and 'w:val="24"' in bullet
    heading = re.search(r"<w:p>(?:(?!</w:p>).)*Big heading.*?</w:p>", body, re.S).group(0)
    assert 'w:val="60"' in heading and 'w:val="FF0000"' in heading and 'w:ascii="Times New Roman"' in heading
    assert 'w:val="Heading1"' in heading  # the level is unchanged: the contents list still finds it
    assert word_styles(data) is not None


# ---- OpenDocument ------------------------------------------------------------------------------------------------


def test_odt_gives_each_distinct_look_one_automatic_style_over_the_parent():
    data = render_odt_document(document(
        Paragraph("one", MONO, 9), Paragraph("two", MONO, 9), BulletList(["b"], SERIF, 12), NumberedList(["n"], None, 13),
        Heading("Head", 2, font=SERIF, size=24, colour="#ff0000"),
    ))
    xml = content_xml(data)
    assert xml.count('style:name="P_Own') == 4  # the two equal paragraphs share one
    assert re.search(
        r'style:name="P_Own1" style:family="paragraph" style:parent-style-name="Standard">'
        r'<style:text-properties style:font-name="Courier New" fo:font-size="9pt"', xml,
    )
    assert 'style:parent-style-name="List_20_Bullet"' in xml and 'style:parent-style-name="List_20_Number"' in xml
    assert re.search(r'<text:h text:style-name="P_Own\d" text:outline-level="2">', xml)  # the outline level is unchanged
    assert 'fo:color="#FF0000"' in xml
    assert 'style:name="Courier New"' in xml and 'style:name="Times New Roman"' in xml  # both declared in the part that uses them


def test_odt_with_no_block_look_adds_no_styles():
    assert "P_Own" not in content_xml(render_odt_document(document(Paragraph("x"), Heading("h", 1))))


# ---- HTML --------------------------------------------------------------------------------------------------------


def test_html_sets_validated_inline_css_only_on_blocks_that_set_a_look():
    html = render_html_document(document(
        Paragraph("plain"), Paragraph("own", MONO, 9), NumberedList(["n"], SERIF, None), Heading("Head", 1, font=SERIF, size=20, colour="#ff0000"),
    )).decode()
    assert "<p>plain</p>" in html
    assert '<p style="font-family: &quot;Courier New&quot;, monospace; font-size: 9pt">own</p>' in html
    assert '<ol style="font-family: &quot;Times New Roman&quot;, serif">' in html
    assert re.search(r'<h2 id="head" style="font-family: &quot;Times New Roman&quot;, serif; font-size: 20pt; color: #ff0000">Head</h2>', html)


# ---- embedding ----------------------------------------------------------------------------------------------------


def test_bundled_block_fonts_are_never_asked_to_be_embedded():
    assert used_extra_families(document(Paragraph("x", MONO, 9), Heading("h", 1, font=SERIF))) == []


def test_an_extra_family_named_only_by_a_block_is_found_for_embedding():
    extra = replace(MONO, key="x-house", bundled=False, faces_found=("regular", "bold"))
    uses = used_extra_families(document(Paragraph(MathText(["a ", Styled("b", bold=True)]), extra, 9)))
    assert [u.family.key for u in uses] == ["x-house"] and {"regular", "bold"} <= uses[0].styles


# ---- a run through the API ---------------------------------------------------------------------------------------


def test_a_run_prints_each_blocks_own_look_over_the_layouts_in_every_format(world):  # noqa: F811
    project = world.project("Alpha")
    h = auth_headers(world.token)
    layout = create(world, project, tree_with(
        {"type": "heading", "text": "Plan *now* and **big**", "level": 1, "font": "mono", "size": 22, "colour": "#ff0000"},
        {"type": "text", "text": "Mono body", "font": "mono", "size": 9},
        {"type": "text", "text": "Layout body"},
        styles={"body": {"font": "serif", "size": 12}, "headings": {"bold": False}},
    ))
    base = f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run"
    pdf = world.client.get(base, params={"format": "pdf"}, headers=h)
    assert pdf.status_code == 200, pdf.text
    fonts = pdf_fonts(pdf.content)
    assert {"LiberationSerif", "LiberationMono", "LiberationMono-Italic"} <= fonts
    docx = world.client.get(base, params={"format": "docx"}, headers=h).content
    body = body_xml(docx)
    assert 'w:ascii="Courier New"' in body and 'w:val="44"' in body and 'w:val="FF0000"' in body
    assert "Plan " in body and ">now<" in body and "**" not in body and "*now*" not in body
    html = world.client.get(base, params={"format": "html"}, headers=h).text
    assert "font-size: 22pt" in html and ("<em>now</em>" in html or "<i>now</i>" in html)
    odt = world.client.get(base, params={"format": "odt"}, headers=h).content
    assert 'fo:font-size="22pt"' in content_xml(odt)


def test_a_block_naming_a_font_the_server_lacks_prints_in_the_standard_one_with_a_run_note(world):  # noqa: F811
    from tests.test_report_shapes import preview

    project = world.project("Alpha")
    result = preview(world, project, tree_with({"type": "text", "text": "hello", "font": "x-house-face"}))
    assert any("x-house-face" in w for w in result["warnings"])
    assert "hello" in result["html"]


def test_validate_and_save_warn_about_a_block_font_the_server_lacks(world):  # noqa: F811
    project = world.project("Alpha")
    h = auth_headers(world.token)
    tree = tree_with({"type": "heading", "text": "T", "font": "x-house-face"})
    check = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts/validate", json={"tree": tree}, headers=h).json()
    assert check["ok"] is True and len(check["warnings"]) == 1 and "x-house-face" in check["warnings"][0]


def test_a_placeholder_inside_a_heading_mark_is_filled_after_the_marks_are_read(world):  # noqa: F811
    from tests.test_report_shapes import preview

    project = world.project("Alpha")
    result = preview(world, project, tree_with({"type": "heading", "text": "**{{report_title}}** for *{{project_name}}*"}))
    html = result["html"]
    assert "<strong>" in html or "<b>" in html
    assert "{{" not in html and ("<em>Alpha</em>" in html or "<i>Alpha</i>" in html)
