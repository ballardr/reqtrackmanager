"""
Module: services.report_running

The running header and footer of a document report, as the renderers share them.

Responsibilities:
- `apply_template_defaults`: give a layout's document the branding template's footer text and logo wherever the layout's
  page style says nothing, and a plain "Page n" footer when there is no template.
- `cell_lines`, `band_visible` and `band_for_page`: the small rules every renderer applies the same way (the lines of a
  cell, whether a band shows on a page, and which band a left-hand page gets when the margins mirror).

Design decisions:
- A header or footer is an invisible three-column table (left, centre, right) in the page margin. The renderers draw it
  in their own way (a canvas callback, a Word header part, an ODF master-page header, an HTML band); the content and the
  rules are decided here once so PDF, Word, OpenDocument text and HTML cannot drift.
- The layout's own header or footer wins over the template's: a template supplies the default only where the page style
  (or the document's, which a style inherits) wrote none. An explicit empty band is "print nothing" and is kept.
- The template's cover page flag keeps working: the default header and footer are not printed on the first page when the
  template asks for a cover page, as the Word and OpenDocument footers always did.

Dependencies: `services.report_model` (the neutral bands), `services.report_document` (for typing the branding only).
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from app.services.report_model import (
    Image,
    PageField,
    PageStyle,
    PageStyleChange,
    ReportDocument,
    RunningBand,
    SlotPart,
)

if TYPE_CHECKING:
    from app.services.report_document import ReportBranding

#: The height of the template logo when it becomes a header, in cm.
DEFAULT_LOGO_HEIGHT_CM = 0.9


def default_footer(branding: ReportBranding | None) -> RunningBand:
    """The footer a layout gets when its page style writes none: the template's footer text and the page number, centred."""
    prefix = f"{branding.footer_text}  ·  " if branding and branding.footer_text else ""
    return RunningBand(
        centre=(f"{prefix}Page ", PageField.PAGE), first_page=not (branding and branding.include_cover_page),
    )


def default_header(branding: ReportBranding | None) -> RunningBand | None:
    """The header a layout gets when its page style writes none: the template's logo at the left, or none without one."""
    if branding is None or not branding.logo_bytes:
        return None
    return RunningBand(
        logo=Image(data=branding.logo_bytes, decorative=True), logo_height_cm=DEFAULT_LOGO_HEIGHT_CM,
        first_page=not branding.include_cover_page,
    )


def apply_template_defaults(document: ReportDocument, branding: ReportBranding | None) -> ReportDocument:
    """`document` with the template's defaults wherever a page style has no header or footer of its own.

    Args:
        document: A layout's document, whose styles carry the layout's own bands (`None` where it wrote none).
        branding: The organisation template's branding, or `None`.

    Returns:
        A copy in which every style (the document's and each section's) has a footer, and a header when the template has
        a logo.
    """
    header, footer = default_header(branding), default_footer(branding)

    def filled(style: PageStyle) -> PageStyle:
        return replace(
            style, header=style.header if style.header is not None else header,
            footer=style.footer if style.footer is not None else footer,
        )

    blocks = [replace(b, style=filled(b.style)) if isinstance(b, PageStyleChange) else b for b in document.blocks]
    own = filled(document.style)
    return replace(document, blocks=blocks, header=own.header, footer=own.footer)


def cell_lines(parts: tuple[SlotPart, ...]) -> list[list[SlotPart]]:
    """A cell's parts split into lines at each line break in its text; an empty cell has no lines."""
    lines: list[list[SlotPart]] = [[]]
    for part in parts:
        if isinstance(part, PageField):
            lines[-1].append(part)
            continue
        pieces = part.split("\n")
        for i, piece in enumerate(pieces):
            if i:
                lines.append([])
            if piece:
                lines[-1].append(piece)
    return lines if any(lines) else []


def band_visible(band: RunningBand | None, *, first_page: bool) -> bool:
    """Whether `band` prints on a page: it has content, and it is not the first page of a band that skips it."""
    return band is not None and not band.empty and (band.first_page or not first_page)


def band_for_page(band: RunningBand, *, mirrored: bool, verso: bool) -> RunningBand:
    """The band as printed on a page: the left-hand page of a double-sided document swaps the left and right cells."""
    return band.mirrored() if mirrored and verso else band


__all__ = [
    "DEFAULT_LOGO_HEIGHT_CM", "apply_template_defaults", "band_for_page", "band_visible", "cell_lines", "default_footer",
    "default_header",
]
