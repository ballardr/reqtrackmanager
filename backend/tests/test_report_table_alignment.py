"""
Module: tests.test_report_table_alignment

Tables with the same headings share one set of column widths (`services.report_table_alignment`).

Responsibilities:
- Pin, in every format, that the Review Package's Open Questions pair (two tables with the same nine headings and
  different content, as a module report widget emits them) has equal column widths once the rule has run.
- Pin the rule's edges: grouping, the author winning, the page-width split, idempotence, the organisation-wide run, and
  the PDF's gap between consecutive tables.

Design decisions:
- The same pair is what a single project, a merged project tree and an organisation run produce: the merge only adds a
  `Project` column or repeats the pair under another project's heading, and every table reaches the renderers as the
  same compact, width-less `Table`.
- The unaligned pair (`raw_pair`) is kept as the baseline, so a change in how a format sizes a lone table is visible.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import replace

import pytest
from docx import Document as DocxDocument
from reportlab.lib.units import cm

from app.services import report_pdf
from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import assert_valid, empty_tree, validate_tree
from app.services.report_model import Heading, PageStyle, PageStyleChange, ReportDocument, Table
from app.services.report_odt import render_odt_document
from app.services.report_table_alignment import align_tables

COLUMNS = ["Question", "Project", "Priority", "Status", "Owner", "Due", "Overdue", "Days open", "Tags"]
OPEN = [
    ["OQ-001 Which regulator signs off the data transfer?", "ACME", "High", "Open", "Sam Lee", "2026-10-01", "Overdue", "40", "legal"],
    ["OQ-002 Do we keep Q2 pricing?", "ACME-SUB", "Low", "Open", "Jo", "2026-12-01", "", "3", ""],
    ["OQ-003 Cut-over date", "ACME", "High", "Open", "Sam Lee", "2026-09-01", "Overdue", "90", ""],
]
OVERDUE = [OPEN[2]]


def raw_pair() -> ReportDocument:
    """A heading and the Open and Overdue tables, as the Review Package places them, before the alignment."""
    return ReportDocument(title="t", blocks=[
        Heading("Open Questions", 1), Table(COLUMNS, OPEN, compact=True), Table(COLUMNS, OVERDUE, compact=True),
    ])


def pair() -> ReportDocument:
    """`raw_pair` after the evaluator's alignment."""
    return align_tables(raw_pair())


def pdf_widths(document: ReportDocument, monkeypatch: pytest.MonkeyPatch) -> list[list[float]]:
    """The column widths in cm of each table the PDF renderer lays out, by watching `styled_table`."""
    seen: list[list[float]] = []
    real = report_pdf.styled_table

    def watch(data, col_widths, **keys):
        seen.append([round(w / cm, 2) for w in col_widths])
        return real(data, col_widths=col_widths, **keys)

    monkeypatch.setattr(report_pdf, "styled_table", watch)
    report_pdf.render_pdf_document(document)
    return seen


def docx_widths(document: ReportDocument) -> list[list[float]]:
    """The grid column widths in cm of each Word table."""
    return [[round(c.width.cm, 2) for c in t.columns] for t in DocxDocument(io.BytesIO(render_docx_document(document))).tables]


def odt_widths(document: ReportDocument) -> list[list[str]]:
    """The column widths of each OpenDocument table, in order (one style per column)."""
    package = zipfile.ZipFile(io.BytesIO(render_odt_document(document)))
    widths = re.findall(r'style:column-width="([\d.]+cm)"', package.read("content.xml").decode() + package.read("styles.xml").decode())
    count = len(COLUMNS)
    return [widths[i:i + count] for i in range(0, len(widths), count)]


def html_columns(document: ReportDocument) -> list[str]:
    """The `colgroup` (or its absence) of each table in the HTML preview."""
    html = render_html_document(document).decode()
    return [re.search(r"<colgroup>.*?</colgroup>", t, re.S).group(0) if "<colgroup>" in t else "" for t in html.split("<table")[1:]]


def test_the_unaligned_pair_is_sized_per_table(monkeypatch):
    """The baseline: the PDF sizes each table from its own cells and the preview leaves it to the browser; Word and
    OpenDocument give every column the same width, so they line up but ignore the content."""
    first, second = pdf_widths(raw_pair(), monkeypatch)
    assert first != second
    assert html_columns(raw_pair()) == ["", ""]
    assert all(len(set(w)) == 1 for w in docx_widths(raw_pair()))


def test_pdf_columns_line_up(monkeypatch):
    first, second = pdf_widths(pair(), monkeypatch)
    assert first == second


def test_word_columns_line_up():
    first, second = docx_widths(pair())
    assert first == second


def test_opendocument_columns_line_up():
    first, second = odt_widths(pair())
    assert first == second


def test_preview_columns_line_up():
    first, second = html_columns(pair())
    assert first and first == second
    assert render_html_document(pair()).decode().count('class="compact fixed"') == 2  # fixed, or the browser overrides the columns


def tables(document: ReportDocument) -> list[Table]:
    return [b for b in document.blocks if isinstance(b, Table)]


def test_word_and_opendocument_columns_follow_the_content():
    """Word and OpenDocument no longer give every column the same width."""
    assert len(set(docx_widths(pair())[0])) > 1
    assert len(set(odt_widths(pair())[0])) > 1


def test_the_group_takes_the_widest_need_and_fills_the_table():
    first, second = tables(pair())
    assert first.weights == second.weights and first.aligned and second.aligned
    assert sum(first.weights) == pytest.approx(raw_pair().style.usable_width_cm)
    assert first.weights[0] == max(first.weights)  # the question column is the widest


def test_a_lone_table_is_left_as_it_is():
    document = ReportDocument(title="t", blocks=[Table(COLUMNS, OPEN, compact=True)])
    assert align_tables(document) is document


def test_different_headings_are_not_grouped():
    document = ReportDocument(title="t", blocks=[Table(["A", "B"], [["x", "y"]]), Table(["A", "C"], [["x", "y"]])])
    assert align_tables(document) is document


def test_empty_and_one_column_tables_are_left_as_they_are():
    document = ReportDocument(title="t", blocks=[
        Table(COLUMNS, [], compact=True), Table(COLUMNS, OPEN, compact=True),
        Table(["A"], [["x"]]), Table(["A"], [["y"]]),
    ])
    assert align_tables(document) is document


def test_an_author_forced_width_or_an_engine_weight_wins():
    forced = Table(COLUMNS, OPEN, compact=True, widths=["30%"] + [None] * 8)
    weighted = Table(COLUMNS, OPEN, compact=True, weights=[1.0] * 8 + [3.0])
    plain = Table(COLUMNS, OVERDUE, compact=True)
    result = align_tables(ReportDocument(title="t", blocks=[forced, weighted, plain]))
    assert tables(result) == [forced, weighted, plain]


def test_a_section_with_another_page_width_is_a_separate_group():
    wide = PageStyle(page_size="A3", landscape=True)
    document = ReportDocument(title="t", blocks=[
        Table(COLUMNS, OPEN, compact=True), PageStyleChange(wide), Table(COLUMNS, OVERDUE, compact=True),
        Table(COLUMNS, OPEN, compact=True),
    ])
    first, second, third = tables(align_tables(document))
    assert first.weights is None and not first.aligned
    assert second.weights == third.weights
    assert sum(second.weights) == pytest.approx(wide.usable_width_cm)


def test_aligning_twice_recomputes_from_the_content():
    """The organisation-wide run aligns again after joining the projects' documents, so an aligned table is regrouped."""
    once = raw_pair()
    other = ReportDocument(title="t", blocks=[Table(COLUMNS, [["OQ-9 " + "x" * 80] + OPEN[0][1:]], compact=True)])
    first = align_tables(once)
    joined = replace(first, blocks=[*first.blocks, *align_tables(other).blocks])
    again = tables(align_tables(joined))
    assert len({tuple(t.weights) for t in again}) == 1
    assert again[0].weights != tables(first)[0].weights
    assert align_tables(joined) == align_tables(align_tables(joined))


def test_the_pdf_separates_consecutive_tables(monkeypatch):
    """A gap follows a table only when the next block is also a table."""
    seen: list[str] = []
    real = report_pdf.Spacer

    def watch(width, height):
        seen.append(round(height / cm, 2))
        return real(width, height)

    monkeypatch.setattr(report_pdf, "Spacer", watch)
    report_pdf.render_pdf_document(raw_pair())
    assert report_pdf.TABLE_GAP_CM in seen


def test_the_pdf_adds_no_gap_after_a_last_table(monkeypatch):
    seen: list[float] = []
    real = report_pdf.Spacer
    monkeypatch.setattr(report_pdf, "Spacer", lambda w, h: (seen.append(round(h / cm, 2)), real(w, h))[1])
    report_pdf.render_pdf_document(ReportDocument(title="t", blocks=[Table(COLUMNS, OPEN, compact=True)]))
    assert report_pdf.TABLE_GAP_CM not in seen


# ---- the layout switch and a module report's usual widths ----------------------------------------------------------

USUAL = [None, None, "8%", "9%", None, "9%", "8%", "8%", None]


def test_a_layout_that_turns_the_rule_off_keeps_every_table_as_it_was():
    off = replace(raw_pair(), align_tables=False)
    assert align_tables(off) is off


def test_usual_widths_fix_their_columns_and_the_rest_share_by_content():
    document = ReportDocument(title="t", blocks=[Table(COLUMNS, OPEN, compact=True, usual_widths=USUAL)])
    (table,) = tables(align_tables(document))
    usable = document.style.usable_width_cm
    assert table.aligned and sum(table.weights) == pytest.approx(usable)
    assert table.weights[2] == pytest.approx(0.08 * usable) and table.weights[3] == pytest.approx(0.09 * usable)
    assert table.weights[0] > table.weights[1]  # the question outgrows the project name


def test_a_group_with_usual_widths_lines_up_on_them():
    document = ReportDocument(title="t", blocks=[
        Table(COLUMNS, OPEN, compact=True, usual_widths=USUAL), Table(COLUMNS, OVERDUE, compact=True, usual_widths=USUAL),
    ])
    first, second = tables(align_tables(document))
    assert first.weights == second.weights
    assert first.weights[2] == pytest.approx(0.08 * document.style.usable_width_cm)


def test_usual_widths_are_not_applied_when_the_rule_is_off():
    document = ReportDocument(title="t", blocks=[Table(COLUMNS, OPEN, compact=True, usual_widths=USUAL)], align_tables=False)
    assert align_tables(document) is document


def test_a_table_without_usual_widths_is_still_left_alone_when_alone():
    document = ReportDocument(title="t", blocks=[Table(COLUMNS, OPEN, compact=True)])
    assert align_tables(document) is document


def test_an_author_forced_width_beats_usual_widths():
    forced = Table(COLUMNS, OPEN, compact=True, widths=["30%"] + [None] * 8, usual_widths=USUAL)
    document = ReportDocument(title="t", blocks=[forced])
    assert align_tables(document) is document


def test_the_switch_is_a_document_boolean_that_reads_back_through_the_text_view():
    tree = {**empty_tree("document"), "align_tables": False}
    assert_valid(tree)
    assert format_tree(tree).splitlines()[0] == "@layout document portrait noalign"
    assert parse_text(format_tree(tree)).tree == tree
    explicit = {**empty_tree("document"), "align_tables": True}
    assert " align" in format_tree(explicit).splitlines()[0] and parse_text(format_tree(explicit)).tree == explicit
    assert "align_tables" not in parse_text(format_tree(empty_tree("document"))).tree
    assert [e.path for e in validate_tree({**tree, "align_tables": "no"}).errors] == ["align_tables"]
    assert [e.path for e in validate_tree({**empty_tree("table"), "align_tables": False}).errors] == ["align_tables"]
