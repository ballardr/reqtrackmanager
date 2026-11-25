"""One fixture document of Markdown through all four report formats, with the structure asserted from what each format wrote:
formatted text, nested lists, a quotation, code that keeps its indentation, a table and a drawn diagram."""

from __future__ import annotations

import io
import re
import zipfile

import pytest
from docx import Document
from docx.oxml.ns import qn

from app.services import report_diagram, report_pdf
from app.services.custom_report_run import _sections_of_document
from app.services.report_diagram import DiagramBudget, DiagramError
from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_markdown import record_markdown_blocks
from app.services.report_model import Heading, ReportDocument, Table
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document

SVG = (
    '<svg id="my-svg" width="100%" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60" style="max-width: 120px;">'
    '<style>#my-svg .box{fill:#ececff;stroke:#9370db}</style>'
    '<g class="box"><rect width="100" height="40"/><text x="10" y="25">Start</text></g></svg>'
)
MARKDOWN = """# Rationale

We chose **PostgreSQL** because *consistency* matters; see [the guide](https://example.com/guide) and `psql`.

1. Keep the store
   - cheap
     - very risky
2. Move to PostgreSQL

> Quoted guidance
> from the board

```python
def f(x):
    return x  *  2
```

| Option | Cost |
|--------|-----:|
| Keep   | 10   |

```mermaid
flowchart LR
  A-->B
```

```mermaid
broken
```
"""


@pytest.fixture()
def document(monkeypatch) -> tuple[ReportDocument, list[str]]:
    def post(source: str, theme: str) -> bytes:
        if source == "broken":
            raise DiagramError("Parse error")
        return SVG.encode()

    monkeypatch.setattr(report_diagram, "_post", post)
    report_diagram.clear_cache()
    warnings: list[str] = []
    blocks = record_markdown_blocks(MARKDOWN, diagrams=DiagramBudget(), warn=warnings.append)
    yield ReportDocument("Fixture", [Heading("Decision DEC-001", 1), *blocks]), warnings
    report_diagram.clear_cache()


def test_the_document_carries_a_drawn_diagram_and_a_warning_for_the_one_that_could_not_be_drawn(document):
    _, warnings = document

    assert warnings == ["A diagram is shown as its text. Parse error"]


def test_html_has_the_structure_and_the_diagram_inline_without_a_style_sheet(document):
    page = render_html_document(document[0]).decode()
    body = page.split("<body>")[1]

    assert "<strong>PostgreSQL</strong>" in body and "<em>consistency</em>" in body and "<code>psql</code>" in body
    assert 'href="https://example.com/guide"' in body
    assert "<ol><li>Keep the store<ul><li>cheap<ul><li>very risky</li></ul></li></ul></li><li>Move to PostgreSQL</li></ol>" in body
    assert "<blockquote>Quoted guidance" in body
    assert '<pre class="code"><code>def f(x):\n    return x  *  2</code></pre>' in body
    assert body.count('<table class="grid"') == 1 and "<p>Option</p>" in body and 'class="a-right' in body
    figure = re.search(r"<figure.*?</figure>", body, re.DOTALL)
    assert figure and "<svg" in figure.group(0) and "<style" not in figure.group(0) and 'fill="#ececff"' in figure.group(0)
    assert 'aria-label="Diagram (flowchart)' in figure.group(0)
    assert "Diagram source (the diagram could not be drawn)" in body and "<code>broken</code>" in body
    assert "<script" not in body.lower()


def test_word_has_list_levels_a_bordered_quote_shaded_monospace_code_a_table_and_a_picture(document):
    word = Document(io.BytesIO(render_docx_document(document[0])))
    paragraphs = {p.text: p for p in word.paragraphs}

    assert [paragraphs[name].style.name for name in ("Keep the store", "cheap", "very risky", "Move to PostgreSQL")] == [
        "List Number", "List Bullet 2", "List Bullet 3", "List Number",
    ]
    quote = paragraphs["Quoted guidance\nfrom the board"]._p
    assert quote.find(f".//{qn('w:pBdr')}") is not None
    code = next(p for p in word.paragraphs if p.text.startswith("def f(x):"))
    assert "return x  *  2" in code.text and code.runs[0].font.name == "Courier New"
    assert code._p.find(f".//{qn('w:shd')}").get(qn("w:fill")) == "F3F3F3"
    assert len(word.tables) == 1 and [c.text for c in word.tables[0].rows[0].cells] == ["Option", "Cost"]
    assert len(word.inline_shapes) == 1
    assert any(p.text == "broken" for p in word.paragraphs)


def test_the_word_paragraph_properties_stay_in_the_order_the_schema_requires(document):
    word = Document(io.BytesIO(render_docx_document(document[0])))
    order = ["pStyle", "keepNext", "pBdr", "shd", "tabs", "spacing", "ind", "jc", "rPr"]

    for paragraph in word.paragraphs:
        properties = paragraph._p.find(qn("w:pPr"))
        if properties is None:
            continue
        seen = [etree_name(child) for child in properties if etree_name(child) in order]
        assert seen == sorted(seen, key=order.index), seen


def etree_name(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def test_opendocument_has_nested_lists_styled_quote_and_code_a_table_and_a_picture(document):
    archive = zipfile.ZipFile(io.BytesIO(render_odt_document(document[0])))
    content = archive.read("content.xml").decode()

    assert re.search(r"<text:list-item><text:p[^>]*>Keep the store</text:p><text:list [^>]*><text:list-item><text:p[^>]*>cheap</text:p>"
                     r"<text:list [^>]*><text:list-item><text:p[^>]*>very risky", content)
    assert 'text:style-name="Quote_20_Block">Quoted guidance<text:line-break/>from the board</text:p>' in content
    assert re.search(
        r'<text:p text:style-name="Code_20_Block">def f\(x\):<text:line-break/><text:s text:c="4"/>return x<text:s text:c="2"/>\*', content,
    )
    assert content.count("<table:table ") == 1 and content.count("<draw:image ") == 1
    styles = archive.read("styles.xml").decode()
    assert 'style:name="Code_20_Block"' in styles and 'style:name="Quote_20_Block"' in styles
    assert all(f'text:level="{level}"' in styles for level in (1, 2, 3, 4))


def test_pdf_is_built_from_a_nested_list_a_barred_quote_monospace_code_a_table_and_a_picture(document, monkeypatch):
    from reportlab.platypus import Image as RlImage
    from reportlab.platypus import ListFlowable
    from reportlab.platypus import Table as RlTable

    captured: list = []
    monkeypatch.setattr(report_pdf, "_build_pdf", lambda story, *args, **kwargs: captured.extend(story) or b"%PDF-")

    render_pdf_document(document[0])

    lists = [f for f in captured if isinstance(f, ListFlowable)]
    assert len(lists) == 1
    inner = [item for entry in lists[0]._flowables for item in getattr(entry, "_flowables", []) if isinstance(item, ListFlowable)]
    assert len(inner) == 1  # a list holds the list below it in the item that owns it
    quote = next(f for f in captured if isinstance(f, RlTable) and any(cmd[0] == "LINEBEFORE" for cmd in f._bkgrndcmds + f._linecmds))
    assert quote is not None
    assert any(isinstance(f, RlImage) for f in captured)  # the diagram, as a picture drawn at print resolution
    code_style = next(f.style for f in captured if hasattr(f, "style") and f.style.name == "report_code")
    assert code_style.fontName == "Report-mono-regular"  # the bundled monospace family
    assert len([f for f in captured if isinstance(f, RlTable)]) >= 2  # the quote's bar and the table


def test_pdf_renders_to_a_real_file_with_every_block(document):
    data = render_pdf_document(document[0])

    assert data.startswith(b"%PDF-") and len(data) > 20_000


def test_the_run_result_shows_the_new_blocks_as_text_lines(document):
    sections, lines = _sections_of_document(document[0].blocks)

    assert sections == [] and "• cheap" not in lines
    assert "1. Keep the store" in lines and "  • cheap" in lines and "    • very risky" in lines and "2. Move to PostgreSQL" in lines
    assert "> Quoted guidance\nfrom the board" in lines or any(line.startswith("> Quoted guidance") for line in lines)
    assert "def f(x):" in lines and "broken" in lines
    assert not any(isinstance(block, Table) for block in document[0].blocks)
