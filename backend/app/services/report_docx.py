"""
Module: services.report_docx

Renders a neutral `ReportDocument` (`services.report_model`) to an editable
Word (DOCX) file with python-docx. It is the DOCX counterpart of `report_pdf`:
the same blocks, so the two formats show the same content.

Editable by design: headings use Word's real Heading styles (so a table of
contents can be inserted), tables are real tables with a repeating, accent
shaded header row, and the footer carries a live page-number field. Nothing is
rendered as an image of text or of a table.

Security decisions:
- Every user string passes through `clean_text` first. python-docx (lxml)
  raises on characters that are invalid in XML 1.0 (control characters), which
  would otherwise let any author's text turn a download into a 500.
- Text is only ever set as run or cell text, never as markup, so a `<script>`
  or `<w:...>` string is stored as literal text.
- No hyperlink, field-code or macro path takes user text. The only field is the
  fixed `PAGE` number in the footer, and the model carries no links.
- The accent colour reaches an XML attribute, so it is checked against a hex
  pattern and falls back to the default.
- Equations are Word's own (editable) equation objects when `report_math.omml` has a tested translation, built
  from the converter's markup after its element allow-list; otherwise a PNG of the same drawing, and if even that
  fails the TeX as the author wrote it. No equation text reaches the XML except as `m:t` text the converter escaped.
- Images are the pre-resolved, tenant-checked bytes in the model; an image
  python-docx cannot decode is skipped.
- Core properties carry the title, a fixed author and the creation time only,
  never a person's name or email.

Dependencies: python-docx, `services.report_model`, `services.report_document`
(branding type), `services.branding` (default accent), `services.report_math` (equations).
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from datetime import UTC, datetime

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor
from docx.text.run import Run

from app.services.branding import DEFAULT_ACCENT_COLOR_HEX, readable_on_white
from app.services.report_math import OMML_NS, omml, png_of, typeset
from app.services.report_model import (
    TONE_FILL,
    BulletList,
    Equation,
    Gap,
    Heading,
    Image,
    Note,
    PageBreak,
    Paragraph,
    ReportDocument,
    Table,
    text_on,
    text_runs,
)
from app.services.report_svg import svg_png

DOCX_AUTHOR = "ReqTrackManager"
_PAGE_WIDTH_CM, _PAGE_HEIGHT_CM = 21.0, 29.7  # A4
_MARGIN_CM = 1.5
_XML_INVALID = re.compile("[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]")
_HEX_COLOUR = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_ZEBRA = "F5F5F5"
_NOTE_GREY = RGBColor(0x55, 0x55, 0x55)


def clean_text(text: str) -> str:
    """Removes characters that are not valid in XML 1.0 (control characters,
    lone surrogates), which python-docx refuses to write.

    Args:
        text: Untrusted text.

    Returns:
        The text with every XML-invalid character dropped.
    """
    return _XML_INVALID.sub("", text)


def _hex(colour: str | None) -> str:
    """The six hex digits of `colour`, or the default accent when it is not a
    plain `#RRGGBB` value (the value ends up in an XML attribute)."""
    match = _HEX_COLOUR.match(colour or "")
    return (match or _HEX_COLOUR.match(DEFAULT_ACCENT_COLOR_HEX)).group(1).upper()  # type: ignore[union-attr]


def _shade(cell, fill: str) -> None:
    """Sets a table cell's background colour (`fill` is six hex digits)."""
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def _repeat_header(row) -> None:
    """Marks `row` as the header row repeated on every page."""
    row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))


def _page_number_field(paragraph) -> None:
    """Appends a live `PAGE` field (the fixed field code, no user text)."""
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


def _configure_page(doc: DocxDocument, document: ReportDocument) -> float:
    """Sets A4 size, orientation and margins; returns the usable width in cm."""
    section = doc.sections[0]
    width, height = (_PAGE_HEIGHT_CM, _PAGE_WIDTH_CM) if document.landscape else (_PAGE_WIDTH_CM, _PAGE_HEIGHT_CM)
    section.orientation = WD_ORIENT.LANDSCAPE if document.landscape else WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Cm(width), Cm(height)
    section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = Cm(_MARGIN_CM)
    return width - 2 * _MARGIN_CM


def _footer(doc: DocxDocument, document: ReportDocument) -> None:
    """The footer: optional branding text, then the page number. A cover page
    is left without one."""
    section = doc.sections[0]
    branding = document.branding
    section.different_first_page_header_footer = bool(branding and branding.include_cover_page)
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if branding and branding.footer_text:
        paragraph.add_run(clean_text(branding.footer_text) + "  ·  Page ")
    else:
        paragraph.add_run("Page ")
    _page_number_field(paragraph)


def _svg_png(svg: str) -> bytes:
    """A PNG of an SVG figure (Word cannot embed SVG), or empty bytes when it cannot be drawn, which `_picture` skips."""
    try:
        return svg_png(svg)
    except Exception:  # noqa: BLE001 - a figure that cannot be drawn must never break report generation
        return b""


def _picture(doc: DocxDocument, data: bytes, max_width_cm: float, *, fixed_width_cm: float | None = None) -> bool:
    """Adds an image, shrunk to the usable width. Returns `False` (nothing
    added) when the bytes are not an image python-docx can read."""
    try:
        paragraph = doc.add_paragraph()
        run = paragraph.add_run()
        shape = run.add_picture(io.BytesIO(data), width=Cm(fixed_width_cm) if fixed_width_cm else None)
    except Exception:  # noqa: BLE001 - a malformed or unsupported image must never break report generation
        parent = paragraph._p.getparent()
        if parent is not None:
            parent.remove(paragraph._p)
        return False
    limit = Cm(max_width_cm)
    if shape.width > limit:
        shape.height = Emu(int(shape.height * limit / shape.width))
        shape.width = Emu(int(limit))
    return True


_POINTS_PER_CM = 28.3465


def _inline_equation(paragraph, equation: Equation) -> None:
    """Appends an inline equation to `paragraph`: a Word equation, else a picture on the baseline, else its source."""
    native = omml(equation.tex)
    if native:
        paragraph._p.append(parse_xml(native))
        return
    drawn = typeset(equation.tex, False)
    png = png_of(drawn) if drawn is not None else None
    if drawn is None or png is None:
        paragraph.add_run(clean_text(equation.text))
        return
    run = paragraph.add_run()
    try:
        run.add_picture(io.BytesIO(png), width=Pt(drawn.width), height=Pt(drawn.height))
    except Exception:  # noqa: BLE001 - a picture python-docx cannot read must never break report generation
        paragraph._p.remove(run._r)
        paragraph.add_run(clean_text(equation.text))
        return
    if drawn.descent:
        offset = OxmlElement("w:position")
        offset.set(qn("w:val"), str(-round(drawn.descent * 2)))  # half-points below the baseline
        run._r.get_or_add_rPr().append(offset)


def _add_text(paragraph, value: str, style: Callable[[Run], None] | None = None) -> list[Run]:
    """Appends model text to `paragraph`: a run per plain piece (given `style`), a Word equation or picture per
    inline equation. Returns the plain runs."""
    runs = []
    for part in text_runs(value):
        if isinstance(part, str):
            run = paragraph.add_run(clean_text(part))
            if style is not None:
                style(run)
            runs.append(run)
        else:
            _inline_equation(paragraph, part)
    return runs


def _display_equation(doc: DocxDocument, equation: Equation, usable_cm: float) -> None:
    """Adds a display equation: a centred Word equation, else a centred picture, else its source."""
    native = omml(equation.tex)
    if native:
        doc.add_paragraph()._p.append(parse_xml(f'<m:oMathPara xmlns:m="{OMML_NS}">{native}</m:oMathPara>'))
        return
    drawn = typeset(equation.tex, True)
    png = png_of(drawn) if drawn is not None else None
    if drawn is not None and png is not None and _picture(doc, png, usable_cm, fixed_width_cm=drawn.width / _POINTS_PER_CM):
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        return
    doc.add_paragraph(clean_text(equation.text))


def _cover(doc: DocxDocument, document: ReportDocument, accent: str, usable_cm: float) -> None:
    """The opening block: a branded cover page (logo, accent title, page
    break) when branding asks for one, otherwise a plain title line."""
    title = clean_text(document.title)
    branding = document.branding
    if branding and branding.include_cover_page:
        spacer = doc.add_paragraph()
        spacer.paragraph_format.space_before = Cm(5)
        if branding.logo_bytes:
            _picture(doc, branding.logo_bytes, usable_cm, fixed_width_cm=4)
        paragraph = doc.add_paragraph(style="Title")
        run = paragraph.add_run(title)
        run.font.size = Pt(28)
        run.font.color.rgb = RGBColor.from_string(_hex(readable_on_white(accent)))  # text on a white page
        doc.add_page_break()
    else:
        doc.add_paragraph(title, style="Title")


def _table(doc: DocxDocument, block: Table, accent: str, usable_cm: float) -> None:
    """A real Word table: shaded, repeating header row, optional zebra rows."""
    if not block.columns:
        return
    count = len(block.columns)
    widths = block.col_widths_cm or [1.0] * count
    scale = usable_cm / sum(widths)
    table = doc.add_table(rows=1, cols=count, style="Table Grid")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for column, width in zip(table.columns, widths, strict=False):
        column.width = Cm(width * scale)  # the grid widths; Word and LibreOffice read these, not only the cells'
    font_size = Pt(7.5 if block.compact else 8)

    def fill(cells, values, *, header: bool = False, shade: str | None = None, row_index: int = 0) -> None:
        for column, (cell, value, width) in enumerate(zip(cells, values, widths, strict=False)):
            cell.width = Cm(width * scale)
            tone = None if header else block.tone_at(row_index, column)

            def style(run: Run, header: bool = header, tone: str | None = tone) -> None:
                run.font.size = font_size
                if header:
                    run.font.bold = True
                    run.font.color.rgb = RGBColor.from_string(text_on(accent))  # white or black, whichever the accent needs
                elif tone:
                    # A tone overrides the zebra stripe; the text colour is chosen by contrast with the tint.
                    run.font.color.rgb = RGBColor.from_string(text_on(TONE_FILL[tone]))

            if not _add_text(cell.paragraphs[0], value, style):
                style(cell.paragraphs[0].add_run(""))  # an all-equation cell still gets its size
            if header:
                _shade(cell, accent)
            elif tone:
                _shade(cell, TONE_FILL[tone])
            elif shade:
                _shade(cell, shade)

    fill(table.rows[0].cells, block.columns, header=True)
    _repeat_header(table.rows[0])
    for index, row in enumerate(block.rows):
        cells = table.add_row().cells
        fill(cells, (row + [""] * count)[:count], shade=_ZEBRA if block.compact and index % 2 else None, row_index=index)
    doc.add_paragraph()  # keeps two consecutive tables from merging in Word


def render_docx_document(document: ReportDocument) -> bytes:
    """Renders `document` as a DOCX file.

    Args:
        document: The neutral report.

    Returns:
        DOCX bytes.
    """
    doc = Document()
    usable_cm = _configure_page(doc, document)
    accent = _hex(document.branding.accent_color_hex if document.branding else None)

    properties = doc.core_properties
    properties.title = clean_text(document.title)
    properties.author = properties.last_modified_by = DOCX_AUTHOR
    properties.comments = properties.subject = properties.keywords = properties.category = ""
    properties.created = properties.modified = datetime.now(UTC).replace(tzinfo=None)

    _footer(doc, document)
    _cover(doc, document, accent, usable_cm)

    for block in document.blocks:
        if isinstance(block, Heading):
            _add_text(doc.add_heading("", level=min(max(block.level, 1), 4)), block.text)
        elif isinstance(block, Paragraph):
            _add_text(doc.add_paragraph(), block.text)
        elif isinstance(block, Equation):
            _display_equation(doc, block, usable_cm)
        elif isinstance(block, Note):
            run = doc.add_paragraph().add_run(clean_text(block.text))
            run.italic = True
            run.font.size = Pt(8.5)
            run.font.color.rgb = _NOTE_GREY
        elif isinstance(block, BulletList):
            for item in block.items:
                _add_text(doc.add_paragraph(style="List Bullet"), item)
        elif isinstance(block, Image):
            _picture(doc, _svg_png(block.svg) if block.svg is not None else block.data, usable_cm)
        elif isinstance(block, Table):
            _table(doc, block, accent, usable_cm)
        elif isinstance(block, PageBreak):
            doc.add_page_break()
        elif isinstance(block, Gap):
            continue  # a PDF layout hint; Word styles carry paragraph spacing

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
