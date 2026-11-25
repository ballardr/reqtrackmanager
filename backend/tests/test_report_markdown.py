"""Tests for `services.report_markdown`: the one Markdown walk behind every report format. The author reader (a layout's own
text) keeps its narrow inline reading, the record reader reads as the screen does, and both turn block structure (nested
lists, quotations, code, tables, diagrams) into neutral blocks."""

from __future__ import annotations

import pytest

from app.services import report_diagram
from app.services.report_diagram import DiagramBudget, DiagramError, DrawnDiagram
from app.services.report_markdown import MAX_TABLE_COLUMNS, MAX_TABLE_ROWS, record_markdown_blocks
from app.services.report_model import (
    BulletList,
    CodeBlock,
    Gap,
    Grid,
    Image,
    MathText,
    NumberedList,
    Paragraph,
    Quote,
    Styled,
    list_entries,
    markdown_to_blocks,
)

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20" viewBox="0 0 40 20"><rect width="40" height="20"/></svg>'


def real(blocks: list) -> list:
    """The blocks without the spacing hints."""
    return [b for b in blocks if not isinstance(b, Gap)]


@pytest.fixture()
def drawing(monkeypatch):
    """A converter stand-in: every diagram is drawn as the same small rectangle, except text containing `broken`."""
    asked: list[str] = []

    def post(source: str, theme: str) -> bytes:
        asked.append(source)
        if "broken" in source:
            raise DiagramError("Parse error on line 2")
        return SVG.encode()

    monkeypatch.setattr(report_diagram, "_post", post)
    report_diagram.clear_cache()
    yield asked
    report_diagram.clear_cache()


# ---- block structure, both readers ---------------------------------------------------------------------------------


@pytest.mark.parametrize("read", [markdown_to_blocks, record_markdown_blocks], ids=["author", "record"])
def test_headings_paragraphs_and_inline_styles_are_read_by_both_readers(read):
    found = real(read("# Title\n\nA **bold** and *italic* and `code` word.\n"))

    assert found[0].text == "Title" and isinstance(found[1], Paragraph)
    runs = found[1].text.parts
    assert [(r.text, r.bold, r.italic, r.code) for r in runs if isinstance(r, Styled)] == [
        ("bold", True, False, False), ("italic", False, True, False), ("code", False, False, True),
    ]


@pytest.mark.parametrize("read", [markdown_to_blocks, record_markdown_blocks], ids=["author", "record"])
def test_a_list_may_nest_and_mix_numbered_and_bulleted_items(read):
    block = real(read("1. one\n   - a\n     - deep\n   - b\n2. two\n"))[0]

    assert isinstance(block, NumberedList)
    assert [(e.text, e.level, e.ordered) for e in list_entries(block)] == [
        ("one", 0, True), ("a", 1, False), ("deep", 2, False), ("b", 1, False), ("two", 0, True),
    ]


@pytest.mark.parametrize("read", [markdown_to_blocks, record_markdown_blocks], ids=["author", "record"])
def test_a_flat_list_keeps_the_plain_shape_every_renderer_already_reads(read):
    block = real(read("- a\n- b\n"))[0]

    assert isinstance(block, BulletList) and block.items == ["a", "b"] and block.levels == () and block.ordered == ()


@pytest.mark.parametrize("read", [markdown_to_blocks, record_markdown_blocks], ids=["author", "record"])
def test_a_quotation_a_fence_and_a_table_become_their_own_blocks(read):
    found = real(read("> said\n\n```python\nx = 1\n  y = 2\n```\n\n| A | B |\n|:--|--:|\n| 1 | 2 |\n"))

    assert found[0] == Quote("said")
    assert found[1] == CodeBlock("x = 1\n  y = 2", "python")
    grid = found[2]
    assert isinstance(grid, Grid) and grid.header_rows == 1
    head, body = grid.rows
    assert [c.paragraphs for c in head.cells] == [("A",), ("B",)] and all(c.bold for c in head.cells)
    assert [c.align for c in body.cells] == ["left", "right"] and not any(c.bold for c in body.cells)


def test_an_indented_block_is_code_where_it_used_to_be_dropped_without_a_word():
    assert real(markdown_to_blocks("text\n\n    indented\n")) == [Paragraph("text"), CodeBlock("indented", "")]


def test_a_rule_is_a_gap_and_nothing_else_is_made_of_unknown_syntax():
    found = markdown_to_blocks("a\n\n---\n\nb\n")

    assert [b for b in found if not isinstance(b, Gap)] == [Paragraph("a"), Paragraph("b")] and Gap(0.4) in found


def test_a_table_wider_than_the_limit_is_cut_with_a_warning_too():
    wide = "| h |" + " h |" * (MAX_TABLE_COLUMNS + 1) + "\n|" + "---|" * (MAX_TABLE_COLUMNS + 2) + "\n| 1 |" + " 2 |" * (MAX_TABLE_COLUMNS + 1) + "\n"
    warnings: list[str] = []

    grid = real(record_markdown_blocks(wide, warn=warnings.append))[0]

    assert all(len(r.cells) == MAX_TABLE_COLUMNS for r in grid.rows) and len(warnings) == 1


def test_a_table_is_cut_at_its_limits_with_a_warning():
    rows = "\n".join(f"| {n} |" + " x |" * (MAX_TABLE_COLUMNS + 2) for n in range(MAX_TABLE_ROWS + 5))
    header = "| h |" + " h |" * (MAX_TABLE_COLUMNS + 2) + "\n|" + "---|" * (MAX_TABLE_COLUMNS + 3) + "\n"
    warnings: list[str] = []

    grid = real(record_markdown_blocks(header + rows, warn=warnings.append))[0]

    assert len(grid.rows) <= MAX_TABLE_ROWS and all(len(r.cells) <= MAX_TABLE_COLUMNS for r in grid.rows)
    assert warnings and "cut" in warnings[0]


# ---- what only the record reader does -----------------------------------------------------------------------------


def test_a_heading_in_a_record_sits_below_the_heading_the_report_printed_for_the_record():
    found = real(record_markdown_blocks("# one\n## two\n#### four\n"))

    assert [(h.text, h.level) for h in found] == [("one", 3), ("two", 4), ("four", 4)]
    assert [h.level for h in real(record_markdown_blocks("# one\n", heading_offset=0))] == [1]
    assert real(markdown_to_blocks("# one\n## two\n"))[0].level == 1  # an author's own heading is not shifted


def test_the_record_reader_reads_what_the_screen_reads_and_leaves_the_rest_as_typed():
    text = real(record_markdown_blocks("A \\*star\\* and <https://example.com> and ~~gone~~ and <b>html</b> ![alt](x.png)\n"))[0].text

    assert "*star*" in text and "~~gone~~" in text and "<b>html</b>" in text and "![alt](x.png)" in text
    assert any(isinstance(p, Styled) and p.href == "https://example.com" for p in text.parts)


def test_a_link_is_a_link_only_when_the_report_allows_it():
    text = real(record_markdown_blocks("[ok](https://example.com) [bad](javascript:alert(1)) [mail](mailto:a@b.example)\n"))[0].text

    hrefs = [p.href for p in text.parts if isinstance(p, Styled) and p.href]
    assert hrefs == ["https://example.com", "mailto:a@b.example"] and "[bad](javascript:alert(1))" in str(text)


def test_a_record_value_is_never_filled_in_or_read_for_the_layouts_placeholders():
    found = real(record_markdown_blocks("{{project_name}} and {{record.title}}\n"))

    assert found == [Paragraph("{{project_name}} and {{record.title}}")]
    assert real(markdown_to_blocks("{{project_name}}\n", placeholders={"project_name": "# Not a heading"})) == [Paragraph("# Not a heading")]


def test_equations_are_kept_as_written_for_the_caller_to_draw_only_where_the_field_has_them():
    with_math = real(record_markdown_blocks(r"Stress \(a_1 * b_2\) and $$x * y$$", math=True))[0].text
    without = real(record_markdown_blocks(r"Stress \(a_1 * b_2\)"))[0].text

    assert str(with_math) == r"Stress \(a_1 * b_2\) and $$x * y$$" and not isinstance(with_math, MathText)
    assert str(without) == "Stress (a_1 * b_2)"  # no equations here, so the reader's own escape rule applies


def test_a_document_nested_past_the_readers_limit_neither_crashes_nor_loops():
    deep = "> " * 400 + "end"

    assert record_markdown_blocks(deep) is not None
    assert record_markdown_blocks("- a\n" + "".join("  " * n + "- b\n" for n in range(1, 120))) is not None


def test_blank_text_has_no_blocks():
    assert record_markdown_blocks("  \n") == [] and markdown_to_blocks("") == []


# ---- diagrams ---------------------------------------------------------------------------------------------------------


def test_a_mermaid_fence_becomes_a_drawn_diagram_with_a_text_alternative(drawing):
    found = real(record_markdown_blocks("```mermaid\nflowchart LR\n A-->B\n```\n", diagrams=DiagramBudget()))

    assert len(found) == 1 and isinstance(found[0], Image)
    assert found[0].svg and found[0].raster and found[0].alt == "Diagram (flowchart)" and found[0].align == "center"
    assert drawing == ["flowchart LR\n A-->B"]


def test_the_text_alternative_names_what_the_drawing_prints(monkeypatch):
    drawn = DrawnDiagram(SVG, 40, 20, "Start, End")
    monkeypatch.setattr(report_diagram.DiagramBudget, "draw", lambda self, source, theme="light": drawn)

    found = real(record_markdown_blocks("```mermaid\nsequenceDiagram\n A->>B: Hi\n```\n", diagrams=DiagramBudget()))

    assert found[0].alt == "Diagram (sequenceDiagram): Start, End"


def test_a_diagram_that_cannot_be_drawn_is_printed_as_its_source_with_a_warning_never_failing_the_report(drawing):
    warnings: list[str] = []

    found = real(record_markdown_blocks("before\n\n```mermaid\nbroken\n```\n\nafter\n", diagrams=DiagramBudget(), warn=warnings.append))

    assert [type(b) for b in found] == [Paragraph, CodeBlock, Paragraph]
    assert found[1].text == "broken" and found[1].language == "mermaid" and "could not be drawn" in found[1].label
    assert warnings == ["A diagram is shown as its text. Parse error on line 2"]


def test_without_a_budget_a_diagram_is_its_source_and_nothing_is_asked_of_the_converter(drawing):
    found = real(record_markdown_blocks("```mermaid\nflowchart LR\n A-->B\n```\n"))

    assert found == [CodeBlock("flowchart LR\n A-->B", "mermaid", "Diagram source")] and drawing == []


def test_other_fenced_languages_are_code_not_diagrams(drawing):
    found = real(record_markdown_blocks("```sql\nselect 1\n```\n", diagrams=DiagramBudget()))

    assert found == [CodeBlock("select 1", "sql")] and drawing == []


def test_a_diagram_in_a_layouts_own_text_is_drawn_too(drawing):
    found = real(markdown_to_blocks("```mermaid\nflowchart LR\n A-->B\n```\n", diagrams=DiagramBudget()))

    assert isinstance(found[0], Image) and found[0].raster
