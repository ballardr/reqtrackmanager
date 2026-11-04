"""Tests for a layout's default table heading colours (`table_header_fill`, `table_header_text`): the tree rules, the text
view, the contrast rule, the precedence (a custom table cell's own fill, then the layout, then the organisation accent) and
what each of the four formats writes for a document table and a custom table's header row."""

from __future__ import annotations

import base64
import io
import re
import uuid
import zipfile
import zlib
from typing import Any

import pytest
from docx import Document as DocxDocument

from app.models.organization import Organization
from app.services.report_document import ReportBranding
from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import empty_tree
from app.services.report_model import DocumentStyles, ReportDocument, Table, text_on
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from app.services.report_styles import resolve_styles
from tests.conftest import auth_headers
from tests.test_report_images import db, world  # noqa: F401 - the world and db fixtures
from tests.test_report_styles import create, errors_of, styled_tree

ACCENT = "#112233"
FILL = "#fde68a"  # light: black text reads best
DARK = "#1e3a8a"  # dark: white text reads best
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def document(styles: DocumentStyles, accent: str = ACCENT) -> ReportDocument:
    return ReportDocument(
        title="T", blocks=[Table(["Code", "Title"], [["REQ-001", "First"]], compact=True)], styles=styles,
        branding=ReportBranding(accent_color_hex=accent),
    )


def docx_header(doc: ReportDocument) -> tuple[str, str]:
    """`(cell fill, run colour)` of the first table's heading row in the Word file."""
    table = DocxDocument(io.BytesIO(render_docx_document(doc))).tables[0]
    cell = table.rows[0].cells[0]
    fill = cell._tc.find(f"{W}tcPr").find(f"{W}shd").get(f"{W}fill")
    return fill, str(cell.paragraphs[0].runs[0].font.color.rgb)


def pdf_fills(pdf: bytes) -> set[str]:
    """Every `r g b rg` fill colour the PDF's page streams set, as upper-case hex."""
    found: set[str] = set()
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            content = zlib.decompress(base64.a85decode(raw.strip(), adobe=True)).decode("latin-1")
        except Exception:  # noqa: BLE001 - a font or the document info, not a page
            continue
        for r, g, b in re.findall(r"([\d.]+) ([\d.]+) ([\d.]+) (?:rg|sc)\b", content):
            found.add("".join(f"{round(float(c) * 255):02X}" for c in (r, g, b)))
    return found


# ---- the contrast rule -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("fill", "text"), [("fde68a", "000000"), ("1e3a8a", "FFFFFF"), ("ffffff", "000000"), ("000000", "FFFFFF")])
def test_the_text_colour_is_chosen_by_contrast_with_the_fill(fill, text):
    assert DocumentStyles(table_header_fill=f"#{fill}").table_head_colours(ACCENT) == (fill.upper(), text)


def test_the_contrast_rule_flips_between_two_neighbouring_greys():
    # the WCAG crossover sits near #757575: just below it white reads better, just above it black does
    assert text_on("747474") == "FFFFFF" and text_on("777777") == "000000"
    assert DocumentStyles(table_header_fill="#747474").table_head_colours(ACCENT)[1] == "FFFFFF"
    assert DocumentStyles(table_header_fill="#777777").table_head_colours(ACCENT)[1] == "000000"


def test_a_text_colour_alone_keeps_the_accent_fill_and_a_fill_alone_gets_automatic_text():
    assert DocumentStyles(table_header_text="#ff0000").table_head_colours(ACCENT) == ("112233", "FF0000")
    assert DocumentStyles(table_header_fill=FILL, table_header_text="#ff0000").table_head_colours(ACCENT) == ("FDE68A", "FF0000")
    assert DocumentStyles().table_head_colours(ACCENT) == ("112233", text_on("112233"))


def test_heading_colours_alone_do_not_switch_on_the_font_styling_path():
    assert DocumentStyles(table_header_fill=FILL, table_header_text="#000000").is_default
    assert not DocumentStyles(table_header_fill=FILL, heading_italic=True).is_default


# ---- the tree ----------------------------------------------------------------------------------------------------


def test_valid_heading_colours_are_accepted_as_a_hex_a_reserved_word_or_a_scheme_name():
    from app.services.report_layout_tree import assert_valid

    assert_valid(styled_tree(table_header_fill="primary", table_header_text="#ffffff"))
    assert_valid(styled_tree(table_header_fill="accent_dark", table_header_text="white"))


@pytest.mark.parametrize(("key", "value", "text"), [
    ("table_header_fill", "teal-ish", "Must be a hex colour"),
    ("table_header_fill", "none", "Must be a hex colour"),
    ("table_header_text", 7, "Must be a hex colour"),
])
def test_a_bad_heading_colour_is_refused_with_its_path(key, value, text):
    problems = errors_of(styled_tree(**{key: value}))
    assert any(path == key and text in message for path, message in problems), problems


def test_a_scheme_name_is_checked_against_the_names_in_scope():
    problems = errors_of(styled_tree(table_header_fill="brand"), organization_colours=["warn"])
    assert any(p == "table_header_fill" and "no colour called brand" in m for p, m in problems)
    from app.services.report_layout_tree import assert_valid

    assert_valid(styled_tree(table_header_fill="brand", palette=[{"name": "brand", "colour": "#123456"}]), organization_colours=[])


def test_heading_colours_belong_to_document_layouts_only():
    table = {**empty_tree("table"), "table_header_fill": "accent", "table_header_text": "white"}
    assert {"table_header_fill", "table_header_text"} <= {p for p, _ in errors_of(table)}


# ---- the text view -----------------------------------------------------------------------------------------------


def test_the_text_view_reads_and_writes_the_heading_colours_exactly():
    parsed = parse_text("@layout document A4\n@tableheadings fill=primary text=#ffffff\n\n# Intro\n")
    assert parsed.ok, parsed.errors
    assert parsed.tree["table_header_fill"] == "primary" and parsed.tree["table_header_text"] == "#ffffff"
    text = format_tree(parsed.tree)
    assert "@tableheadings fill=primary text=#ffffff" in text
    assert parse_text(text).tree == parsed.tree
    only_text = parse_text("@layout document A4\n@tableheadings text=black\n")
    assert only_text.tree["table_header_text"] == "black" and "table_header_fill" not in only_text.tree
    assert parse_text(format_tree(only_text.tree)).tree == only_text.tree


@pytest.mark.parametrize(("text", "message"), [
    ("@layout document A4\n@tableheadings\n", "at least one setting"),
    ("@layout document A4\n@tableheadings fill=primary fill=tint\n", "given twice"),
    ("@layout document A4\n@tableheadings colour=primary\n", "Expected fill=<colour> or text=<colour>"),
    ("@layout document A4\n@tableheadings fill=primary\n@tableheadings text=white\n", "written once"),
    ("@layout document A4\n# Intro\n@tableheadings fill=primary\n", "before the first block"),
])
def test_text_view_mistakes_are_reported_on_their_line(text, message):
    parsed = parse_text(text)
    assert not parsed.ok and any(message in e.message for e in parsed.errors), parsed.errors


def test_the_tree_rules_reach_the_text_view_with_a_line():
    parsed = parse_text("@layout document A4\n@tableheadings fill=not-a-colour\n")
    assert not parsed.ok
    assert any(e.line == 2 and "Must be a hex colour" in e.message for e in parsed.errors), parsed.errors


# ---- the four formats --------------------------------------------------------------------------------------------


def test_with_nothing_set_a_heading_is_the_accent_with_contrasting_text_in_every_format():
    doc = document(DocumentStyles())
    assert docx_header(doc) == ("112233", text_on("112233"))
    assert "112233" in pdf_fills(render_pdf_document(doc)) or "#112233" in str(render_pdf_document(doc))
    assert "th { background: #112233; color: #" + text_on("112233") in render_html_document(doc).decode().replace("#" + "112233", "#112233")
    odt = zipfile.ZipFile(io.BytesIO(render_odt_document(doc))).read("content.xml").decode()
    assert re.search(r'name="C_hdr".*?background-color="#112233"', odt)


def test_word_shades_the_heading_in_the_layout_fill_with_the_chosen_or_automatic_text():
    assert docx_header(document(DocumentStyles(table_header_fill=FILL))) == ("FDE68A", "000000")
    assert docx_header(document(DocumentStyles(table_header_fill=DARK))) == ("1E3A8A", "FFFFFF")
    assert docx_header(document(DocumentStyles(table_header_fill=FILL, table_header_text="#7f1d1d"))) == ("FDE68A", "7F1D1D")


def test_the_pdf_fills_the_heading_with_the_layout_colour_instead_of_the_accent():
    default = pdf_fills(render_pdf_document(document(DocumentStyles())))
    custom = pdf_fills(render_pdf_document(document(DocumentStyles(table_header_fill=FILL))))
    assert "FDE68A" in custom and "FDE68A" not in default
    assert "112233" in default and "112233" not in custom


def test_the_pdf_prints_the_heading_text_in_the_chosen_colour():
    custom = pdf_fills(render_pdf_document(document(DocumentStyles(table_header_fill=FILL, table_header_text="#7f1d1d"))))
    assert "7F1D1D" in custom
    assert "7F1D1D" not in pdf_fills(render_pdf_document(document(DocumentStyles(table_header_fill=FILL))))


def test_html_writes_the_heading_colours_into_the_th_rule_only():
    html = render_html_document(document(DocumentStyles(table_header_fill=FILL, table_header_text="#7f1d1d"))).decode()
    assert "th { background: #FDE68A; color: #7F1D1D;" in html
    assert re.search(r"--accent: #112233", html)  # the accent still drives headings and the title rule


def test_opendocument_styles_the_heading_cell_and_its_text():
    doc = document(DocumentStyles(table_header_fill=FILL, table_header_text="#7f1d1d"))
    odt = zipfile.ZipFile(io.BytesIO(render_odt_document(doc))).read("content.xml").decode()
    assert re.search(r'name="C_hdr".*?fo:background-color="#FDE68A"', odt)
    assert re.search(r'name="P_hdr".*?fo:color="#7F1D1D"', odt)


# ---- the run: a custom table's heading row -----------------------------------------------------------------------


GRID = {
    "type": "grid", "columns": [{}, {}], "header_rows": 1,
    "rows": [{"cells": [{"text": "Code"}, {"text": "Title"}]}, {"cells": [{"text": "REQ-001"}, {"text": "First"}]}],
}


def run_html(world, db, tree: dict[str, Any]) -> str:  # noqa: F811
    organization = db.get(Organization, uuid.UUID(world.org["id"]))
    organization.report_colour_scheme = [{"name": "warn", "colour": "#b45309"}]
    db.commit()
    project = world.project("Alpha")
    layout = create(world, project, tree)
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": "html"}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp.text


def cell_styles(html: str) -> list[str]:
    """The inline style of every grid cell, in document order."""
    return re.findall(r'<td class="[^"]*"(?: [a-z]+="\d+")*(?: style="([^"]*)")?>', html)


def test_a_custom_tables_heading_row_takes_the_layout_colours_and_its_body_does_not(world, db):  # noqa: F811
    tree = styled_tree(table_header_fill="warn")
    tree["nodes"] = [GRID]
    styles = cell_styles(run_html(world, db, tree))
    assert styles[:2] == ["background-color:#b45309;color:#ffffff"] * 2 or all("background-color:#b45309" in s for s in styles[:2])
    assert all("background-color" not in s for s in styles[2:])
    assert "color:#ffffff" in styles[0]  # automatic text on a dark brown


def test_a_cells_own_fill_wins_and_keeps_its_own_text_colour_rule(world, db):  # noqa: F811
    grid = {**GRID, "rows": [{"cells": [{"text": "Code", "fill": "#ffffff"}, {"text": "Title"}]}, GRID["rows"][1]]}
    tree = styled_tree(table_header_fill="warn", table_header_text="#000000")
    tree["nodes"] = [grid]
    styles = cell_styles(run_html(world, db, tree))
    assert "background-color:#ffffff" in styles[0] and "color:#000000" not in styles[0]  # the default pair applies as a unit
    assert "background-color:#b45309" in styles[1] and "color:#000000" in styles[1]


def test_no_default_leaves_a_custom_tables_heading_row_as_authored(world, db):  # noqa: F811
    tree = styled_tree()
    tree["nodes"] = [GRID]
    assert all(s == "" for s in cell_styles(run_html(world, db, tree)))


def test_a_grid_without_heading_rows_is_untouched(world, db):  # noqa: F811
    tree = styled_tree(table_header_fill="warn")
    tree["nodes"] = [{**GRID, "header_rows": 0}]
    assert all("background-color" not in s for s in cell_styles(run_html(world, db, tree)))


def test_the_default_applies_to_every_heading_row_of_a_grid(world, db):  # noqa: F811
    grid = {**GRID, "header_rows": 2}
    tree = styled_tree(table_header_fill="#fde68a")
    tree["nodes"] = [grid]
    styles = cell_styles(run_html(world, db, tree))
    assert all("background-color:#fde68a" in s and "color:#000000" in s for s in styles)


def test_the_scheme_name_is_recorded_and_the_preview_shows_the_colour(world, db):  # noqa: F811
    from tests.test_report_shapes import preview

    organization = db.get(Organization, uuid.UUID(world.org["id"]))
    organization.report_colour_scheme = [{"name": "warn", "colour": "#b45309"}]
    db.commit()
    tree = styled_tree(table_header_fill="warn")
    tree["nodes"] = [GRID]
    result = preview(world, world.project("Alpha"), tree)
    assert "background-color:#b45309" in result["html"]


def test_resolve_styles_reads_the_two_words_and_records_a_scheme_name(db):  # noqa: F811
    resolved, notes, used = resolve_styles(
        db, styled_tree(table_header_fill="warn", table_header_text="white"), accent="#112233", scheme={"warn": "#b45309"},
    )
    assert (resolved.table_header_fill, resolved.table_header_text) == ("#b45309", "#ffffff")
    assert notes == [] and used == {"warn": "#b45309"}
    plain, _, used_plain = resolve_styles(db, styled_tree(), accent="#112233", scheme={})
    assert plain == DocumentStyles() and used_plain == {}
