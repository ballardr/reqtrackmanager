"""Tests for the table-of-contents block (`contents`): tree validation, the text view, the headings it lists, one contents for
a joined multi-project report, and the four renderers read as rendered (PDF page numbers, a Word TOC field and an OpenDocument
index with every entry written in and linked, HTML links). No database except the evaluator test."""

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
from docx.oxml.ns import qn

from app.database import SessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.services.link_graph import ArtefactResolver
from app.services.report_docx import render_docx_document
from app.services.report_framework import ReportContext
from app.services.report_html import render_html_document
from app.services.report_layout_eval import EvalStats, EvaluatedLayout, evaluate_layout
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import BLOCK_SPECS, FAMILY_DOCUMENT, FAMILY_TABLE, empty_tree, validate_tree
from app.services.report_model import (
    MAX_CONTENTS_ENTRIES,
    Contents,
    ContentsEntry,
    Heading,
    MathText,
    PageBreak,
    Paragraph,
    ReportDocument,
    finalize_links,
)
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from tests.link_world import World


def tree(*nodes: dict[str, Any], family: str = FAMILY_DOCUMENT) -> dict[str, Any]:
    return {**empty_tree(family), "nodes": list(nodes)}


def problems(*nodes: dict[str, Any], family: str = FAMILY_DOCUMENT) -> dict[str, str]:
    return {e.path: e.message for e in validate_tree(tree(*nodes, family=family)).errors}


# ---- the tree ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", [
    {"type": "contents"},
    {"type": "contents", "title": "Inhalt", "levels": 1, "new_page": False},
    {"type": "contents", "title": "", "levels": 3},
    {"type": "contents", "title": "Contents of {{report_title}}"},
])
def test_a_contents_block_with_valid_settings_is_valid(node):
    assert problems(node) == {}


@pytest.mark.parametrize(("node", "path"), [
    ({"type": "contents", "levels": 0}, "nodes[0].levels"),
    ({"type": "contents", "levels": 4}, "nodes[0].levels"),
    ({"type": "contents", "levels": True}, "nodes[0].levels"),
    ({"type": "contents", "levels": "2"}, "nodes[0].levels"),
    ({"type": "contents", "new_page": "yes"}, "nodes[0].new_page"),
    ({"type": "contents", "title": 5}, "nodes[0].title"),
    ({"type": "contents", "title": "x" * 201}, "nodes[0].title"),
    ({"type": "contents", "title": "{{nope}}"}, "nodes[0].title"),
    ({"type": "contents", "colour": "red"}, "nodes[0].colour"),
])
def test_a_bad_contents_setting_is_named(node, path):
    assert path in problems(node)


def test_a_layout_holds_one_contents_and_the_second_is_named():
    found = problems({"type": "contents"}, {"type": "heading", "text": "A"}, {"type": "contents"})
    assert list(found) == ["nodes[2]"]
    assert "nodes[0]" in found["nodes[2]"]


def test_a_contents_cannot_sit_inside_a_repeating_or_page_bottom_block():
    repeated = problems({"type": "each", "source": {"record_type": "requirement"}, "as": "r", "children": [{"type": "contents"}]})
    assert "once for every record" in repeated["nodes[0].children[0]"]
    grouped = problems({"type": "group", "source": {"record_type": "requirement"}, "by": "status", "as": "g", "children": [{"type": "contents"}]})
    assert "nodes[0].children[0]" in grouped
    bottom = problems({"type": "bottom", "children": [{"type": "contents"}]})
    assert "page bottom" in bottom["nodes[0].children[0]"]


def test_a_contents_inside_a_section_or_an_if_is_allowed():
    assert problems({"type": "if", "when": {"module": "risk_management"}, "children": [{"type": "contents"}]}) == {}


def test_a_table_layout_cannot_hold_a_contents():
    assert "nodes[0].type" in problems({"type": "contents"}, family=FAMILY_TABLE)


def test_the_block_declares_its_schema_for_the_designer():
    schema = BLOCK_SPECS["contents"].schema
    assert schema is not None and schema.label == "Table of contents"
    assert [f.key for f in schema.fields] == ["title", "levels", "new_page"]
    assert all(f.help for f in schema.fields)


# ---- the text view ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "@contents",
    '@contents "Inhalt"',
    "@contents levels 2",
    "@contents nonewpage",
    '@contents "Index" levels 1 newpage',
    '@contents ""',
])
def test_a_contents_line_round_trips_through_the_text_view(line):
    text = f"@layout document\n\n{line}\n"
    parsed = parse_text(text)
    assert parsed.ok
    assert format_tree(parsed.tree).strip().splitlines()[-1] == line


def test_the_text_view_reads_the_settings_into_the_tree():
    parsed = parse_text('@layout document\n\n@contents "Inhalt" levels 2 nonewpage\n')
    assert parsed.tree["nodes"] == [{"type": "contents", "title": "Inhalt", "levels": 2, "new_page": False}]


@pytest.mark.parametrize(
    "line", ["@contents levels", "@contents levels two", "@contents levels 2 levels 3", "@contents bogus", "@contents nonewpage newpage"],
)
def test_a_malformed_contents_line_is_a_text_error(line):
    parsed = parse_text(f"@layout document\n\n{line}\n")
    assert not parsed.ok and parsed.errors[0].line == 3


def test_a_second_contents_in_the_text_view_points_at_its_line():
    parsed = parse_text("@layout document\n\n@contents\n@heading A\n@contents\n")
    assert [e.line for e in parsed.errors] == [5]


# ---- the headings it lists ---------------------------------------------------------------------------------------


def listed(*blocks: Any, **settings: Any) -> tuple[ContentsEntry, ...]:
    document = finalize_links(ReportDocument("T", [Contents(**settings), *blocks]))
    contents = document.blocks[0]
    assert isinstance(contents, Contents)
    return contents.entries


def test_the_contents_lists_every_heading_in_reading_order_with_its_anchor_and_level():
    entries = listed(Heading("One", 1), Paragraph("x"), Heading("Two", 2), Heading("Two", 2))
    assert [(e.text, e.level, e.anchor) for e in entries] == [("One", 1, "one"), ("Two", 2, "two"), ("Two", 2, "two-2")]


def test_a_heading_before_the_contents_is_listed_too():
    document = finalize_links(ReportDocument("T", [Heading("Cover", 1), Contents(), Heading("Body", 1)]))
    assert [e.text for e in document.blocks[1].entries] == ["Cover", "Body"]


def test_only_the_levels_asked_for_are_listed():
    blocks = [Heading("A", 1), Heading("B", 2), Heading("C", 3), Heading("D", 4)]
    assert [e.text for e in listed(*blocks, levels=1)] == ["A"]
    assert [e.text for e in listed(*blocks, levels=2)] == ["A", "B"]
    assert [e.text for e in listed(*blocks, levels=3)] == ["A", "B", "C"]


def test_a_heading_is_listed_by_its_words_not_its_styling():
    assert [e.text for e in listed(Heading(MathText(["Cost of ", "x"]), 1))] == ["Cost of x"]


def test_the_contents_own_title_is_not_a_heading_and_a_document_with_no_headings_lists_nothing():
    assert listed(Paragraph("x"), title="Contents") == ()


def test_the_entries_are_bounded():
    entries = listed(*[Heading(f"H{n}", 1) for n in range(MAX_CONTENTS_ENTRIES + 50)])
    assert len(entries) == MAX_CONTENTS_ENTRIES


# ---- the evaluator and a joined run -------------------------------------------------------------------------------


def test_the_evaluator_emits_the_block_with_its_settings_and_the_title_filled(client, admin_token):
    world = World(client, admin_token, "Contents Org", context_strategy=True)
    project = world.project("Contents P")
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        org = db.get(Organization, uuid.UUID(world.org["id"]))
        ctx = ReportContext(module_key="reporting", organization=org, projects=[row], root_project=row)
        layout = tree({"type": "contents", "title": "Index of {{project_name}}", "levels": 2, "new_page": False}, {"type": "heading", "text": "A"})
        out = evaluate_layout(db, ArtefactResolver(db, row, world.user_id, include_related=True), ctx, layout, title="R")
    finally:
        db.close()
    assert out.document is not None
    block = out.document.blocks[0]
    assert block == Contents(title="Index of Contents P", levels=2, new_page=False, entries=())


def test_a_joined_report_has_one_contents_listing_every_projects_headings():
    from app.services.custom_report_run import merge_evaluations

    def part(name: str) -> EvaluatedLayout:
        document = ReportDocument("T", [Contents(levels=3), Heading(f"{name} scope", 1), Heading(f"{name} detail", 2)], show_title=False)
        return EvaluatedLayout("document", document, [], [], EvalStats(), "", {}, False, [], {})

    alpha, beta = Project(id=uuid.uuid4(), name="Alpha"), Project(id=uuid.uuid4(), name="Beta")
    merged = merge_evaluations([(alpha, part("Alpha")), (beta, part("Beta"))], "Report")
    assert merged.document is not None
    assert len([b for b in merged.document.blocks if isinstance(b, Contents)]) == 1
    contents = finalize_links(merged.document).blocks[0 if isinstance(merged.document.blocks[0], Contents) else 1]
    assert [e.text for e in contents.entries] == ["Alpha", "Alpha scope", "Alpha detail", "Beta", "Beta scope", "Beta detail"]
    assert [e.level for e in contents.entries] == [1, 2, 3, 1, 2, 3]


# ---- the renderers, read as rendered -------------------------------------------------------------------------------

CHAPTERS = 5


def sample(*, new_page: bool = True, levels: int = 2, title: str = "Contents") -> ReportDocument:
    blocks: list[Any] = [Heading("Cover", 1), Contents(title=title, levels=levels, new_page=new_page)]
    for n in range(1, CHAPTERS + 1):
        blocks += [Heading(f"Chapter {n}", 1), Paragraph("Body. " * 30), Heading(f"Section {n}.1", 2), Heading(f"Detail {n}", 3), PageBreak()]
    return ReportDocument("T", blocks, show_title=False)


def first_page_texts(pdf: bytes) -> list[str]:
    """Every text string drawn on the first page, in drawing order."""
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            content = zlib.decompress(base64.a85decode(raw.strip(), adobe=True)).decode("latin-1")
        except Exception:  # noqa: BLE001 - not a page
            continue
        if " Tm (" in content:
            return re.findall(r"Tm \((.*?)\) Tj", content)
    return []


def first_page_strings(pdf: bytes) -> str:
    """Everything drawn as text on the first page, run together."""
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            content = zlib.decompress(base64.a85decode(raw.strip(), adobe=True)).decode("latin-1")
        except Exception:  # noqa: BLE001 - not a page
            continue
        if " Tm (" in content or " Tf" in content:
            return "".join(re.findall(r"\(((?:[^()\\]|\\.)*)\)", content)).replace("\\(", "(").replace("\\)", ")")
    return ""


def test_the_pdf_prints_each_headings_real_page_number():
    texts = first_page_texts(render_pdf_document(sample()))
    numbers = [t for t in texts if t.isdigit()]
    # Cover is on page 1 with the contents; each chapter starts a page after the contents' page break, its section on the same page.
    assert numbers == ["1", *[str(n + 1) for n in range(1, CHAPTERS + 1) for _ in (0, 1)]]


def test_the_pdf_numbers_hold_when_the_contents_runs_over_more_than_one_page():
    blocks: list[Any] = [Contents(levels=1)]
    for n in range(1, 120):
        blocks += [Heading(f"Chapter {n} with enough words to be a real line of the contents", 1), PageBreak()]
    pdf = render_pdf_document(ReportDocument("T", blocks, show_title=False))
    pages = len(re.findall(rb"/Type /Page\b", pdf))
    # the contents fills pages 1 and 2, so chapter 1 is on page 3 and the last chapter is on the last page
    texts = first_page_texts(pdf)
    assert "3" in [t for t in texts if t.isdigit()] and pages >= 119


def test_without_a_new_page_the_pdf_has_one_page_less():
    with_break = len(re.findall(rb"/Type /Page\b", render_pdf_document(sample(new_page=True))))
    without = len(re.findall(rb"/Type /Page\b", render_pdf_document(sample(new_page=False))))
    assert with_break == without + 1


def test_a_pdf_contents_with_nothing_to_list_prints_nothing_and_no_break():
    with_contents = render_pdf_document(ReportDocument("T", [Contents(), Paragraph("Just text.")], show_title=False))
    without = render_pdf_document(ReportDocument("T", [Paragraph("Just text.")], show_title=False))
    assert len(re.findall(rb"/Type /Page\b", with_contents)) == len(re.findall(rb"/Type /Page\b", without)) == 1
    assert "Contents" not in first_page_strings(with_contents)


def test_the_pdf_title_and_entry_words_are_escaped_not_read_as_markup():
    doc = ReportDocument("T", [Contents(title="<b>Index</b>"), Heading("<img src='file:///etc/passwd'/> & more", 1)], show_title=False)
    drawn = first_page_strings(render_pdf_document(doc))
    assert "<b>Index</b>" in drawn and "<img src='file:///etc/passwd'/>" in drawn


def word_paragraphs(data: bytes) -> list[tuple[str, str]]:
    doc = DocxDocument(io.BytesIO(data))
    return [(p.style.name, p.text) for p in doc.paragraphs]


def test_word_gets_a_real_toc_field_with_every_entry_written_in_linked_and_no_page_numbers():
    data = render_docx_document(sample())
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert xml.count('w:fldCharType="begin"') == 1 and xml.count('w:fldCharType="end"') == 1  # no PAGE fields: no footer here
    assert ' TOC \\o "1-2" \\h \\z \\u ' in xml
    assert "PAGEREF" not in xml
    entries = [(style, text) for style, text in word_paragraphs(data) if style.startswith("toc ")]
    assert [text for _, text in entries] == ["Cover", *[t for n in range(1, CHAPTERS + 1) for t in (f"Chapter {n}", f"Section {n}.1")]]
    assert {style for style, _ in entries} == {"toc 1", "toc 2"}
    # every entry points at a bookmark a heading carries
    anchors = set(re.findall(r'<w:hyperlink w:anchor="(sec_[0-9a-f]+)"', xml))
    bookmarks = set(re.findall(r'<w:bookmarkStart w:id="\d+" w:name="(sec_[0-9a-f]+)"', xml))
    assert len(anchors) == 1 + CHAPTERS * 2 and anchors <= bookmarks
    assert not [text for _, text in entries if re.search(r"\d+$", text) and "Chapter" not in text and "Section" not in text]


def test_the_word_title_is_not_a_heading_so_the_field_never_lists_it():
    data = render_docx_document(sample())
    titles = [(style, text) for style, text in word_paragraphs(data) if text == "Contents"]
    assert titles == [("TOC Heading", "Contents")]
    doc = DocxDocument(io.BytesIO(data))
    outline = doc.styles["TOC Heading"].element.find(qn("w:pPr")).find(qn("w:outlineLvl"))
    assert outline is not None and outline.get(qn("w:val")) == "9"


def test_the_word_toc_styles_carry_a_right_tab_with_dot_leaders_for_when_the_field_is_updated():
    doc = DocxDocument(io.BytesIO(render_docx_document(sample())))
    tabs = doc.styles["toc 1"].paragraph_format.tab_stops
    assert len(tabs) == 1 and str(tabs[0].leader).startswith("DOTS") and str(tabs[0].alignment).startswith("RIGHT")


def test_word_writes_nothing_for_a_contents_with_no_entries():
    data = render_docx_document(ReportDocument("T", [Contents(), Paragraph("Just text.")], show_title=False))
    assert "fldChar" not in zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()


def test_word_escapes_entry_text_and_builds_no_field_instruction_from_it():
    data = render_docx_document(ReportDocument("T", [Contents(), Heading('"\\ \\o <w:p/> & x', 1)], show_title=False))
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert xml.count("<w:instrText") == 1 and "<w:p/>" not in xml


def odt_content(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("content.xml").decode()


def test_opendocument_gets_an_index_with_written_in_linked_entries_and_no_page_numbers():
    xml = odt_content(render_odt_document(sample()))
    assert xml.count("<text:table-of-content ") == 1 and 'text:outline-level="2"' in xml
    body = xml[xml.index("<text:index-body>"):xml.index("</text:index-body>")]
    links = re.findall(r'xlink:href="#([^"]+)"[^>]*>([^<]*)</text:a>', body)
    assert [text for _, text in links] == ["Cover", *[t for n in range(1, CHAPTERS + 1) for t in (f"Chapter {n}", f"Section {n}.1")]]
    marks = set(re.findall(r'<text:bookmark text:name="([^"]+)"/>', xml))
    assert {anchor for anchor, _ in links} <= marks
    assert "index-entry-page-number" in xml and "<text:tab" not in body  # numbers only after a person updates the index


def test_opendocument_entry_templates_follow_the_levels_asked_for():
    xml = odt_content(render_odt_document(sample(levels=1)))
    assert xml.count("<text:table-of-content-entry-template ") == 1


def test_opendocument_escapes_entry_text_and_writes_nothing_for_an_empty_contents():
    xml = odt_content(render_odt_document(ReportDocument("T", [Contents(title="A & B"), Heading("<x>", 1)], show_title=False)))
    assert "A &amp; B" in xml and "&lt;x&gt;" in xml
    empty = odt_content(render_odt_document(ReportDocument("T", [Contents(), Paragraph("x")], show_title=False)))
    assert "table-of-content" not in empty


def test_html_lists_links_to_the_heading_ids_and_no_page_numbers():
    html = render_html_document(sample()).decode()
    nav = html[html.index('<nav class="contents"'):html.index("</nav>")]
    hrefs = re.findall(r'<a href="#([^"]+)">([^<]*)</a>', nav)
    assert [text for _, text in hrefs] == ["Cover", *[t for n in range(1, CHAPTERS + 1) for t in (f"Chapter {n}", f"Section {n}.1")]]
    assert all(f'id="{anchor}"' in html for anchor, _ in hrefs)
    assert 'aria-label="Contents"' in nav


def test_html_escapes_the_title_and_the_entries_and_omits_an_empty_contents():
    html = render_html_document(ReportDocument("T", [Contents(title="<i>x</i>"), Heading("<script>1</script>", 1)], show_title=False)).decode()
    assert "<script>1" not in html and "&lt;script&gt;" in html and "<i>x" not in html
    assert "<nav" not in render_html_document(ReportDocument("T", [Contents(), Paragraph("x")], show_title=False)).decode()
