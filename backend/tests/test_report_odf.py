"""Tests for the ODT and ODS renderers (`services.report_odt`, `services.report_ods`, `services.report_odf`):
package structure, escaping of hostile text, whitespace, headings, tables, branding and cover, pictures and
equations, spreadsheet cell safety and sheet names. No database."""

from __future__ import annotations

import io
import zipfile

import pytest
from lxml import etree
from PIL import Image as PilImage

from app.services.report_document import ReportBranding
from app.services.report_math import typeset
from app.services.report_model import (
    BulletList,
    Equation,
    Gap,
    Heading,
    Image,
    MathText,
    Note,
    PageBreak,
    Paragraph,
    ReportDocument,
    Sheet,
    Table,
)
from app.services.report_odf import NAMESPACES, xml_text
from app.services.report_render import MAX_CELL_CHARS, RenderInput, formats_for, render, sheet_title, unique_names

NS = {"text": NAMESPACES["text"], "table": NAMESPACES["table"], "office": NAMESPACES["office"], "style": NAMESPACES["style"],
      "draw": NAMESPACES["draw"], "fo": NAMESPACES["fo"], "manifest": NAMESPACES["manifest"], "svg": NAMESPACES["svg"]}


def qn(prefix: str, local: str) -> str:
    """The Clark-notation name of `local` in the namespace `prefix`."""
    return f"{{{NS[prefix]}}}{local}"


HOSTILE = '<script>alert(1)</script></text:p><draw:frame> & "q" \x00\x08'


def png(colour=(200, 30, 30), size=(40, 20)) -> bytes:
    buffer = io.BytesIO()
    PilImage.new("RGB", size, colour).save(buffer, "PNG")
    return buffer.getvalue()


def odt(document: ReportDocument) -> zipfile.ZipFile:
    out = render("odt", "document", RenderInput("t", document=document))
    assert out.extension == "odt"
    return zipfile.ZipFile(io.BytesIO(out.content))


def ods(*sheets: Sheet) -> zipfile.ZipFile:
    out = render("ods", "table", RenderInput("t", sheets=list(sheets)))
    assert out.extension == "ods"
    return zipfile.ZipFile(io.BytesIO(out.content))


def xml(archive: zipfile.ZipFile, part: str) -> etree._Element:
    return etree.fromstring(archive.read(part))


def test_both_formats_are_registered_for_their_family():
    assert "odt" in formats_for("document") and "ods" in formats_for("table")
    assert "odt" not in formats_for("table") and "ods" not in formats_for("document")


@pytest.mark.parametrize("archive", [
    lambda: odt(ReportDocument("T", [Heading("H"), Image(png()), Table(["a"], [["b"]])])),
    lambda: ods(Sheet("S", ["a"], [["b"]])),
])
def test_package_has_mimetype_first_and_stored_and_a_manifest_listing_every_part(archive):
    zf = archive()
    first = zf.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert zf.read("mimetype").decode().startswith("application/vnd.oasis.opendocument.")
    listed = {e.get(qn("manifest", "full-path")) for e in xml(zf, "META-INF/manifest.xml")}
    assert listed == {"/", "META-INF/manifest.xml", *(n for n in zf.namelist() if n not in ("mimetype", "META-INF/manifest.xml"))}
    for name in zf.namelist():
        if name.endswith(".xml"):
            xml(zf, name)  # well-formed


def test_metadata_is_fixed_and_carries_no_person():
    meta = odt(ReportDocument("My <title>")).read("meta.xml").decode()
    assert "ReqTrackManager" in meta and "My &lt;title&gt;" in meta


def test_xml_text_keeps_whitespace_and_drops_invalid_characters():
    assert xml_text("a  b") == 'a<text:s text:c="2"/>b'
    assert xml_text("a\tb\nc") == "a<text:tab/>b<text:line-break/>c"
    assert xml_text(" x ") == '<text:s text:c="1"/>x<text:s text:c="1"/>'
    assert xml_text("x\x00\x08y") == "xy"
    assert xml_text("<&>") == "&lt;&amp;&gt;"


def test_hostile_text_is_content_in_every_position_and_never_markup():
    document = ReportDocument(HOSTILE, [
        Heading(HOSTILE), Paragraph(HOSTILE), Note(HOSTILE), BulletList([HOSTILE]),
        Table([HOSTILE], [[HOSTILE]]), Equation("x", True),
    ], branding=ReportBranding(footer_text=HOSTILE))
    archive = odt(document)
    for part in ("content.xml", "styles.xml", "meta.xml"):
        root = xml(archive, part)
        assert not root.xpath("//*[local-name()='script']")
    content = xml(archive, "content.xml")
    assert not content.xpath("//draw:frame[not(@draw:name)]", namespaces=NS)
    body = content.xpath("//office:text", namespaces=NS)[0]
    assert "<script>alert(1)</script></text:p><draw:frame> & \"q\"" in "".join(body.itertext())


def test_headings_are_real_outline_headings_and_a_level_is_clamped():
    content = xml(odt(ReportDocument("T", [Heading("One", 1), Heading("Deep", 9), Heading("Zero", 0)])), "content.xml")
    levels = [h.get(qn("text", "outline-level")) for h in content.xpath("//text:h", namespaces=NS)]
    assert levels == ["1", "4", "1"]
    styles = xml(odt(ReportDocument("T")), "styles.xml")
    assert styles.xpath("//style:style[@style:name='Heading_20_1'][@style:default-outline-level='1']", namespaces=NS)


def test_table_has_a_repeating_header_zebra_tones_and_padded_rows():
    table = Table(["A", "B", "C"], [["1", "2"], ["3", "4", "5"]], compact=True, tones=[["danger", None], [None, "info", None]])
    content = xml(odt(ReportDocument("T", [table])), "content.xml")
    header = content.xpath("//table:table-header-rows/table:table-row/table:table-cell", namespaces=NS)
    assert [c.xpath("string(.)") for c in header] == ["A", "B", "C"]
    rows = content.xpath("//table:table/table:table-row", namespaces=NS)
    assert len(rows) == 2 and all(len(r) == 3 for r in rows)
    first = rows[0].xpath("table:table-cell/@table:style-name", namespaces=NS)
    second = rows[1].xpath("table:table-cell/@table:style-name", namespaces=NS)
    assert first == ["C_danger", "C_zebra" if False else "C_body", "C_body"]
    assert second == ["C_zebra", "C_info", "C_zebra"]
    assert len(content.xpath("//table:table-column", namespaces=NS)) == 3


def test_a_table_without_columns_is_left_out_and_two_tables_are_separated():
    content = xml(odt(ReportDocument("T", [Table([], []), Table(["a"], []), Table(["b"], [])])), "content.xml")
    tables = content.xpath("//table:table", namespaces=NS)
    assert len(tables) == 2 and tables[0].get(qn("table", "name")) != tables[1].get(qn("table", "name"))
    assert tables[0].getnext().tag == qn("text", "p")


def test_bullet_list_page_break_and_gap():
    content = xml(odt(ReportDocument("T", [BulletList(["a", "b"]), BulletList([]), PageBreak(), Gap(2)])), "content.xml")
    assert len(content.xpath("//text:list/text:list-item", namespaces=NS)) == 2
    assert content.xpath("//text:p[@text:style-name='P_Break']", namespaces=NS)
    styles = etree.tostring(content).decode()
    assert 'fo:break-after="page"' in styles


def test_landscape_orientation_cover_page_and_footer_text():
    branding = ReportBranding(accent_color_hex="#112233", include_cover_page=True, footer_text="Secret", logo_bytes=png())
    archive = odt(ReportDocument("Cover title", [Paragraph("body")], branding=branding, landscape=True))
    styles = xml(archive, "styles.xml")
    layout = styles.xpath("//style:page-layout-properties", namespaces=NS)[0]
    assert layout.get(qn("fo", "page-width")) == "29.700cm" and layout.get(qn("fo", "page-height")) == "21.000cm"
    footer = styles.xpath("//style:master-page[@style:name='Standard']/style:footer", namespaces=NS)[0]
    assert footer.xpath("string(.)").startswith("Secret  ·  Page ") and footer.xpath(".//text:page-number", namespaces=NS)
    assert not styles.xpath("//style:master-page[@style:name='Cover']/style:footer", namespaces=NS)
    content = xml(archive, "content.xml")
    assert content.xpath("//text:p[@text:style-name='P_CoverTitle']", namespaces=NS)[0].xpath("string(.)") == "Cover title"
    assert content.xpath("//style:style[@style:name='P_CoverStart'][@style:master-page-name='Cover']", namespaces=NS)
    assert content.xpath("//draw:frame", namespaces=NS)  # the logo
    assert any(n.startswith("Pictures/") for n in archive.namelist())


def test_a_plain_document_has_a_title_line_and_no_cover_styles():
    content = xml(odt(ReportDocument("Plain")), "content.xml")
    assert content.xpath("//text:p[@text:style-name='Title']", namespaces=NS)[0].xpath("string(.)") == "Plain"
    assert not content.xpath("//style:style[@style:name='P_CoverStart']", namespaces=NS)


def test_a_bad_accent_colour_falls_back_and_never_reaches_the_xml():
    archive = odt(ReportDocument("T", [Table(["a"], [["b"]])], branding=ReportBranding(accent_color_hex='"><x/>')))
    text = archive.read("content.xml").decode()
    assert "<x/>" not in text and 'fo:background-color="#' in text
    xml(archive, "content.xml")


def test_pictures_are_sniffed_from_bytes_and_non_images_are_skipped():
    archive = odt(ReportDocument("T", [Image(png(), alt='a "red" <box>'), Image(b"not an image"), Image(b"<svg/>")]))
    content = xml(archive, "content.xml")
    assert len(content.xpath("//draw:frame", namespaces=NS)) == 1
    assert content.xpath("//draw:frame/svg:title", namespaces=NS)[0].text == 'a "red" <box>'
    assert [n for n in archive.namelist() if n.startswith("Pictures/")] == ["Pictures/image1.png"]
    media = {e.get(qn("manifest", "full-path")): e.get(qn("manifest", "media-type")) for e in xml(archive, "META-INF/manifest.xml")}
    assert media["Pictures/image1.png"] == "image/png"


def test_a_wide_picture_is_shrunk_to_the_usable_width():
    content = xml(odt(ReportDocument("T", [Image(png(size=(4000, 1000)))])), "content.xml")
    frame = content.xpath("//draw:frame", namespaces=NS)[0]
    assert frame.get(qn("svg", "width")) == "18.000cm" and frame.get(qn("svg", "height")) == "4.500cm"


def test_an_svg_figure_becomes_a_picture():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20" viewBox="0 0 40 20"><rect width="40" height="20" fill="#c00"/></svg>'
    archive = odt(ReportDocument("T", [Image(svg=svg)]))
    assert any(n.endswith(".png") for n in archive.namelist())


def test_equations_are_pictures_inline_and_display_and_the_source_when_they_cannot_be_drawn():
    assert typeset("x^2", False) is not None
    document = ReportDocument("T", [
        Equation(r"\frac{a}{b}", True),
        Paragraph(MathText(["See ", Equation("x^2", False), " here"])),
        Equation(r"\input{/etc/passwd}", True),
        Paragraph(MathText(["bad ", Equation(r"\input{x}", False)])),
    ])
    content = xml(odt(document), "content.xml")
    frames = content.xpath("//draw:frame", namespaces=NS)
    assert len(frames) == 2
    inline = [f for f in frames if f.get(qn("draw", "style-name")) == "fr_inline"]
    assert len(inline) == 1 and inline[0].get(qn("svg", "y")) is not None
    text = "".join(content.xpath("//office:text", namespaces=NS)[0].itertext())
    assert "$$\\input{/etc/passwd}$$" in text and "\\(\\input{x}\\)" in text


def test_ods_cells_are_typed_text_never_formulas_guarded_and_cut():
    archive = ods(Sheet("S", ["=h", "ok"], [["=SUM(1)", "@x"], ["-1", "+1"], ["\tt", "plain"], ["", "x" * (MAX_CELL_CHARS + 50)]]))
    content = xml(archive, "content.xml")
    assert not content.xpath("//@table:formula", namespaces=NS)
    cells = content.xpath("//table:table-cell", namespaces=NS)
    assert all(c.get(qn("office", "value-type")) in ("string", None) for c in cells)
    values = ["".join(c.itertext()) for c in cells]
    assert values[:2] == ["'=h", "ok"] and values[2:4] == ["'=SUM(1)", "'@x"] and values[4:6] == ["'-1", "'+1"]
    assert values[6].startswith("'") and values[8] == "" and len(values[9]) == MAX_CELL_CHARS


def test_ods_has_a_tab_per_sheet_with_clean_unique_names_and_a_frozen_header():
    archive = ods(
        Sheet("Req/uirements: [1]", ["a"], []), Sheet("req/uirements: [1]", ["a"], []), Sheet("'Quoted'", ["a"], []), Sheet("x" * 40, ["a"], []),
    )
    names = [t.get(qn("table", "name")) for t in xml(archive, "content.xml").xpath("//table:table", namespaces=NS)]
    assert names[0] == "Req uirements   1" and names[1].endswith("(2)") and names[2] == "Quoted" and len(names[3]) == 31
    assert len({n.lower() for n in names}) == 4
    settings = archive.read("settings.xml").decode()
    assert settings.count('config:name="VerticalSplitMode"') == 4 and 'config:name="Quoted"' in settings
    assert xml(archive, "content.xml").xpath("//table:table-header-rows", namespaces=NS)


def test_ods_preserves_multiline_and_spaced_text_and_unicode():
    content = xml(ods(Sheet("S", ["h"], [["a\nb  c"], ["é ü Ж 日本"]])), "content.xml")
    cells = content.xpath("//table:table/table:table-row[1]/table:table-cell", namespaces=NS)[0]
    assert cells.xpath(".//text:line-break", namespaces=NS) and cells.xpath(".//text:s", namespaces=NS)
    assert "é ü Ж 日本" in "".join(content.itertext())


def test_ods_hostile_sheet_name_and_cells_cannot_break_the_xml():
    archive = ods(Sheet('"><x/>', [HOSTILE], [[HOSTILE]]))
    content = xml(archive, "content.xml")
    assert not content.xpath("//*[local-name()='x']") and xml(archive, "settings.xml") is not None


def test_ods_with_no_sheet_is_a_valid_workbook_and_a_sheet_with_no_rows_keeps_its_header():
    assert len(xml(ods(), "content.xml").xpath("//table:table", namespaces=NS)) == 1
    only_header = xml(ods(Sheet("S", ["a", "b"], [])), "content.xml")
    assert len(only_header.xpath("//table:table-cell", namespaces=NS)) == 2


def test_ods_streams_a_large_sheet_without_a_per_cell_object_tree():
    rows = [[f"v{r}", str(r), "x"] for r in range(20_000)]
    out = render("ods", "table", RenderInput("t", sheets=[Sheet("Big", ["a", "b", "c"], rows)]))
    archive = zipfile.ZipFile(io.BytesIO(out.content))
    content = archive.read("content.xml")
    assert content.count(b"<table:table-row>") == 20_001
    xml(archive, "content.xml")


def test_sheet_titles_are_clean_for_every_spreadsheet_format():
    assert sheet_title("'a/b'") == "a b" and sheet_title("[x]") == "x" and sheet_title("  ") == ""
    assert unique_names(["'", "'"], clean=sheet_title) == ["Sheet", "Sheet (2)"]
