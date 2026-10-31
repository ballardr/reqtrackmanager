"""
Module: services.report_running

The running header and footer of a document report, as the renderers share them.

Responsibilities:
- `apply_default_bands`: give a layout's document a plain "Page n" footer wherever the layout's page style says nothing.
- `cell_lines`, `band_visible` and `band_for_page`: the small rules every renderer applies the same way (the lines of a
  cell, whether a band shows on a page, and which band a left-hand page gets when the margins mirror).

Design decisions:
- A header or footer is an invisible three-column table (left, centre, right) in the page margin. The renderers draw it
  in their own way (a canvas callback, a Word header part, an ODF master-page header, an HTML band); the content and the
  rules are decided here once so PDF, Word, OpenDocument text and HTML cannot drift.
- A custom layout is never forced to print the organisation's footer text, logo or cover page: it reads them as
  `{{org.footer_text}}`, the `org_logo` image and `if org.include_cover_page` (`services.report_org_values`). The default
  here is only the page number, and only where the page style (or the document's, which a style inherits) wrote no
  footer. An explicit empty band is "print nothing" and is kept.

Dependencies: `services.report_model` (the neutral bands).
"""

from __future__ import annotations

from dataclasses import replace

from app.services.report_model import (
    PageField,
    PageStyle,
    PageStyleChange,
    ReportDocument,
    RunningBand,
    SlotPart,
)


def default_footer() -> RunningBand:
    """The footer a layout gets when its page style writes none: the page number, centred."""
    return RunningBand(centre=("Page ", PageField.PAGE))


def apply_default_bands(document: ReportDocument) -> ReportDocument:
    """`document` with a page-number footer wherever a page style has no footer of its own.

    Args:
        document: A layout's document, whose styles carry the layout's own bands (`None` where it wrote none).

    Returns:
        A copy in which every style (the document's and each section's) has a footer.
    """
    footer = default_footer()

    def filled(style: PageStyle) -> PageStyle:
        return replace(style, footer=style.footer if style.footer is not None else footer)

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


__all__ = ["apply_default_bands", "band_for_page", "band_visible", "cell_lines", "default_footer"]
