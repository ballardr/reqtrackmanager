"""
Module: services.report_odt_running

The running headers and footers of an OpenDocument text file: the page layouts and master pages of a document that has them.

Responsibilities:
- `running_styles`: the automatic styles the bands use (a borderless table, its columns and cells) for `styles.xml`.
- `page_layout`: a style's page layout, whose top and bottom margins leave room for the header and footer inside the
  margins the layout asked for (ODF puts a header and footer inside the text area, so the body would otherwise start lower
  than in the other formats).
- `master_page`: a master page with its header, left-hand header, first-page header and the same for the footer.

Design decisions:
- A header or footer is a borderless three-column table of left, centre and right cells, holding `text:page-number` and
  `text:page-count` fields and an optional logo frame.
- The first page of a master page is its own `style:header-first`/`style:footer-first`, so a section's first page can
  differ; the return to the document's style uses a separate master page without one (a continuation).
- The page layout of the cover page has no header or footer, as before.

Dependencies: `services.report_odf`, `services.report_image_layout`, `services.report_running`, `services.report_svg`.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.report_image_layout import placed_size_cm
from app.services.report_model import SLOT_NAMES, PageField, PageStyle, RunningBand
from app.services.report_odf import OdfPackage, length_cm, raster_info, xml_text
from app.services.report_page_styles import BAND_EDGE_CM
from app.services.report_running import band_for_page, cell_lines
from app.services.report_svg import svg_png

_ALIGN = {"left": "start", "centre": "center", "right": "end"}


def shown(band: RunningBand | None) -> bool:
    """Whether `band` prints something (it exists and is not the explicit empty band)."""
    return band is not None and not band.empty


def page_layout(name: str, style: PageStyle, *, bands: bool) -> str:
    """A `style:page-layout` for `style`: paper, orientation and margins.

    OpenDocument has no gutter, so it is added to the left margin (the inner edge when `style.mirror`). With `bands`, a
    shown header or footer takes the space inside the layout's own margin: the page margin is the gap to the page edge
    and the header or footer is as tall as the rest of the margin.
    """
    width, height = style.dimensions_cm
    margins = style.margins
    header, footer = bands and shown(style.header), bands and shown(style.footer)
    top = BAND_EDGE_CM if header else margins.top
    bottom = BAND_EDGE_CM if footer else margins.bottom
    header_style = (
        f'<style:header-style><style:header-footer-properties fo:min-height="{length_cm(margins.top - BAND_EDGE_CM)}" '
        'fo:margin-bottom="0cm" style:dynamic-spacing="false"/></style:header-style>' if header else ""
    )
    footer_style = (
        f'<style:footer-style><style:header-footer-properties fo:min-height="{length_cm(margins.bottom - BAND_EDGE_CM)}" '
        'fo:margin-top="0cm" style:dynamic-spacing="false"/></style:footer-style>' if footer
        else '<style:footer-style><style:header-footer-properties fo:min-height="0.5cm" fo:margin-top="0.3cm"/></style:footer-style>'
        if not bands else ""
    )
    return (
        f'<style:page-layout style:name="{name}">'
        f'<style:page-layout-properties fo:page-width="{length_cm(width)}" fo:page-height="{length_cm(height)}" '
        f'style:print-orientation="{"landscape" if style.landscape else "portrait"}" '
        f'style:page-usage="{"mirrored" if style.mirror else "all"}" '
        f'fo:margin-top="{length_cm(top)}" fo:margin-bottom="{length_cm(bottom)}" '
        f'fo:margin-left="{length_cm(margins.left + margins.gutter)}" fo:margin-right="{length_cm(margins.right)}"/>'
        f"{header_style}{footer_style}</style:page-layout>"
    )


def running_styles(index: int, style: PageStyle) -> str:
    """The automatic styles of the band tables of page style number `index`: the table, its columns and its cells."""
    width = style.usable_width_cm
    return (
        f'<style:style style:name="T_band{index}" style:family="table"><style:table-properties style:width="{length_cm(width)}" '
        'table:align="left"/></style:style>'
        f'<style:style style:name="C_bandcol{index}" style:family="table-column"><style:table-column-properties '
        f'style:column-width="{length_cm(width / 3)}"/></style:style>'
        '<style:style style:name="C_band" style:family="table-cell"><style:table-cell-properties fo:border="none" fo:padding="0cm" '
        'style:vertical-align="middle"/></style:style>'
    )


class RunningWriter:
    """Writes the band elements of one file, numbering its tables and pictures."""

    def __init__(self, package: OdfPackage) -> None:
        self.package = package
        self.tables = 0
        self.pictures = 0

    def logo(self, band: RunningBand, cell_cm: float) -> str:
        """The logo's frame, or `""` when it cannot be drawn."""
        logo = band.logo
        if logo is None:
            return ""
        try:
            data = svg_png(logo.svg) if logo.svg is not None else logo.data
        except Exception:  # noqa: BLE001 - a figure that cannot be drawn must never break report generation
            return ""
        info = raster_info(data) if data else None
        size = placed_size_cm(replace(logo, data=data, svg=None, height_cm=band.logo_height_cm, width=None), cell_cm) if info else None
        if info is None or size is None:
            return ""
        path = self.package.add_picture(data, info[0], info[1])
        self.pictures += 1
        return (
            f'<draw:frame draw:style-name="fr_block" draw:name="BandLogo{self.pictures}" text:anchor-type="as-char" '
            f'svg:width="{length_cm(size[0])}" svg:height="{length_cm(size[1])}">'
            f'<draw:image xlink:href="{path}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/></draw:frame>'
        )

    def table(self, band: RunningBand, index: int, style: PageStyle) -> str:
        """The band as a three-column table."""
        self.tables += 1
        cell_cm = style.usable_width_cm / 3
        cells = []
        for slot in SLOT_NAMES:
            lines = cell_lines(band.slot(slot)) or [[]]
            paragraphs = []
            for number, line in enumerate(lines):
                content = ""
                if number == 0 and band.logo is not None and band.logo_slot == slot:
                    frame = self.logo(band, cell_cm)
                    content += frame + ('<text:s text:c="2"/>' if frame and line else "")
                for part in line:
                    content += (
                        '<text:page-number text:select-page="current">1</text:page-number>' if part is PageField.PAGE
                        else "<text:page-count>1</text:page-count>" if part is PageField.PAGES else xml_text(part)
                    )
                paragraphs.append(f'<text:p text:style-name="Band_{slot}">{content}</text:p>')
            cells.append(f'<table:table-cell table:style-name="C_band" office:value-type="string">{"".join(paragraphs)}</table:table-cell>')
        return (
            f'<table:table table:name="Band{self.tables}" table:style-name="T_band{index}">'
            f'<table:table-column table:style-name="C_bandcol{index}" table:number-columns-repeated="3"/>'
            f'<table:table-row>{"".join(cells)}</table:table-row></table:table>'
        )

    def element(self, tag: str, band: RunningBand | None, index: int, style: PageStyle, *, left_hand: bool = False, hidden: bool = False) -> str:
        """`<style:{tag}>` holding the band (or an empty paragraph where the band is skipped); `""` when there is no band."""
        if not shown(band):
            return ""
        assert band is not None
        if hidden:
            return f"<style:{tag}><text:p/></style:{tag}>"
        return f"<style:{tag}>{self.table(band_for_page(band, mirrored=left_hand, verso=left_hand), index, style)}</style:{tag}>"

    def master_page(self, name: str, layout: str, index: int, style: PageStyle, *, first_differs: bool) -> str:
        """A master page: header, left-hand header and first-page header, then the same for the footer.

        Args:
            name: The master page's name.
            layout: Its page layout's name.
            index: The page style's number (for the table styles).
            style: The style, carrying the header and footer.
            first_differs: Whether the first page of the master page has its own header and footer.
        """
        parts = []
        for kind, band in (("header", style.header), ("footer", style.footer)):
            parts.append(self.element(kind, band, index, style))
            if style.mirror:
                parts.append(self.element(f"{kind}-left", band, index, style, left_hand=True))
            if first_differs and band is not None:
                parts.append(self.element(f"{kind}-first", band, index, style, hidden=not band.first_page))
        return f'<style:master-page style:name="{name}" style:page-layout-name="{layout}">{"".join(parts)}</style:master-page>'


def first_differs(style: PageStyle) -> bool:
    """Whether a shown header or footer of `style` skips the first page."""
    return any(shown(band) and not band.first_page for band in (style.header, style.footer) if band is not None)


__all__ = ["RunningWriter", "first_differs", "page_layout", "running_styles", "shown"]
