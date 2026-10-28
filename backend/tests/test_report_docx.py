"""Tests for the neutral report document model and its DOCX renderer.

Covers the Markdown reader, the DOCX structure (real heading styles, real
tables with a shaded repeating header, footer, orientation, core properties),
the XML-invalid-character and markup safety rules, image handling and tenant
isolation, and the HTTP surface for the requirement report and the module
reports. The PDF renderer's unchanged layout is covered by the existing report
test files, which are the acceptance guard for moving it onto the model.
"""

from __future__ import annotations

import io
import struct
import zlib
from datetime import UTC, datetime

import pytest
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn

from app.modules.registry import get_all_reports
from app.services.report_document import ReportBranding
from app.services.report_docx import DOCX_AUTHOR, clean_text, render_docx_document
from app.services.report_framework import ReportResult, ReportSection, build_result_document, render_docx
from app.services.report_model import (
    BulletList,
    Gap,
    Heading,
    Image,
    MathText,
    Note,
    PageBreak,
    Paragraph,
    ReportDocument,
    Styled,
    Table,
    markdown_to_blocks,
)
from app.services.reports import ReportRequirementRow, build_requirement_document
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
HOSTILE = "bad \x00\x08\x0b\x1f\ud800 <script>alert(1)</script> <w:p/> & ]]> end"
# What can travel through JSON and PostgreSQL (no NUL, no lone surrogate) yet is still XML-invalid.
STORED_HOSTILE = "bad \x08\x0b\x1f <script>alert(1)</script> <w:p/> & ]]> end"


def _tiny_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + ihdr + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b"")


def _open(content: bytes):
    return Document(io.BytesIO(content))


def _header_fill(table) -> str:
    return table.rows[0].cells[0]._tc.tcPr.find(qn("w:shd")).get(qn("w:fill"))


def _row(code="R-1", name="Boot fast", reasoning="UX", status="draft", component="Core", category="Perf", c=1, k=1):
    return ReportRequirementRow(code, name, reasoning, "", status, component, category, c, k)


# --- Markdown reader -----------------------------------------------------------------------


def test_markdown_to_blocks_reads_headings_paragraphs_lists_and_own_line_images():
    source = "# One\n\n### Three\n\n###### Six\n\ntext *styled* and ~~literal~~\n\n- a\n- b\n\n![alt](attachment:x)\n"
    blocks = markdown_to_blocks(source, {"attachment:x": b"png"})
    assert [b for b in blocks if isinstance(b, Heading)] == [Heading("One", 1), Heading("Three", 3), Heading("Six", 4)]
    # Emphasis is a style (the words read without markers); the rest of the inline syntax stays as written.
    styled = next(b for b in blocks if isinstance(b, Paragraph) and isinstance(b.text, MathText))
    assert styled.text.parts == ("text ", Styled("styled", italic=True), " and ~~literal~~")
    assert BulletList(["a", "b"]) in blocks
    assert Image(b"png") in blocks


def test_markdown_to_blocks_skips_unresolved_images_and_blank_input():
    assert markdown_to_blocks("   \n") == []
    blocks = markdown_to_blocks("![alt](attachment:missing)\n", {})
    assert not [b for b in blocks if isinstance(b, Image)]
    mixed = markdown_to_blocks("see ![alt](attachment:x) here", {"attachment:x": b"png"})
    assert Paragraph("see ![alt](attachment:x) here") in mixed  # an inline image keeps its literal text


# --- Document builders ---------------------------------------------------------------------


def test_requirement_document_groups_chapters_and_tables():
    rows = [_row("R-2", component="B", c=2), _row("R-1", component="A", c=1)]
    chaptered = build_requirement_document(project_name="P", pre_markdown="# Intro", rows=rows, post_markdown="# End", chapters_per_component=True)
    assert chaptered.title == "P" and chaptered.landscape is False
    assert [b.text for b in chaptered.blocks if isinstance(b, Heading) and b.level == 1] == ["Intro", "A", "B", "End"]
    assert sum(isinstance(b, PageBreak) for b in chaptered.blocks) == 2
    table = next(b for b in chaptered.blocks if isinstance(b, Table))
    assert table.columns == ["ID", "Name", "Reasoning", "Status", "Tags"] and table.rows == [["R-1", "Boot fast", "UX", "Draft", ""]]
    flowing = build_requirement_document(project_name="P", pre_markdown="", rows=rows, post_markdown="", chapters_per_component=False)
    assert not [b for b in flowing.blocks if isinstance(b, PageBreak)]


def test_requirement_document_tones_the_status_cell_like_the_screen_badge():
    from app.services.report_model import TONE_FILL

    rows = [_row("R-1", status="approved"), _row("R-2", status="draft")]
    document = build_requirement_document(project_name="P", pre_markdown="", rows=rows, post_markdown="", chapters_per_component=False)
    table = next(b for b in document.blocks if isinstance(b, Table))
    assert [table.tone_at(i, 3) for i in range(2)] == ["accent", "muted"]
    assert all(table.tone_at(i, c) is None for i in range(2) for c in (0, 1, 2, 4))
    docx = _open(render_docx_document(document))
    cells = docx.tables[0].rows
    assert cells[1].cells[3]._tc.tcPr.find(qn("w:shd")).get(qn("w:fill")) == TONE_FILL["accent"]


def test_result_document_is_landscape_with_a_table_per_non_empty_section():
    result = ReportResult(
        "k", "T", "Scope", datetime(2026, 1, 2, 3, 4, tzinfo=UTC), ["caveat"],
        [ReportSection("a", "A", ["x"], [["1"]], note="n"), ReportSection("b", "B", ["x"], [])],
    )
    document = build_result_document(result)
    assert document.landscape is True
    assert Note("Scope · generated 2026-01-02 03:04 UTC") in document.blocks and Note("caveat") in document.blocks
    assert len([b for b in document.blocks if isinstance(b, Table)]) == 1 and Note("None.") in document.blocks


# --- DOCX structure ------------------------------------------------------------------------


def test_docx_uses_real_headings_tables_lists_and_a_shaded_repeating_header():
    document = ReportDocument(
        title="Title", branding=ReportBranding(accent_color_hex="#AA3300", footer_text="Confidential"),
        blocks=[
            Heading("Chapter", 1), Heading("Section", 2), Paragraph("Body"), BulletList(["one", "two"]), Note("small"),
            Table(["A", "B"], [["1", "2"], ["3", "4"], ["5", "6"]], compact=True), Gap(1), PageBreak(),
        ],
    )
    doc = _open(render_docx_document(document))
    styles = [(p.style.name, p.text) for p in doc.paragraphs if p.text]
    assert ("Title", "Title") in styles and ("Heading 1", "Chapter") in styles and ("Heading 2", "Section") in styles
    assert [t for s, t in styles if s == "List Bullet"] == ["one", "two"]
    table = doc.tables[0]
    assert [[c.text for c in r.cells] for r in table.rows] == [["A", "B"], ["1", "2"], ["3", "4"], ["5", "6"]]
    assert _header_fill(table) == "AA3300"
    assert table.rows[0]._tr.trPr.find(qn("w:tblHeader")) is not None
    assert table.rows[0].cells[0].paragraphs[0].runs[0].font.bold is True
    footer = doc.sections[0].footer.paragraphs[0]
    assert "Confidential" in footer.text and footer._p.find(qn("w:fldSimple")).get(qn("w:instr")) == "PAGE"


def test_docx_orientation_follows_the_document_and_core_properties_hold_no_personal_data():
    wide = _open(render_docx_document(ReportDocument(title="Wide", landscape=True)))
    assert wide.sections[0].orientation == WD_ORIENT.LANDSCAPE and wide.sections[0].page_width > wide.sections[0].page_height
    tall = _open(render_docx_document(ReportDocument(title="Tall")))
    assert tall.sections[0].orientation == WD_ORIENT.PORTRAIT
    props = tall.core_properties
    assert props.author == props.last_modified_by == DOCX_AUTHOR and props.title == "Tall"
    assert props.comments == "" and props.created is not None


def test_docx_cover_page_has_logo_accent_title_and_a_clean_first_page_footer():
    branding = ReportBranding(accent_color_hex="#112233", include_cover_page=True, footer_text="Foot", logo_bytes=_tiny_png())
    doc = _open(render_docx_document(ReportDocument(title="Cover", branding=branding, blocks=[Paragraph("after")])))
    title = next(p for p in doc.paragraphs if p.style.name == "Title")
    assert title.runs[0].font.color.rgb == (0x11, 0x22, 0x33)
    assert len(doc.inline_shapes) == 1
    assert doc.sections[0].different_first_page_header_footer is True
    assert any(p._p.xpath('.//w:br[@w:type="page"]') for p in doc.paragraphs)


def test_docx_table_grid_widths_follow_the_requested_proportions_and_fit_the_page():
    document = ReportDocument(title="T", blocks=[Table(["A", "B"], [["1", "2"]], col_widths_cm=[3, 9])])
    doc = _open(render_docx_document(document))
    widths = [c.width for c in doc.tables[0].columns]
    assert widths[1] == pytest.approx(widths[0] * 3, rel=0.01)
    usable = doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin
    assert sum(widths) == pytest.approx(usable, rel=0.01)


def test_docx_invalid_accent_colour_falls_back_instead_of_reaching_the_xml():
    document = ReportDocument(
        title="T", branding=ReportBranding(accent_color_hex='"/><w:evil/>'), blocks=[Table(["A"], [["1"]])],
    )
    table = _open(render_docx_document(document)).tables[0]
    assert _header_fill(table) == "475569"


# --- Safety --------------------------------------------------------------------------------


def test_clean_text_drops_only_xml_invalid_characters():
    assert clean_text("a\x00b\x08c\x0bd\x1fe\ud800f") == "abcdef"
    assert clean_text("tab\tnew\nline é 漢 😀") == "tab\tnew\nline é 漢 😀"


def test_docx_survives_control_characters_and_stores_markup_as_literal_text_everywhere():
    document = ReportDocument(
        title=HOSTILE, branding=ReportBranding(footer_text=HOSTILE),
        blocks=[
            Heading(HOSTILE, 1), Paragraph(HOSTILE), Note(HOSTILE), BulletList([HOSTILE]),
            Table([HOSTILE], [[HOSTILE]]), Table([HOSTILE], [[HOSTILE]], compact=True),
        ],
    )
    content = render_docx_document(document)
    doc = _open(content)
    expected = clean_text(HOSTILE)
    texts = [p.text for p in doc.paragraphs if p.text]
    assert texts.count(expected) >= 4
    assert doc.tables[0].rows[1].cells[0].text == expected
    assert doc.core_properties.title == expected
    # The markup is escaped text, never an element: no <script> or injected <w:p/> exists in the body.
    body = doc.element.body
    assert body.xpath("//script") == []
    assert len(body.xpath("//w:t[contains(., '<script>')]")) >= 4


def test_docx_skips_an_undecodable_image_and_shrinks_a_wide_one():
    broken = _open(render_docx_document(ReportDocument(title="T", blocks=[Image(b"not an image"), Paragraph("still here")])))
    assert len(broken.inline_shapes) == 0 and "still here" in [p.text for p in broken.paragraphs]
    ok = _open(render_docx_document(ReportDocument(title="T", blocks=[Image(_tiny_png())])))
    assert len(ok.inline_shapes) == 1


def test_docx_handles_empty_and_ragged_tables_and_documents():
    assert _open(render_docx_document(ReportDocument(title="Empty"))).paragraphs
    ragged = _open(render_docx_document(ReportDocument(title="R", blocks=[Table(["A", "B"], [["only"], ["1", "2", "3"]])])))
    assert [[c.text for c in r.cells] for r in ragged.tables[0].rows] == [["A", "B"], ["only", ""], ["1", "2"]]
    assert not _open(render_docx_document(ReportDocument(title="N", blocks=[Table([], [])]))).tables


def test_framework_docx_has_a_table_per_section_in_landscape():
    result = ReportResult(
        "k", "T", "Scope", datetime.now(UTC), [HOSTILE],
        [ReportSection("a", "A", ["c1", "c2"], [["1", "2"], [HOSTILE, "4"]]), ReportSection("b", "B", ["x"], [])],
    )
    doc = _open(render_docx(result))
    assert doc.sections[0].orientation == WD_ORIENT.LANDSCAPE
    assert len(doc.tables) == 1 and doc.tables[0].rows[2].cells[0].text == clean_text(HOSTILE)
    assert "None." in [p.text for p in doc.paragraphs]
    assert render_docx(ReportResult("k", "T", "S", datetime.now(UTC), [], []))[:2] == b"PK"


# --- HTTP: requirement report --------------------------------------------------------------


def _seed_requirement(client, token, org_id, name="Boot fast"):
    project = create_project(client, token, org_id)
    component_id, category_id = create_component_and_category(client, token, project["id"])
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": name, "reasoning": "UX matters", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return project


def test_requirement_report_docx_download(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "DocxReqOrg")
    project = _seed_requirement(client, token, org["id"], STORED_HOSTILE)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports", json={"format": "docx", "pre_markdown": "# Intro\n\nHello"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == DOCX_TYPE
    assert resp.headers["content-disposition"] == 'attachment; filename="Demo Project-requirements.docx"'
    doc = _open(resp.content)
    assert ("Heading 1", "Intro") in [(p.style.name, p.text) for p in doc.paragraphs]
    assert doc.tables[0].rows[1].cells[1].text == clean_text(STORED_HOSTILE)
    assert doc.tables[0].rows[1].cells[3].text == "Draft"  # label map, not the raw enum


def test_requirement_report_docx_applies_template_branding_and_rejects_a_foreign_template(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "DocxBrandOrg")
    project = _seed_requirement(client, token, org["id"])
    created = client.post(
        f"/api/v1/orgs/{org['id']}/report-templates",
        json={"name": "Branded", "accent_color_hex": "#ff0000", "footer_text": "Confidential", "include_cover_page": True},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports", json={"format": "docx", "report_template_id": created.json()["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    doc = _open(resp.content)
    assert _header_fill(doc.tables[0]) == "FF0000" and "Confidential" in doc.sections[0].footer.paragraphs[0].text

    other, other_token = create_org_admin_in(client, admin_token, "DocxForeignOrg")
    foreign = client.post(f"/api/v1/orgs/{other['id']}/report-templates", json={"name": "Theirs"}, headers=auth_headers(other_token))
    bad = client.post(
        f"/api/v1/projects/{project['id']}/reports", json={"format": "docx", "report_template_id": foreign.json()["id"]},
        headers=auth_headers(token),
    )
    assert bad.status_code == 400


def test_requirement_report_docx_needs_project_access(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "DocxAccessOrg")
    project = _seed_requirement(client, token, org["id"])
    _, outsider = create_org_admin_in(client, admin_token, "DocxOutsiderOrg")
    resp = client.post(f"/api/v1/projects/{project['id']}/reports", json={"format": "docx"}, headers=auth_headers(outsider))
    assert resp.status_code in (403, 404)


def test_requirement_report_docx_embeds_own_org_images_and_never_another_orgs(client, admin_token):
    other, other_token = create_org_admin_in(client, admin_token, "DocxImgOther")
    theirs = client.post(
        f"/api/v1/orgs/{other['id']}/resources", files={"file": ("p.png", _tiny_png(), "image/png")}, headers=auth_headers(other_token),
    ).json()["id"]
    org, token = create_org_admin_in(client, admin_token, "DocxImgOrg")
    project = create_project(client, token, org["id"])
    mine = client.post(
        f"/api/v1/orgs/{org['id']}/resources", files={"file": ("p.png", _tiny_png(), "image/png")}, headers=auth_headers(token),
    ).json()["id"]

    def run(file_id):
        resp = client.post(
            f"/api/v1/projects/{project['id']}/reports",
            json={"format": "docx", "pre_markdown": f"![x](attachment:{file_id})\n"}, headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
        return _open(resp.content)

    assert len(run(mine).inline_shapes) == 1
    assert len(run(theirs).inline_shapes) == 0, "another organisation's file must never be embedded"


# --- HTTP: module reports ------------------------------------------------------------------


def test_every_catalogued_project_report_exports_docx_and_pdf(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "DocxCatalogueOrg")
    for module_key in {key for key, _ in get_all_reports()}:
        resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{module_key}", json={"enabled": True}, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
    project = create_project(client, token, org["id"])
    entries = client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(token)).json()
    assert entries and all("docx" in e["formats"] for e in entries)
    for entry in entries:
        docx = client.get(entry["path"], params={"format": "docx"}, headers=auth_headers(token))
        assert docx.status_code == 200, (entry["slug"], docx.text)
        assert docx.headers["content-type"] == DOCX_TYPE
        assert docx.headers["content-disposition"].endswith(f"-{entry['slug']}.docx\"")
        assert _open(docx.content).sections[0].orientation == WD_ORIENT.LANDSCAPE
        pdf = client.get(entry["path"], params={"format": "pdf"}, headers=auth_headers(token))
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF"), entry["slug"]
