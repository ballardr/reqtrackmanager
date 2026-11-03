"""
Module: services.report_band_cells

How wide each cell of a header or footer is and where its content sits vertically, decided once for every renderer.

Responsibilities:
- `resolve_band_cells`: the width in cm and the vertical alignment of the left, centre and right cells of a band on a
  page whose text is `usable_cm` wide. The PDF, Word, OpenDocument and HTML renderers all read this and nothing else.
- `fixed_widths_problem`: why the fixed cell widths of a band (as written in the layout) do not fit a page, for the
  layout check.

Design decisions:
- A cell with no width fits its content (its widest line at the band's size, plus a logo placed in it), an empty cell
  only its floor (`MIN_COLUMN_CM`). The room the cells do not need goes to the centre cell when it has content, so a
  short left and right text leave the title its width; otherwise to the other cells with content, in proportion to what
  they need.
- When the cells need more than the band has, the widest cell gives way first (water-filling): a long centre text wraps
  in the centre and the short sides keep their width.
- A fixed width is a percentage of the band or a length, as a table column's is; the same parser reads both.
- The default vertical alignment is top, so a one-line cell and a two-line cell start on the same line.

Dependencies: `services.report_column_width`, `services.report_fonts`, `services.report_image_layout`,
`services.report_model`, `services.report_running`.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace

from app.services.report_column_width import MIN_COLUMN_CM, parse_width
from app.services.report_fonts import text_width, using_family
from app.services.report_image_layout import placed_size_cm
from app.services.report_model import SLOT_NAMES, VALIGN_CHOICES, PageField, RunningBand
from app.services.report_running import band_size_pt, cell_lines, unmark

#: Room added to a cell's content for the gap between cells, in cm.
CELL_PADDING_CM = 0.3
#: The gap between a logo and the text beside it, in cm (as the PDF draws it).
LOGO_GAP_CM = 0.2
#: Stand-ins for the page numbers when a cell's width is measured (a page number is not known until the end).
_PAGE_SAMPLE = {PageField.PAGE: "88", PageField.PAGES: "888"}
_PT_CM = 2.54 / 72


@dataclass(frozen=True)
class BandCell:
    """One resolved cell of a band.

    Attributes:
        slot: `left`, `centre` or `right`.
        width_cm: The cell's width in cm; the three add up to the band's width.
        valign: One of `VALIGN_CHOICES`.
    """

    slot: str
    width_cm: float
    valign: str


def _fixed_cm(spec: str | None, usable_cm: float) -> float | None:
    """A fixed width as cm of a band `usable_cm` wide, `None` when the cell has none (or an unreadable one)."""
    parsed = parse_width(spec) if spec else None
    if parsed is None:
        return None
    return parsed[1] / 100 * usable_cm if parsed[0] == "percent" else parsed[1]


def _content_cm(band: RunningBand, slot: str, usable_cm: float) -> float:
    """What the cell's content needs in cm: its widest line, and a logo placed in it, plus the padding; the floor if empty."""
    size = band_size_pt(band.size)
    widest = 0.0
    for line in cell_lines(band.slot(slot)):
        points = 0.0
        for part in line:
            words, bold, italic = unmark(part)
            text = _PAGE_SAMPLE[words] if isinstance(words, PageField) else words
            points += text_width(text, size, bold=bold, italic=italic)
        widest = max(widest, points)
    width = widest * _PT_CM
    if band.logo is not None and band.logo_slot == slot:
        placed = placed_size_cm(replace(band.logo, height_cm=band.logo_height_cm, width=None), usable_cm)
        if placed is not None:
            width += placed[0] + (LOGO_GAP_CM if widest else 0.0)
    return max(MIN_COLUMN_CM, width + CELL_PADDING_CM) if width > 0 else MIN_COLUMN_CM


def _fit_to(needs: list[float], room: float) -> list[float]:
    """Shrinks `needs` to add up to `room`, the largest first, so the short ones keep what they asked for (none below the floor)."""
    floor = min(MIN_COLUMN_CM, room / len(needs))
    if sum(needs) <= room:
        return needs
    low, high = floor, max(needs)
    for _ in range(50):
        level = (low + high) / 2
        if sum(max(floor, min(need, level)) for need in needs) > room:
            high = level
        else:
            low = level
    return [max(floor, min(need, low)) for need in needs]


def resolve_band_cells(band: RunningBand, usable_cm: float) -> tuple[BandCell, BandCell, BandCell]:
    """The width and vertical alignment of each cell of a band.

    Args:
        band: The band, already mirrored for the page it is drawn on.
        usable_cm: The width of the text on that page, which the band spans.

    Returns:
        The left, centre and right cells in that order; their widths add up to `usable_cm`.
    """
    fixed = [None if (cm := _fixed_cm(spec, usable_cm)) is None else max(MIN_COLUMN_CM, cm) for spec in band.widths]  # a stored width below the floor never reaches a renderer as 0
    free = [i for i, width in enumerate(fixed) if width is None]
    widths = [width or 0.0 for width in fixed]
    if free and sum(widths) + MIN_COLUMN_CM * len(free) > usable_cm + 1e-9:  # the layout check refuses this; here the fixed cells give way
        held = [i for i in range(len(widths)) if i not in free]
        for i, width in zip(held, _fit_to([widths[i] for i in held], usable_cm - MIN_COLUMN_CM * len(free)), strict=True):
            widths[i] = width
    if free:
        room = max(usable_cm - sum(widths), MIN_COLUMN_CM * len(free))
        with using_family(band.font.key) if band.font else nullcontext():  # measured in the font the band prints in
            needs = [_content_cm(band, SLOT_NAMES[i], usable_cm) for i in free]
        if sum(needs) >= room:
            given = _fit_to(needs, room)
        else:
            extra = room - sum(needs)
            filled = [k for k, i in enumerate(free) if band.slot(SLOT_NAMES[i]) or (band.logo is not None and band.logo_slot == SLOT_NAMES[i])]
            centre = [k for k, i in enumerate(free) if SLOT_NAMES[i] == "centre" and k in filled]
            takers = centre or filled or list(range(len(free)))
            weight = sum(needs[k] for k in takers)
            given = [
                need + (extra if centre else extra * need / weight) if k in takers else need for k, need in enumerate(needs)
            ]
        for k, i in enumerate(free):
            widths[i] = given[k]
    total = sum(widths)
    if total > 0 and abs(total - usable_cm) > 1e-9:
        widths = [w * usable_cm / total for w in widths]
    cells = [
        BandCell(slot, widths[i], own if (own := band.valigns[i]) in VALIGN_CHOICES else band.valign)
        for i, slot in enumerate(SLOT_NAMES)
    ]
    return cells[0], cells[1], cells[2]


def fixed_widths_problem(widths: dict[str, str], usable_cm: float) -> str | None:
    """Why a band's fixed cell widths cannot fit a band `usable_cm` wide, or `None` when they can.

    Args:
        widths: `{slot: width text}` of the cells that have a fixed width (valid widths).
        usable_cm: The text width of the page the band is on.

    Returns:
        A message when the fixed cells, with the floor for every cell that has none, fill or pass the band; or a fixed
        length wider than the band.
    """
    fixed = {slot: cm for slot, spec in widths.items() if (cm := _fixed_cm(spec, usable_cm)) is not None}
    for slot, cm in fixed.items():
        if cm > usable_cm + 1e-9:
            return f"The {slot} cell is {cm:.1f} cm wide, wider than the {usable_cm:.1f} cm of text on the page."
    left = len(SLOT_NAMES) - len(fixed)
    if sum(fixed.values()) + MIN_COLUMN_CM * left > usable_cm + 1e-9:
        return (
            f"The fixed cell widths take {sum(fixed.values()):.1f} cm of the {usable_cm:.1f} cm of text, leaving too little "
            f"for the other {'cell' if left == 1 else 'cells'} (each needs at least {MIN_COLUMN_CM * 10:g} mm)."
        )
    return None
