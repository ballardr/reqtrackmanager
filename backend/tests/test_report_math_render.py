"""Tests for equations in the PDF, Word and HTML renderers: the drawn forms, the fallbacks to source, hostile
text beside an equation, and the temporary files the PDF needs for inline equations. No database."""

from __future__ import annotations

import glob
import io
import re
import tempfile
import zipfile

import pytest
from lxml import etree

from app.services import report_math
from app.services.report_docx import render_docx_document
from app.services.report_html import CSP, render_html_document
from app.services.report_model import BulletList, Equation, Heading, MathText, Paragraph, ReportDocument, Table
from app.services.report_pdf import render_pdf_document

M = report_math.OMML_NS
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
BAD = r"\href{http://x}{y}"
UNSUPPORTED_BY_WORD = r"\hat{x}+\lim_{x\to 0}f"


def inline(tex: str) -> Equation:
    return Equation(tex, False)


def para(*parts) -> Paragraph:
    """A paragraph of text and inline equations."""
    return Paragraph(MathText(list(parts)))


def document(*blocks) -> ReportDocument:
    return ReportDocument("Math report", list(blocks))


def word_xml(doc: ReportDocument) -> etree._Element:
    with zipfile.ZipFile(io.BytesIO(render_docx_document(doc))) as archive:
        return etree.fromstring(archive.read("word/document.xml"))


def mark(tag: str) -> str:
    return f"{{{M}}}{tag}"


# --- HTML -------------------------------------------------------------------------------------------


def test_html_draws_a_display_equation_as_inline_svg_named_by_its_tex():
    page = render_html_document(document(Equation(r"\frac{a}{b} < 1"))).decode()

    assert '<figure class="equation" role="img" aria-label="\\frac{a}{b} &lt; 1"><svg' in page
    assert "<script" not in page and CSP in page


def test_html_sizes_an_inline_equation_in_em_and_sits_it_on_the_baseline():
    page = render_html_document(document(para("x is ", inline(r"\frac{a}{b}"), " ok"))).decode()
    match = re.search(
        r'<span class="math" role="img" aria-label="\\frac\{a\}\{b\}" style="vertical-align:-([\d.]+)em"><svg[^>]*width="([\d.]+)em"',
        page,
    )

    assert match and float(match.group(1)) > 0 and float(match.group(2)) > 0
    assert page.count("<p>x is <span") == 1 and "ok</p>" in page


def test_html_shows_the_source_of_an_equation_it_cannot_draw():
    page = render_html_document(document(
        para("see ", inline(BAD)), Equation(BAD), Equation(r"\frac{a}"),
    )).decode()

    assert page.count('<code class="math-source">') == 3
    assert r"\(\href{http://x}{y}\)" in page and "$$\\href{http://x}{y}$$" in page
    assert "<a " not in page and "<svg" not in page


def test_html_escapes_text_around_an_equation_and_the_tex_it_names():
    hostile = '<img src="file:///etc/passwd"> & <script>x</script>'
    page = render_html_document(document(para(hostile, inline("x")), Equation('"><script>x</script>'))).decode()

    assert "<script" not in page and "<img" not in page
    assert "&lt;img src=&quot;file:///etc/passwd&quot;&gt;" in page


# --- Word -------------------------------------------------------------------------------------------


def test_word_gets_a_native_display_equation():
    root = word_xml(document(Equation(r"\frac{a}{b}")))

    paragraphs = root.findall(f".//{mark('oMathPara')}")
    assert len(paragraphs) == 1 and paragraphs[0].find(f".//{mark('f')}") is not None
    assert root.find(f".//{{{W}}}drawing") is None


def test_word_puts_an_inline_equation_between_the_runs_of_its_paragraph():
    root = word_xml(document(para("before ", inline(r"x^2"), " after")))
    paragraph = next(p for p in root.iter(f"{{{W}}}p") if p.find(mark("oMath")) is not None)
    order = [etree.QName(child).localname for child in paragraph]

    assert order == ["r", "oMath", "r"]
    assert [t.text for t in paragraph.iter(f"{{{W}}}t")] == ["before ", " after"]


def test_word_falls_back_to_a_picture_for_an_equation_outside_the_tested_subset():
    root = word_xml(document(Equation(UNSUPPORTED_BY_WORD), para("a ", inline(r"\hat{x}"), " b")))

    assert len(root.findall(f".//{{{W}}}drawing")) == 2
    assert root.find(f".//{mark('oMath')}") is None


def test_word_lowers_an_inline_picture_by_its_descent():
    root = word_xml(document(para("a ", inline(r"\hat{\frac{x}{y}}"), " b")))
    positions = [int(p.get(f"{{{W}}}val")) for p in root.iter(f"{{{W}}}position")]

    assert positions and all(p < 0 for p in positions)


def test_word_prints_the_source_of_an_equation_it_cannot_draw():
    root = word_xml(document(Equation(BAD), para("see ", inline(BAD))))
    text = "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))

    assert "$$\\href{http://x}{y}$$" in text and "see \\(\\href{http://x}{y}\\)" in text
    assert root.find(f".//{mark('oMath')}") is None and root.find(f".//{{{W}}}drawing") is None


def test_word_stores_hostile_text_beside_an_equation_as_text_only():
    hostile = '<w:p><w:r>x</w:r></w:p> \x00 <m:oMath/>'
    root = word_xml(document(para(hostile, inline("x"))))

    assert len(root.findall(f".//{mark('oMath')}")) == 1  # only the real one
    assert "<w:p><w:r>x</w:r></w:p>" in "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))


def test_every_word_equation_element_is_in_the_tested_subset():
    root = word_xml(document(
        Equation(r"\sum_{i=1}^n \frac{\sqrt{x_i}}{2}"), Equation(r"\begin{pmatrix}a&b\\c&d\end{pmatrix}"),
        para(inline(r"\text{if } x \geq 0")),
    ))
    names = {etree.QName(e).localname for e in root.iter() if etree.QName(e).namespace == M}

    assert names - {"oMathPara"} <= report_math.OMML_ELEMENTS


# --- PDF --------------------------------------------------------------------------------------------


def leftovers() -> set[str]:
    return set(glob.glob(f"{tempfile.gettempdir()}/report-math-*"))


def test_pdf_renders_every_form_of_equation():
    before = leftovers()
    pdf = render_pdf_document(document(
        Heading("Math", 1),
        para("a ", inline(r"\frac{a}{b}"), " b ", inline(r"\hat{x}"), " c ", inline(BAD)),
        Equation(r"\sum_{i=1}^n i"), Equation(UNSUPPORTED_BY_WORD), Equation(BAD), Paragraph("after"),
    ))

    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
    assert leftovers() == before


def test_pdf_leaves_no_temporary_files_even_when_the_build_fails(monkeypatch):
    before = leftovers()

    def broken(*args, **kwargs):
        raise RuntimeError("build failed")

    monkeypatch.setattr("app.services.report_pdf.build_pdf", broken)
    with pytest.raises(RuntimeError):
        render_pdf_document(document(para("a ", inline("x"))))

    assert leftovers() == before


def test_pdf_with_hostile_text_beside_an_inline_equation_does_not_fetch_or_fail():
    hostile = '<img src="file:///etc/passwd"/> <font>&'

    assert render_pdf_document(document(para(hostile, inline("x")))).startswith(b"%PDF")


def test_a_pdf_with_only_ordinary_text_creates_no_temporary_directory():
    before = leftovers()
    render_pdf_document(document(Paragraph("plain"), Equation("x")))  # display only: vector, no inline PNG

    assert leftovers() == before


# --- headings, list items and table cells ---------------------------------------------------------


def rich(*parts) -> MathText:
    return MathText(list(parts))


def everywhere() -> ReportDocument:
    """Equations in a heading, a list item and a table cell, beside plain ones."""
    return document(
        Heading(rich("Load ", inline(r"\frac{F}{A}")), 2),
        BulletList([rich("item ", inline(r"x^2")), "plain item"]),
        Table(["Field", "Value"], [["a", rich("v = ", inline(r"\sqrt{x}"))], ["b", "plain"]], compact=True),
    )


def test_html_draws_equations_in_headings_list_items_and_cells():
    page = render_html_document(everywhere()).decode()

    assert re.search(r"<h3>Load <span class=\"math\".*?</span></h3>", page)
    assert re.search(r"<li>item <span class=\"math\"", page) and "<li>plain item</li>" in page
    assert re.search(r"<td>v = <span class=\"math\"", page) and "<td>plain</td>" in page


def test_word_puts_native_equations_in_headings_list_items_and_cells():
    root = word_xml(everywhere())
    paragraphs = [p for p in root.iter(f"{{{W}}}p") if p.find(mark("oMath")) is not None]
    styles = []
    for p in paragraphs:
        style = p.find(f"{{{W}}}pPr/{{{W}}}pStyle")
        styles.append(style.get(f"{{{W}}}val") if style is not None else None)

    assert len(paragraphs) == 3
    assert "Heading2" in styles and "ListBullet" in styles and styles.count(None) == 1  # the cell's paragraph
    assert "Load " in "".join(t.text or "" for t in paragraphs[0].iter(f"{{{W}}}t"))


def test_word_cell_text_keeps_its_size_beside_an_equation():
    root = word_xml(everywhere())
    cell = next(c for c in root.iter(f"{{{W}}}tc") if c.find(f".//{mark('oMath')}") is not None)

    assert cell.find(f".//{{{W}}}r/{{{W}}}rPr/{{{W}}}sz") is not None


def test_pdf_renders_equations_in_headings_list_items_and_cells_and_cleans_up():
    before = leftovers()

    assert render_pdf_document(everywhere()).startswith(b"%PDF")
    assert leftovers() == before


def test_a_toned_cell_with_an_equation_renders_in_pdf_and_word():
    table = Table(["Rating"], [[rich("r ", inline("x"))]], compact=True, tones=[["danger"]])
    doc = document(table)

    assert render_pdf_document(doc).startswith(b"%PDF")
    assert word_xml(doc).find(f".//{mark('oMath')}") is not None


def test_text_only_consumers_see_the_source_of_an_equation_unchanged():
    value = rich("see ", inline("x^2"), " and ", Equation("y", True))

    assert value == r"see \(x^2\) and $$y$$" and isinstance(value, str)
    assert value.parts[1] == inline("x^2")
