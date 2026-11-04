"""Tests for a layout's document styles (`styles`, `embed_fonts`): the tree rules, the text view, the run, and the font,
size and heading colour each of the four formats actually writes. Fonts come from the bundled families and a copy of
Liberation Mono mounted as an administrator-provided family."""

from __future__ import annotations

import io
import re
import shutil
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from lxml import etree
from sqlalchemy import select

from app.config import get_settings
from app.models.generated_report import GeneratedReport
from app.models.organization import Organization
from app.services import report_font_catalogue as catalogue
from app.services import report_fonts
from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import InvalidLayoutError, assert_valid, empty_tree
from app.services.report_model import (
    BulletList,
    DocumentStyles,
    Heading,
    Note,
    Paragraph,
    ReportDocument,
    Table,
)
from app.services.report_odt import render_odt_document
from app.services.report_pdf import _look_for, render_pdf_document
from app.services.report_styles import resolve_styles, used_extra_families
from tests.conftest import auth_headers
from tests.test_report_images import db, world  # noqa: F401 - the world and db fixtures
from tests.test_report_shapes import preview

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_LIBERATION = Path(report_fonts.__file__).resolve().parent.parent / "assets" / "report_fonts"
CYRILLIC = "Привет мир"


def styled_tree(styles: dict[str, Any] | None = None, **keys: Any) -> dict[str, Any]:
    tree = {**empty_tree("document"), "nodes": [{"type": "heading", "text": "Intro", "level": 1}, {"type": "text", "text": "Body"}], **keys}
    if styles is not None:
        tree["styles"] = styles
    return tree


def errors_of(tree: dict[str, Any], **kwargs: Any) -> list[tuple[str, str]]:
    with pytest.raises(InvalidLayoutError) as caught:
        assert_valid(tree, **kwargs)
    return [(e.path, e.message) for e in caught.value.errors]


def family(key: str) -> report_fonts.FontFamily:
    return report_fonts.get_family(key)


def pdf_fonts(pdf: bytes) -> set[str]:
    """The base font names the PDF refers to, without the subset prefix."""
    names = set()
    for chunk in pdf.split(b"/BaseFont /")[1:]:
        names.add(chunk.split(b"\n")[0].split(b" ")[0].decode("latin-1").split("+")[-1])
    return names


BLOCKS = [
    Heading("Intro", 1), Paragraph("Body *it* **bold**"), BulletList(["one", "two"]),
    Table(["A", "B"], [["x", "y"]], compact=True), Note("A note"),
]


def document(styles: DocumentStyles, blocks: list | None = None) -> ReportDocument:
    return ReportDocument(title="Title", blocks=list(blocks or BLOCKS), styles=styles)


# ---- the tree ----------------------------------------------------------------------------------------------------


def test_a_valid_styles_object_is_accepted():
    assert_valid(styled_tree({
        "body": {"font": "serif", "size": 11.5},
        "headings": {"font": "x-courier-prime", "bold": False, "italic": True, "colour": "primary"},
    }, embed_fonts=True))


@pytest.mark.parametrize(("styles", "path", "text"), [
    ({}, "styles", "Leave the key out"),
    ({"body": {}}, "styles.body", "Leave the key out"),
    ({"footer": {"font": "sans"}}, "styles.footer", "Unknown key"),
    ({"body": {"font": "Times New Roman"}}, "styles.body.font", "Must be a font"),
    ({"body": {"font": "../etc/passwd"}}, "styles.body.font", "Must be a font"),
    ({"body": {"size": 5.5}}, "styles.body.size", "from 6 to 72"),
    ({"body": {"size": 73}}, "styles.body.size", "from 6 to 72"),
    ({"body": {"size": 10.3}}, "styles.body.size", "whole or half"),
    ({"body": {"size": "11"}}, "styles.body.size", "number of points"),
    ({"body": {"size": True}}, "styles.body.size", "number of points"),
    ({"body": {"colour": "red"}}, "styles.body.colour", "Unknown key"),
    ({"headings": {"size": 12}}, "styles.headings.size", "Unknown key"),
    ({"headings": {"colour": "none"}}, "styles.headings.colour", "Must be a hex colour"),
    ({"headings": {"colour": "Red!"}}, "styles.headings.colour", "Must be a hex colour"),
    ({"headings": {"bold": "yes"}}, "styles.headings.bold", "true or false"),
    ({"headings": {"italic": 1}}, "styles.headings.italic", "true or false"),
    ("serif", "styles", "Must be an object"),
])
def test_a_bad_styles_value_is_refused_with_its_path(styles, path, text):
    assert any(p == path and text in m for p, m in errors_of(styled_tree(styles)))


def test_a_scheme_name_is_checked_where_the_organisations_names_are_known():
    tree = styled_tree({"headings": {"colour": "ghost"}})
    assert_valid(tree)  # a well formed name is accepted unchecked where the organisation is not at hand
    assert any(p == "styles.headings.colour" and "no colour called ghost" in m for p, m in errors_of(tree, organization_colours=[]))
    assert_valid(tree, organization_colours=["ghost"])
    assert_valid(styled_tree({"headings": {"colour": "ghost"}}, palette=[{"name": "ghost", "colour": "#112233"}]), organization_colours=[])


def test_an_extra_font_key_that_the_server_lacks_is_well_formed_so_a_moved_layout_still_saves():
    assert_valid(styled_tree({"body": {"font": "x-some-house-face"}}))


def test_styles_and_embed_fonts_belong_to_document_layouts_only():
    table = {**empty_tree("table"), "styles": {"body": {"font": "sans"}}, "embed_fonts": True}
    paths = {p for p, _ in errors_of(table)}
    assert {"styles", "embed_fonts"} <= paths
    assert any(p == "embed_fonts" and "true or false" in m for p, m in errors_of(styled_tree(embed_fonts="yes")))


# ---- the text view -----------------------------------------------------------------------------------------------


TEXT = """@layout document A4 embedfonts
@style body font=serif size=11.5
@style headings font=x-courier-prime colour=primary bold italic

# Intro
"""


def test_the_text_view_reads_and_writes_the_styles_exactly():
    parsed = parse_text(TEXT)
    assert parsed.ok, parsed.errors
    assert parsed.tree["styles"] == {
        "body": {"font": "serif", "size": 11.5},
        "headings": {"font": "x-courier-prime", "colour": "primary", "bold": True, "italic": True},
    }
    assert parsed.tree["embed_fonts"] is True
    assert parse_text(format_tree(parsed.tree)).tree == parsed.tree


def test_a_switch_that_is_off_is_written_and_read_back_as_off():
    tree = {**empty_tree("document"), "styles": {"headings": {"bold": False, "italic": False}}, "embed_fonts": False, "nodes": []}
    text = format_tree(tree)
    assert "nobold noitalic" in text and "noembedfonts" in text
    assert parse_text(text).tree == tree


@pytest.mark.parametrize(("text", "message"), [
    ("@layout document\n@style body\n", "Write at least one setting"),
    ("@layout document\n@style footer font=sans\n", "Write @style body"),
    ("@layout document\n@style body font=serif\n@style body size=9\n", "@style body is written once"),
    ("@layout document\n@style body colour=primary\n", "Unknown or empty setting"),
    ("@layout document\n@style body bold\n", "Expected font, size"),
    ("@layout document\n@style headings bold nobold\n", "given twice"),
    ("@layout document\n@style body size=abc\n", "number of points"),
    ("@layout document\n# Intro\n@style body font=serif\n", "before the first block"),
])
def test_text_view_mistakes_are_reported_on_their_line(text, message):
    result = parse_text(text)
    assert not result.ok and any(message in e.message for e in result.errors)


def test_the_tree_rules_reach_the_text_view_with_a_line():
    result = parse_text("@layout document\n@style body size=5\n")
    assert not result.ok and [(e.line, "from 6 to 72" in e.message) for e in result.errors] == [(2, True)]
    assert any("Only a document layout" in e.message for e in parse_text("@layout table\n@style body font=serif\n").errors)


# ---- PDF ---------------------------------------------------------------------------------------------------------


def test_a_document_with_no_styles_keeps_the_built_in_look():
    look = _look_for(DocumentStyles())
    assert look.body.fontName == "Helvetica" and look.body.fontSize == 10
    assert pdf_fonts(render_pdf_document(document(DocumentStyles()))) == {"Helvetica", "Helvetica-Bold"}


def test_the_body_family_sets_text_lists_tables_and_notes_in_the_pdf():
    fonts = pdf_fonts(render_pdf_document(document(DocumentStyles(body_font=family("serif")))))
    assert {"LiberationSerif", "LiberationSerif-Bold"} <= fonts
    assert "Helvetica-Bold" not in fonts  # headings follow the body family when they have none


def test_a_heading_font_of_its_own_gives_the_headings_that_face_and_leaves_the_body():
    styles = DocumentStyles(body_font=family("serif"), heading_font=family("mono"), heading_italic=True, heading_bold=False)
    fonts = pdf_fonts(render_pdf_document(document(styles)))
    assert "LiberationMono-Italic" in fonts and "LiberationSerif" in fonts


def test_the_body_size_is_the_text_size_and_headings_keep_their_ratio():
    plain, big = _look_for(DocumentStyles()), _look_for(DocumentStyles(body_size=20))
    assert big.body.fontSize == 20 and big.body.leading == 24
    assert big.headings[1].fontSize == pytest.approx(plain.headings[1].fontSize * 2)
    assert big.cell.fontSize == plain.cell.fontSize  # a table keeps its own size


def test_headings_set_italic_or_not_bold_with_no_font_use_the_matching_helvetica_face():
    both = pdf_fonts(render_pdf_document(document(DocumentStyles(heading_italic=True), [Heading("Intro", 1)])))
    assert "Helvetica-BoldOblique" in both
    italic_only = pdf_fonts(render_pdf_document(document(DocumentStyles(heading_italic=True, heading_bold=False), [Heading("Intro", 1)])))
    assert "Helvetica-Oblique" in italic_only and "Helvetica-Bold" not in italic_only
    assert "Helvetica-Bold" not in pdf_fonts(render_pdf_document(document(DocumentStyles(heading_bold=False), [Heading("Intro", 1)])))


def test_the_heading_colour_is_applied_to_headings_and_the_title():
    look = _look_for(DocumentStyles(heading_colour="#ff0000"))
    assert look.headings[2].textColor.hexval() == "0xff0000" and look.title_face == "Helvetica-Bold"


def test_other_scripts_print_inside_a_serif_document_through_the_unicode_font_only_when_the_family_lacks_them():
    cyrillic = pdf_fonts(render_pdf_document(document(DocumentStyles(body_font=family("serif")), [Paragraph(CYRILLIC)])))
    assert "LiberationSerif" in cyrillic and not any("DejaVu" in n for n in cyrillic)  # Liberation covers Cyrillic
    arabic = pdf_fonts(render_pdf_document(document(DocumentStyles(body_font=family("serif")), [Paragraph("Ωμέγα 漢")])))
    assert "LiberationSerif" in arabic
    same_headings = pdf_fonts(render_pdf_document(document(DocumentStyles(body_font=family("serif")), [Heading("Ωμέγα", 1)])))
    assert same_headings  # a heading in another script renders without error in a bold serif


def test_italic_fallback_text_uses_the_italic_unicode_face():
    from app.services.report_document import safe

    assert 'name="ReportUnicode-Italic"' in safe("漢字", italic=True)
    assert 'name="ReportUnicode-BoldItalic"' in safe("漢字", bold=True, italic=True)
    assert 'name="ReportUnicode"' in safe("漢字")


def test_a_wide_font_still_fits_a_table_column():
    from app.services.report_fonts import text_width, using_family

    with using_family("mono"):
        assert text_width("abcdefghij", 10) == pytest.approx(60.0, rel=1e-3)  # monospaced: 0.6 em per character
    assert text_width("abcdefghij", 10) != pytest.approx(60.0, rel=1e-3)
    pdf = render_pdf_document(document(
        DocumentStyles(body_font=family("mono")),
        [Table(["Reference", "Title"], [["ACME-REQ-001", "Something quite long to wrap " * 4]], compact=True)],
    ))
    assert pdf.startswith(b"%PDF") and "LiberationMono" in "".join(pdf_fonts(pdf))


# ---- Word --------------------------------------------------------------------------------------------------------


def word_styles(data: bytes) -> etree._Element:
    return etree.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/styles.xml"))


def style_rpr(root: etree._Element, style_id: str) -> etree._Element:
    return next(s for s in root.findall(f"{W}style") if s.get(f"{W}styleId") == style_id).find(f"{W}rPr")


def test_word_gets_the_body_defaults_and_the_heading_styles_not_a_run_on_every_paragraph():
    styles = DocumentStyles(
        body_font=family("serif"), body_size=12, heading_font=family("mono"), heading_bold=False, heading_italic=True,
        heading_colour="#ff0000",
    )
    data = render_docx_document(document(styles))
    root = word_styles(data)
    defaults = root.find(f"{W}docDefaults").find(f"{W}rPrDefault").find(f"{W}rPr")
    assert defaults.find(f"{W}rFonts").attrib == {f"{W}{k}": "Times New Roman" for k in ("ascii", "hAnsi", "cs", "eastAsia")}
    assert defaults.find(f"{W}sz").get(f"{W}val") == "24"
    heading = style_rpr(root, "Heading1")
    assert heading.find(f"{W}rFonts").get(f"{W}ascii") == "Courier New"
    assert heading.find(f"{W}b").get(f"{W}val") == "0" and heading.find(f"{W}i") is not None
    assert heading.find(f"{W}color").attrib == {f"{W}val": "FF0000"}
    assert heading.find(f"{W}sz").get(f"{W}val") == str(round(14 * 12 / 11 * 2))  # Word's own ratio, scaled
    assert [etree.QName(c).localname for c in heading] == ["rFonts", "b", "bCs", "i", "iCs", "color", "sz", "szCs"]
    body = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml")
    assert b"Times New Roman" not in body and b"Courier New" not in body  # in the styles only


@pytest.mark.parametrize("size", [None, 9, 14])
def test_heading_levels_get_smaller_in_every_format(size):
    styles = DocumentStyles(body_font=family("serif"), body_size=size)
    root = word_styles(render_docx_document(document(styles)))
    word = [int(style_rpr(root, f"Heading{n}").find(f"{W}sz").get(f"{W}val")) for n in (1, 2, 3, 4)]
    assert word == sorted(set(word), reverse=True) and len(word) == 4
    look = _look_for(styles)
    pdf = [look.headings[n].fontSize for n in (1, 2, 3, 4)]
    assert pdf == sorted(set(pdf), reverse=True)
    xml = odt_styles(render_odt_document(document(styles)))
    odt = [float(re.search(rf'style:name="Heading_20_{n}".*?fo:font-size="([\d.]+)pt"', xml).group(1)) for n in (1, 2, 3, 4)]
    assert odt == sorted(set(odt), reverse=True)


def test_word_with_no_styles_is_the_template_unchanged():
    root = word_styles(render_docx_document(document(DocumentStyles())))
    defaults = root.find(f"{W}docDefaults").find(f"{W}rPrDefault").find(f"{W}rPr")
    assert defaults.find(f"{W}rFonts").get(f"{W}asciiTheme") == "minorHAnsi" and defaults.find(f"{W}sz").get(f"{W}val") == "22"
    assert style_rpr(root, "Heading1").find(f"{W}rFonts").get(f"{W}asciiTheme") == "majorHAnsi"


def test_only_the_settings_given_change_word():
    root = word_styles(render_docx_document(document(DocumentStyles(heading_colour="#00aa00"))))
    assert style_rpr(root, "Heading1").find(f"{W}color").get(f"{W}val") == "00AA00"
    defaults = root.find(f"{W}docDefaults").find(f"{W}rPrDefault").find(f"{W}rPr")
    assert defaults.find(f"{W}rFonts").get(f"{W}asciiTheme") == "minorHAnsi"


# ---- OpenDocument ------------------------------------------------------------------------------------------------


def odt_styles(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("styles.xml").decode()


def test_odt_gets_the_default_style_the_declared_faces_and_the_heading_styles():
    styles = DocumentStyles(
        body_font=family("serif"), body_size=12.5, heading_font=family("mono"), heading_bold=False, heading_italic=True,
        heading_colour="#ff0000",
    )
    xml = odt_styles(render_odt_document(document(styles)))
    assert 'style:font-name="Times New Roman" fo:font-size="12.5pt"' in xml
    assert 'style:name="Times New Roman" svg:font-family="\'Times New Roman\'" style:font-family-generic="roman"' in xml
    assert 'style:name="Courier New" svg:font-family="\'Courier New\'" style:font-family-generic="modern"' in xml
    assert 'fo:font-weight="normal" style:font-name="Courier New" fo:font-style="italic" fo:color="#FF0000"' in xml
    assert 'fo:font-size="20pt"' in xml  # Heading 1: 16 pt at the 10 pt body scales to 20 pt at 12.5 pt
    content = zipfile.ZipFile(io.BytesIO(render_odt_document(document(styles)))).read("content.xml").decode()
    assert 'style:name="Times New Roman"' in content  # the content part declares what it uses too


def test_odt_with_no_styles_keeps_arial_at_ten_points():
    xml = odt_styles(render_odt_document(document(DocumentStyles())))
    assert 'style:font-name="Arial" fo:font-size="10pt"' in xml and "Times New Roman" not in xml
    assert 'fo:font-size="16pt"' in xml


# ---- HTML --------------------------------------------------------------------------------------------------------


def test_html_sets_validated_css_only():
    styles = DocumentStyles(
        body_font=family("serif"), body_size=11, heading_font=family("mono"), heading_bold=True, heading_italic=True,
        heading_colour="#ff0000",
    )
    html = render_html_document(document(styles)).decode()
    assert 'body { font-family: "Times New Roman", serif; font-size: 11pt; }' in html
    assert 'h1, h2, h3, h4, h5 { font-family: "Courier New", monospace; font-weight: bold; font-style: italic; color: #ff0000; }' in html


def test_html_with_no_styles_adds_no_rules():
    html = render_html_document(document(DocumentStyles())).decode()
    assert "body { font-family" not in html and "h1, h2, h3, h4, h5 {" not in html


# ---- resolving the stored words ----------------------------------------------------------------------------------


def test_stored_words_resolve_to_families_a_size_and_a_colour(db):  # noqa: F811
    tree = styled_tree({"body": {"font": "serif", "size": 11}, "headings": {"colour": "warn", "italic": True}}, embed_fonts=True)
    resolved, notes, used = resolve_styles(db, tree, accent="#112233", scheme={"warn": "#b45309"})
    assert resolved.body_font.key == "serif" and resolved.body_size == 11.0 and resolved.heading_font is None
    assert resolved.heading_colour == "#b45309" and resolved.heading_italic and resolved.embed_fonts
    assert notes == [] and used == {"warn": "#b45309"}
    assert resolve_styles(db, styled_tree(), accent="#112233", scheme={})[0] == DocumentStyles()
    _, _, used_hex = resolve_styles(db, styled_tree({"headings": {"colour": "accent"}}), accent="#112233", scheme={})
    assert used_hex == {}  # only scheme names are recorded


def test_a_family_the_server_lacks_falls_back_with_a_note(db):  # noqa: F811
    resolved, notes, _ = resolve_styles(db, styled_tree({"body": {"font": "x-house-face"}}), accent="#112233", scheme={})
    assert resolved.body_font.key == "sans" and len(notes) == 1 and "x-house-face" in notes[0] and "not available on this server" in notes[0]


# ---- administrator-provided families -----------------------------------------------------------------------------


@pytest.fixture
def extra(tmp_path, monkeypatch) -> report_fonts.FontFamily:
    directory = tmp_path / "fonts"
    directory.mkdir()
    for style in ("Regular", "Bold"):
        shutil.copyfile(_LIBERATION / f"LiberationMono-{style}.ttf", directory / f"mono-{style}.ttf")
    monkeypatch.setenv("REPORT_FONTS_DIR", str(directory))
    get_settings.cache_clear()
    catalogue.reset()
    found = catalogue.rescan().families["x-liberation-mono"]
    yield replace(found, word_name="Courier Prime", generic="monospace")
    get_settings.cache_clear()
    catalogue.reset()


def test_an_extra_family_prints_its_real_face_in_the_pdf(extra):
    fonts = pdf_fonts(render_pdf_document(document(DocumentStyles(body_font=extra))))
    assert any("LiberationMono" in n for n in fonts)


def test_the_extra_families_a_document_uses_are_found_with_the_styles_they_need(extra):
    uses = used_extra_families(document(DocumentStyles(body_font=extra)))
    assert [(u.family.key, u.styles) for u in uses] == [("x-liberation-mono", frozenset({"regular", "bold", "italic"}))]
    assert used_extra_families(document(DocumentStyles(body_font=family("serif")))) == []
    heading_only = used_extra_families(document(DocumentStyles(heading_font=extra), [Heading("H", 1)]))
    assert [(u.family.key, u.styles) for u in heading_only] == [("x-liberation-mono", frozenset({"bold"}))]
    both = used_extra_families(document(DocumentStyles(body_font=extra, heading_italic=True), [Heading("H", 1), Paragraph("plain")]))
    assert both[0].styles == frozenset({"regular", "bolditalic"})


def test_word_names_the_extra_family_and_embeds_it_only_when_asked(extra):
    plain = zipfile.ZipFile(io.BytesIO(render_docx_document(document(DocumentStyles(body_font=extra)))))
    assert not [n for n in plain.namelist() if n.endswith(".odttf")] and b"Courier Prime" in plain.read("word/fontTable.xml")
    embedded = zipfile.ZipFile(io.BytesIO(render_docx_document(document(DocumentStyles(body_font=extra, embed_fonts=True)))))
    assert [n for n in embedded.namelist() if n.endswith(".odttf")] and b"embedTrueTypeFonts" in embedded.read("word/settings.xml")


def test_bundled_families_are_never_embedded(extra):
    data = render_docx_document(document(DocumentStyles(body_font=family("serif"), embed_fonts=True)))
    assert not [n for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.endswith(".odttf")]
    odt = zipfile.ZipFile(io.BytesIO(render_odt_document(document(DocumentStyles(body_font=family("serif"), embed_fonts=True)))))
    assert not [n for n in odt.namelist() if n.startswith("Fonts/")]


def test_odt_embeds_the_extra_family_under_the_same_setting(extra):
    odt = zipfile.ZipFile(io.BytesIO(render_odt_document(document(DocumentStyles(body_font=extra, embed_fonts=True)))))
    assert [n for n in odt.namelist() if n.startswith("Fonts/")]
    declared = odt.read("styles.xml").decode()
    assert 'svg:font-face-src' in declared and 'style:name="Courier Prime"' in declared
    without = zipfile.ZipFile(io.BytesIO(render_odt_document(document(DocumentStyles(body_font=extra)))))
    assert not [n for n in without.namelist() if n.startswith("Fonts/")] and 'style:name="Courier Prime"' in without.read("styles.xml").decode()


def test_the_font_a_family_only_keeps_in_the_pdf_name_is_used_by_html_and_word_as_a_stack(extra):
    html = render_html_document(document(DocumentStyles(body_font=extra))).decode()
    assert 'font-family: "Courier Prime", monospace' in html


# ---- a run through the API ---------------------------------------------------------------------------------------


def create(world, project, tree: dict[str, Any], name: str = "Styled"):  # noqa: F811
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts", json={"name": name, "description": "", "family": "document", "tree": tree},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_run_prints_in_the_chosen_fonts_in_every_format(world, db):  # noqa: F811
    project = world.project("Alpha")
    h = auth_headers(world.token)
    organization = db.get(Organization, uuid.UUID(world.org["id"]))
    organization.report_colour_scheme = [{"name": "warn", "colour": "#b45309"}]
    db.commit()
    layout = create(world, project, styled_tree({"body": {"font": "serif", "size": 12}, "headings": {"font": "mono", "colour": "warn"}}))
    base = f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run"
    pdf = world.client.get(base, params={"format": "pdf"}, headers=h)
    assert pdf.status_code == 200, pdf.text
    assert {"LiberationSerif", "LiberationMono-Bold"} <= pdf_fonts(pdf.content)
    docx = world.client.get(base, params={"format": "docx"}, headers=h)
    assert style_rpr(word_styles(docx.content), "Heading1").find(f"{W}color").get(f"{W}val") == "B45309"
    html = world.client.get(base, params={"format": "html"}, headers=h).text
    assert 'font-family: "Times New Roman", serif' in html and "color: #b45309" in html
    odt = world.client.get(base, params={"format": "odt"}, headers=h)
    assert 'style:font-name="Times New Roman" fo:font-size="12pt"' in odt_styles(odt.content)
    row = db.scalars(select(GeneratedReport).where(GeneratedReport.layout_id == uuid.UUID(layout["id"]))).first()
    assert row.stats["colours"] == {"warn": "#b45309"}  # the heading colour name is recorded like any other


def test_the_preview_shows_the_fonts_and_a_missing_family_is_a_run_note(world):  # noqa: F811
    project = world.project("Alpha")
    result = preview(world, project, styled_tree({"body": {"font": "x-house-face"}}))
    assert any("x-house-face" in w for w in result["warnings"]) and 'font-family: "Arial", sans-serif' in result["html"]


def test_validate_and_save_warn_about_a_missing_family_without_refusing(world):  # noqa: F811
    project = world.project("Alpha")
    h = auth_headers(world.token)
    tree = styled_tree({"body": {"font": "x-house-face"}})
    check = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts/validate", json={"tree": tree}, headers=h).json()
    assert check["ok"] is True and len(check["warnings"]) == 1 and "x-house-face" in check["warnings"][0]
    saved = create(world, project, tree)
    detail = world.client.get(f"/api/v1/projects/{project['id']}/report-layouts/{saved['id']}", headers=h).json()
    assert detail["warnings"] == check["warnings"] and detail["current"]["tree"]["styles"] == tree["styles"]
    available = styled_tree({"body": {"font": "serif"}})
    ok = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts/validate", json={"tree": available}, headers=h)
    assert ok.json()["warnings"] == []


def test_the_text_view_of_a_saved_layout_carries_its_styles(world):  # noqa: F811
    project = world.project("Alpha")
    h = auth_headers(world.token)
    tree = styled_tree({"body": {"font": "serif"}}, embed_fonts=True)
    text = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts/text/format", json={"tree": tree}, headers=h)
    assert text.status_code == 200 and "embedfonts" in text.json()["text"] and "@style body font=serif" in text.json()["text"]
    back = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts/text/parse", json={"text": text.json()["text"]}, headers=h)
    assert back.json()["ok"] and back.json()["tree"] == tree
