"""
Module: services.report_odt

Renders a neutral `ReportDocument` (`services.report_model`) to an editable OpenDocument Text (ODT) file: the
ODT counterpart of `report_docx` and `report_pdf`, showing the same blocks.

Editable by design: headings are real heading paragraphs with outline levels (so a table of contents can be
inserted), tables are real tables with a repeating, accent-shaded header row, lists are real lists, and the footer
carries a live page-number field. Nothing is an image of text or of a table.

Design decisions:
- **Written as XML text** (`report_odf`), not through an object library: a report of many thousands of table rows
  stays proportional to the size of the file instead of costing about 10 KB of objects per row.
- **Every string passes `report_odf.xml_text` or `xml_attr`**, so record text is only ever element content: a
  `<script>`, `<text:...>` or `<draw:...>` string is stored as literal text. Colours are checked as six hex digits,
  lengths are formatted from numbers, and an image's type is sniffed from its bytes. A link is written only for an address
  `report_model.finalize_links` has checked, as an attribute value; there is no macro, field code or external object, and
  the one field is the fixed page number.
- **Equations are pictures** (the same drawing the PDF embeds, with a baseline offset inline), then the author's
  source when one cannot be drawn. They are not native formula objects: those need an embedded sub-document in
  StarMath/MathML whose rendering differs between office suites, so a picture is the faithful form (`docs/decisions.md`,
  "ODT and ODS renderers").
- Branding, cover page, orientation, tone fills and header text contrast follow `report_docx` and use the same
  helpers (`text_on`, `readable_on_white`, `TONE_FILL`), so formats cannot drift.

Dependencies: `services.report_odf` (package, escaping), `services.report_model`, `services.report_math`,
`services.report_svg`, `services.branding`.
"""

from __future__ import annotations

from app.services.branding import readable_on_white
from app.services.report_math import png_of, typeset
from app.services.report_model import (
    TONE_FILL,
    BulletList,
    Equation,
    Gap,
    Heading,
    Image,
    Note,
    NumberedList,
    PageBreak,
    Paragraph,
    ReportDocument,
    Styled,
    Table,
    finalize_links,
    page_dimensions_cm,
    text_on,
    text_runs,
)
from app.services.report_odf import (
    FONT_FACES,
    MIME_ODT,
    ODF_VERSION,
    XML_DECLARATION,
    OdfPackage,
    colour,
    length_cm,
    namespace_attrs,
    raster_info,
    xml_attr,
    xml_text,
)
from app.services.report_svg import svg_png

_MARGIN_CM = 1.5
_POINTS_PER_CM = 28.3465
_PIXELS_PER_CM = 96 / 2.54
_ZEBRA = "#F5F5F5"
_NOTE_GREY = "#555555"
_ALL_NS = ("office", "style", "text", "table", "draw", "fo", "xlink", "svg", "dc", "meta")


def _frame_style_xml() -> str:
    return (
        '<style:style style:name="fr_block" style:family="graphic"><style:graphic-properties text:anchor-type="as-char" '
        'style:vertical-pos="top" style:vertical-rel="baseline" style:wrap="none" fo:margin-left="0cm" fo:margin-right="0cm" '
        'fo:margin-top="0cm" fo:margin-bottom="0cm" fo:padding="0cm" fo:border="none"/></style:style>'
        '<style:style style:name="fr_inline" style:family="graphic"><style:graphic-properties text:anchor-type="as-char" '
        'style:vertical-pos="from-top" style:vertical-rel="baseline" style:wrap="none" fo:margin-left="0cm" '
        'fo:margin-right="0cm" fo:margin-top="0cm" fo:margin-bottom="0cm" fo:padding="0cm" fo:border="none"/></style:style>'
    )


def _paragraph_style(name: str, *, parent: str | None = "Standard", para: str = "", text: str = "", extra: str = "") -> str:
    """One paragraph style (`para` and `text` are attribute text for the two property elements)."""
    parent_attr = f' style:parent-style-name="{parent}"' if parent else ""
    paragraph = f"<style:paragraph-properties {para}/>" if para else ""
    run = f"<style:text-properties {text}/>" if text else ""
    return f'<style:style style:name="{name}" style:family="paragraph"{parent_attr}{extra}>{paragraph}{run}</style:style>'


#: The character styles of bold / italic / code runs, by name, as `style:text-properties` attributes.
_SPAN_STYLES: dict[str, str] = {
    "T_Bold": 'fo:font-weight="bold"',
    "T_Italic": 'fo:font-style="italic"',
    "T_BoldItalic": 'fo:font-weight="bold" fo:font-style="italic"',
    "T_Code": 'fo:font-family="\'Courier New\'" style:font-family-generic="modern"',
    "T_BoldCode": 'fo:font-weight="bold" fo:font-family="\'Courier New\'" style:font-family-generic="modern"',
    "T_ItalicCode": 'fo:font-style="italic" fo:font-family="\'Courier New\'" style:font-family-generic="modern"',
    "Internet_20_link": (
        'fo:color="#0563c1" style:text-underline-style="solid" style:text-underline-width="auto" style:text-underline-color="font-color"'
    ),
    "T_BoldItalicCode": 'fo:font-weight="bold" fo:font-style="italic" fo:font-family="\'Courier New\'" style:font-family-generic="modern"',
}


def _text_style(name: str, properties: str) -> str:
    """One character style (the style of a `text:span`)."""
    return f'<style:style style:name="{name}" style:family="text"><style:text-properties {properties}/></style:style>'


def _span_style(run: Styled) -> str:
    """The name of the character style for a run's combination of bold, italic and code."""
    return "T_" + ("Bold" if run.bold else "") + ("Italic" if run.italic else "") + ("Code" if run.code else "")


def _named_styles() -> str:
    """The `office:styles` content that does not depend on the document: default text, headings, notes, the list."""
    sizes = {1: 16, 2: 14, 3: 12, 4: 11}
    headings = "".join(
        _paragraph_style(
            f"Heading_20_{level}", parent="Heading", extra=f' style:display-name="Heading {level}" style:default-outline-level="{level}"',
            text=f'fo:font-size="{size}pt" fo:font-weight="bold"',
        )
        for level, size in sizes.items()
    )
    return (
        '<style:default-style style:family="paragraph"><style:paragraph-properties fo:orphans="2" fo:widows="2"/>'
        '<style:text-properties style:font-name="Arial" fo:font-size="10pt"/></style:default-style>'
        + _paragraph_style("Standard", parent=None, extra=' style:class="text"', para='fo:margin-bottom="0.15cm"')
        + _paragraph_style(
            "Title", extra=' style:next-style-name="Standard"', para='fo:margin-top="0.2cm" fo:margin-bottom="0.4cm"',
            text='fo:font-size="20pt" fo:font-weight="bold"',
        )
        + _paragraph_style(
            "Heading", extra=' style:next-style-name="Standard" style:class="text"',
            para='fo:margin-top="0.4cm" fo:margin-bottom="0.2cm" fo:keep-with-next="always"', text='fo:font-weight="bold"',
        )
        + headings
        + _paragraph_style("Note", text=f'fo:font-size="8.5pt" fo:font-style="italic" fo:color="{_NOTE_GREY}"')
        + _paragraph_style("Footer", para='fo:text-align="center" fo:margin-bottom="0cm"', text='fo:font-size="8pt"')
        + _paragraph_style("List_20_Bullet", extra=' style:display-name="List Bullet"', para='fo:margin-bottom="0.05cm"')
        + _paragraph_style("List_20_Number", extra=' style:display-name="List Number"', para='fo:margin-bottom="0.05cm"')
        + _paragraph_style("Display_20_Equation", para='fo:text-align="center"')
        + "".join(_text_style(name, props) for name, props in _SPAN_STYLES.items())
        + '<text:list-style style:name="L_Number"><text:list-level-style-number text:level="1" style:num-suffix="." style:num-format="1">'
        '<style:list-level-properties text:list-level-position-and-space-mode="label-alignment">'
        '<style:list-level-label-alignment text:label-followed-by="listtab" text:list-tab-stop-position="0.9cm" '
        'fo:text-indent="-0.6cm" fo:margin-left="0.9cm"/></style:list-level-properties></text:list-level-style-number></text:list-style>'
        + '<text:list-style style:name="L_Bullet"><text:list-level-style-bullet text:level="1" text:bullet-char="•">'
        '<style:list-level-properties text:list-level-position-and-space-mode="label-alignment">'
        '<style:list-level-label-alignment text:label-followed-by="listtab" text:list-tab-stop-position="0.9cm" '
        'fo:text-indent="-0.5cm" fo:margin-left="0.9cm"/></style:list-level-properties></text:list-level-style-bullet></text:list-style>'
    )


def _styles_xml(document: ReportDocument) -> str:
    """`styles.xml`: fonts, named styles, the page layout (size, orientation, margins) and the master pages."""
    width, height = page_dimensions_cm(document)
    orientation = "landscape" if document.landscape else "portrait"
    branding = document.branding
    footer = f"{xml_text(branding.footer_text)}  ·  Page " if branding and branding.footer_text else "Page "
    return (
        f'{XML_DECLARATION}<office:document-styles {namespace_attrs(*_ALL_NS)} office:version="{ODF_VERSION}">'
        f"{FONT_FACES}"
        f"<office:styles>{_named_styles()}</office:styles>"
        '<office:automatic-styles><style:page-layout style:name="PL">'
        f'<style:page-layout-properties fo:page-width="{length_cm(width)}" fo:page-height="{length_cm(height)}" '
        f'style:print-orientation="{orientation}" fo:margin-top="{length_cm(_MARGIN_CM)}" fo:margin-bottom="{length_cm(_MARGIN_CM)}" '
        f'fo:margin-left="{length_cm(_MARGIN_CM)}" fo:margin-right="{length_cm(_MARGIN_CM)}"/>'
        '<style:footer-style><style:header-footer-properties fo:min-height="0.5cm" fo:margin-top="0.3cm"/></style:footer-style>'
        "</style:page-layout></office:automatic-styles>"
        '<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="PL">'
        f'<style:footer><text:p text:style-name="Footer">{footer}'
        '<text:page-number text:select-page="current">1</text:page-number></text:p></style:footer>'
        '</style:master-page><style:master-page style:name="Cover" style:page-layout-name="PL"/></office:master-styles>'
        "</office:document-styles>"
    )


class _Body:
    """Builds `content.xml` for one document: body chunks, the automatic styles they need, and the pictures."""

    def __init__(self, document: ReportDocument, package: OdfPackage, usable_cm: float) -> None:
        self.document = document
        self.package = package
        self.usable_cm = usable_cm
        branding = document.branding
        self.accent = colour(branding.accent_color_hex if branding else None)
        self.chunks: list[str] = []
        self.styles: list[str] = []
        self._frames = 0
        self._tables = 0
        self._static_styles()

    # --- styles ---------------------------------------------------------------------------------------------

    def _static_styles(self) -> None:
        """The automatic styles every document carries: frames, the page break, and the table cell and text styles."""
        self.styles.append(_frame_style_xml())
        self.styles.append(_paragraph_style("P_Break", para='fo:break-after="page" fo:margin-bottom="0cm"'))
        self.styles.append(_paragraph_style("P_AfterCover", extra=' style:master-page-name="Standard"', para='fo:margin-bottom="0cm"'))
        header_text = f"#{text_on(self.accent.lstrip('#'))}"
        border = 'fo:border="0.5pt solid #999999" fo:padding="0.08cm"'

        def cell(name: str, fill: str | None) -> str:
            background = f' fo:background-color="{fill}"' if fill else ""
            return f'<style:style style:name="{name}" style:family="table-cell"><style:table-cell-properties {border}{background}/></style:style>'

        self.styles.append(cell("C_hdr", self.accent))
        self.styles.append(cell("C_body", None))
        self.styles.append(cell("C_zebra", _ZEBRA))
        for tone, fill in TONE_FILL.items():
            self.styles.append(cell(f"C_{tone}", f"#{fill}"))
        for suffix, size in (("", 8), ("_c", 7.5)):
            para = 'fo:margin-top="0cm" fo:margin-bottom="0cm"'
            self.styles.append(_paragraph_style(f"P_cell{suffix}", para=para, text=f'fo:font-size="{size}pt"'))
            bold = f'fo:font-size="{size}pt" fo:font-weight="bold" fo:color="{header_text}"'
            self.styles.append(_paragraph_style(f"P_hdr{suffix}", para=para, text=bold))
            for tone, fill in TONE_FILL.items():
                self.styles.append(_paragraph_style(f"P_{tone}{suffix}", para=para, text=f'fo:font-size="{size}pt" fo:color="#{text_on(fill)}"'))

    # --- pictures --------------------------------------------------------------------------------------------

    def _frame(self, data: bytes, width_cm: float, height_cm: float, *, inline_offset_cm: float | None = None, alt: str = "") -> str:
        """A `draw:frame` anchored in the text holding the picture `data`, or `""` when `data` is not a supported raster."""
        info = raster_info(data)
        if info is None:
            return ""
        media_type, extension, _, _ = info
        path = self.package.add_picture(data, media_type, extension)
        self._frames += 1
        style = "fr_block" if inline_offset_cm is None else "fr_inline"
        offset = "" if inline_offset_cm is None else f' svg:y="{length_cm(inline_offset_cm)}"'
        title = f"<svg:title>{xml_text(alt)}</svg:title>" if alt else ""
        return (
            f'<draw:frame draw:style-name="{style}" draw:name="Picture{self._frames}" text:anchor-type="as-char"{offset} '
            f'svg:width="{length_cm(width_cm)}" svg:height="{length_cm(height_cm)}">'
            f'<draw:image xlink:href="{path}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>{title}</draw:frame>'
        )

    def _picture(self, data: bytes, *, fixed_width_cm: float | None = None, alt: str = "") -> str:
        """A picture, shrunk to the usable width (or `fixed_width_cm` wide); `""` when `data` cannot be embedded."""
        info = raster_info(data)
        if info is None:
            return ""
        _, _, width_px, height_px = info
        width = fixed_width_cm if fixed_width_cm else width_px / _PIXELS_PER_CM
        height = width * height_px / width_px
        if width > self.usable_cm:
            width, height = self.usable_cm, self.usable_cm * height_px / width_px
        return self._frame(data, width, height, alt=alt)

    def _equation_frame(self, equation: Equation) -> str:
        """The picture of an equation (on the baseline when inline), or `""` when it cannot be drawn."""
        drawn = typeset(equation.tex, equation.display)
        png = png_of(drawn) if drawn is not None else None
        if drawn is None or png is None:
            return ""
        width, height = drawn.width / _POINTS_PER_CM, drawn.height / _POINTS_PER_CM
        offset = None if equation.display else (drawn.descent - drawn.height) / _POINTS_PER_CM
        return self._frame(png, width, height, inline_offset_cm=offset, alt=equation.tex)

    # --- text ------------------------------------------------------------------------------------------------

    def _inline(self, value: str) -> str:
        """Paragraph content for model text: escaped text, a character-styled span per bold / italic / code run, and a
        picture (else the source) per inline equation."""
        return "".join(
            xml_text(part) if isinstance(part, str)
            else self._styled(part) if isinstance(part, Styled)
            else (self._equation_frame(part) or xml_text(part.text))
            for part in text_runs(value)
        )

    def _styled(self, run: Styled) -> str:
        """A bold / italic / code / link run: a character-styled span, inside a link when it has one (an address was
        checked by `finalize_links`; it is an attribute value, escaped, never markup)."""
        inner = xml_text(run.text)
        if run.bold or run.italic or run.code:
            inner = f'<text:span text:style-name="{_span_style(run)}">{inner}</text:span>'
        if run.href:
            inner = f'<text:a xlink:type="simple" xlink:href={xml_attr(run.href)} text:style-name="Internet_20_link">{inner}</text:a>'
        return inner

    def _paragraph(self, style: str, content: str) -> None:
        self.chunks.append(f'<text:p text:style-name="{style}">{content}</text:p>')

    # --- blocks ----------------------------------------------------------------------------------------------

    def cover(self) -> None:
        """The opening block: a branded cover page (logo, accent title, then the page the body starts on) or a title line."""
        title = self.document.title
        branding = self.document.branding
        if branding and branding.include_cover_page:
            title_colour = colour(readable_on_white(self.accent))
            self.styles.append(_paragraph_style("P_CoverStart", extra=' style:master-page-name="Cover"', para='fo:margin-top="5cm"'))
            self.styles.append(_paragraph_style("P_CoverTitle", parent="Title", text=f'fo:font-size="28pt" fo:color="{title_colour}"'))
            logo = self._picture(branding.logo_bytes, fixed_width_cm=4) if branding.logo_bytes else ""
            self._paragraph("P_CoverStart", logo)
            self._paragraph("P_CoverTitle", xml_text(title))
            self.chunks.append('<text:p text:style-name="P_AfterCover"/>')
        else:
            self._paragraph("Title", xml_text(title))

    def table(self, block: Table) -> None:
        """A real table: shaded, repeating header row, optional zebra rows and tones."""
        if not block.columns:
            return
        self._tables += 1
        name = f"Tbl{self._tables}"
        count = len(block.columns)
        widths = block.col_widths_cm or [1.0] * count
        scale = self.usable_cm / sum(widths)
        suffix = "_c" if block.compact else ""
        self.styles.append(
            f'<style:style style:name="{name}" style:family="table"><style:table-properties style:width="{length_cm(self.usable_cm)}" '
            'table:align="margins" fo:margin-bottom="0.2cm"/></style:style>'
        )
        columns = []
        for index, width in enumerate(widths[:count]):
            self.styles.append(
                f'<style:style style:name="{name}_{index}" style:family="table-column">'
                f'<style:table-column-properties style:column-width="{length_cm(width * scale)}"/></style:style>'
            )
            columns.append(f'<table:table-column table:style-name="{name}_{index}"/>')

        def row(values: list[str], cell_style, paragraph_style) -> str:
            cells = []
            for column, value in enumerate(values):
                cells.append(
                    f'<table:table-cell table:style-name="{cell_style(column)}"><text:p text:style-name="{paragraph_style(column)}">'
                    f"{self._inline(value)}</text:p></table:table-cell>"
                )
            return f"<table:table-row>{''.join(cells)}</table:table-row>"

        self.chunks.append(f'<table:table table:name="{name}" table:style-name="{name}">{"".join(columns)}')
        self.chunks.append(
            "<table:table-header-rows>" + row(block.columns, lambda c: "C_hdr", lambda c: f"P_hdr{suffix}") + "</table:table-header-rows>"
        )
        for index, values in enumerate(block.rows):
            padded = (values + [""] * count)[:count]
            zebra = "C_zebra" if block.compact and index % 2 else "C_body"

            def cell_style(column: int, index: int = index, zebra: str = zebra) -> str:
                tone = block.tone_at(index, column)
                return f"C_{tone}" if tone else zebra

            def paragraph_style(column: int, index: int = index) -> str:
                tone = block.tone_at(index, column)
                return f"P_{tone}{suffix}" if tone else f"P_cell{suffix}"

            self.chunks.append(row(padded, cell_style, paragraph_style))
        self.chunks.append("</table:table>")
        self.chunks.append('<text:p text:style-name="Standard"/>')  # keeps two consecutive tables from merging

    def block(self, block) -> None:
        """Adds one neutral block."""
        if isinstance(block, Heading):
            level = min(max(block.level, 1), 4)
            mark = f"<text:bookmark text:name={xml_attr(block.anchor)}/>" if block.anchor else ""
            self.chunks.append(
                f'<text:h text:style-name="Heading_20_{level}" text:outline-level="{level}">{mark}{self._inline(block.text)}</text:h>',
            )
        elif isinstance(block, Paragraph):
            self._paragraph("Standard", self._inline(block.text))
        elif isinstance(block, Equation):
            self._paragraph("Display_20_Equation", self._equation_frame(block) or xml_text(block.text))
        elif isinstance(block, Note):
            self._paragraph("Note", xml_text(block.text))
        elif isinstance(block, BulletList):
            items = "".join(
                f'<text:list-item><text:p text:style-name="List_20_Bullet">{self._inline(item)}</text:p></text:list-item>' for item in block.items
            )
            if items:
                self.chunks.append(f'<text:list text:style-name="L_Bullet">{items}</text:list>')
        elif isinstance(block, NumberedList):
            items = "".join(
                f'<text:list-item><text:p text:style-name="List_20_Number">{self._inline(item)}</text:p></text:list-item>' for item in block.items
            )
            if items:
                self.chunks.append(f'<text:list text:style-name="L_Number">{items}</text:list>')
        elif isinstance(block, Image):
            data = block.data
            if block.svg is not None:
                try:
                    data = svg_png(block.svg)  # a vector figure is shown as a picture, as in Word
                except Exception:  # noqa: BLE001 - a figure that cannot be drawn must never break report generation
                    data = b""
            frame = self._picture(data, alt=block.alt)
            if frame:
                self._paragraph("Standard", frame)
        elif isinstance(block, Table):
            self.table(block)
        elif isinstance(block, PageBreak):
            self.chunks.append('<text:p text:style-name="P_Break"/>')
        elif isinstance(block, Gap):
            return  # a PDF layout hint; paragraph styles carry the spacing

    def content(self):
        """`content.xml` as text chunks: the prolog and automatic styles (known only now), then the body."""
        yield (
            f'{XML_DECLARATION}<office:document-content {namespace_attrs(*_ALL_NS)} office:version="{ODF_VERSION}">'
            f"{FONT_FACES}"
            f'<office:automatic-styles>{"".join(self.styles)}</office:automatic-styles><office:body><office:text>'
        )
        yield from self.chunks
        yield "</office:text></office:body></office:document-content>"


def render_odt_document(document: ReportDocument) -> bytes:
    """Renders `document` as an ODT file.

    Args:
        document: The neutral report.

    Returns:
        ODT bytes.
    """
    document = finalize_links(document)
    width = page_dimensions_cm(document)[0]
    package = OdfPackage(MIME_ODT, document.title)
    body = _Body(document, package, width - 2 * _MARGIN_CM)
    body.cover()
    for block in document.blocks:
        body.block(block)
    package.add("content.xml", "text/xml", body.content())
    package.add("styles.xml", "text/xml", _styles_xml(document))
    return package.finish()


__all__ = ["render_odt_document"]
