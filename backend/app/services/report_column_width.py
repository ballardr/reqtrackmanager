"""
Module: services.report_column_width

A table column's forced width: what an author may write, and how each renderer turns it into a size.

Responsibilities:
- Parse a width written as a percentage of the table (`30%`) or a length (`4 cm`, `40 mm`); no width means auto.
- Give the canonical text of a width, so the layout tree and the text view agree.
- Resolve a table's widths to centimetres for a given usable width (`resolve_table_widths_cm`), and a sheet's to
  centimetres (`sheet_widths_cm`), the same way in every renderer.

Design decisions:
- A percentage is of the table, not of a page, so it survives a change of page size or orientation.
- Auto columns share what the fixed ones leave over (in proportion to their weights, if the table has any); widths that
  fill more or less than the table are scaled to fit it exactly, so a table is always as wide as its section.
- No column is laid out narrower than `MIN_COLUMN_CM`: that is the stated limit for a column squeezed below a cell's padding,
  and a word longer than the column breaks inside it rather than failing the layout or widening the column.
- A sheet has no page, so its percentages are of a nominal sheet width (`SHEET_REFERENCE_CM`); a sheet's auto columns keep
  their content-sized width.

Dependencies: none.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

#: Narrowest length an author may ask for, in cm: below it a single character would not fit.
MIN_LENGTH_CM = 0.5
#: Widest length an author may ask for, in cm.
MAX_LENGTH_CM = 100.0
#: Narrowest percentage an author may ask for.
MIN_PERCENT = 1.0
#: The narrowest a column is laid out, in cm: room for its cell padding and a character or two; a longer word breaks.
MIN_COLUMN_CM = 0.8
#: The width an auto column is never squeezed below while the fixed columns are being fitted, in cm.
MIN_AUTO_CM = 1.0
#: The width of one character of a spreadsheet column, in cm (a sheet sizes its columns in characters).
CM_PER_CHARACTER = 0.19
#: The table width a sheet's percentages are of, in cm (a sheet has no page).
SHEET_REFERENCE_CM = 25.0

_WIDTH = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(%|cm|mm)\s*$", re.IGNORECASE)


def parse_width(spec: object) -> tuple[str, float] | None:
    """Reads a width.

    Args:
        spec: `"30%"`, `"4 cm"` or `"40 mm"` (spaces and case do not matter).

    Returns:
        `("percent", value)` or `("cm", value in cm)`; `None` when `spec` is not a width.
    """
    if not isinstance(spec, str):
        return None
    match = _WIDTH.match(spec)
    if match is None:
        return None
    value, unit = float(match.group(1)), match.group(2).lower()
    return ("percent", value) if unit == "%" else ("cm", value / 10 if unit == "mm" else value)


def canonical_width(spec: str) -> str:
    """A width in its one written form (`30%`, `4 cm`, `40 mm`), for the tree and the text view.

    Args:
        spec: A valid width.

    Returns:
        The width as `parse_width` read it, in the unit it was written in.

    Raises:
        ValueError: `spec` is not a width.
    """
    match = _WIDTH.match(spec) if isinstance(spec, str) else None
    if match is None:
        raise ValueError(f"Not a width: {spec!r}")
    number = f"{float(match.group(1)):g}"
    unit = match.group(2).lower()
    return f"{number}%" if unit == "%" else f"{number} {unit}"


def width_problem(spec: object) -> str | None:
    """Why `spec` is not an acceptable width, or `None` when it is.

    Args:
        spec: What the author wrote.
    """
    parsed = parse_width(spec)
    if parsed is None:
        return 'Must be a percentage of the table or a length, like "30%", "4 cm" or "40 mm" (leave it out for automatic).'
    unit, value = parsed
    if unit == "percent" and not MIN_PERCENT <= value <= 100:
        return f"A percentage must be from {MIN_PERCENT:g}% to 100%."
    if unit == "cm" and not MIN_LENGTH_CM <= value <= MAX_LENGTH_CM:
        return f"A length must be from {MIN_LENGTH_CM * 10:g} mm to {MAX_LENGTH_CM:g} cm."
    return None


def percent_total(specs: Sequence[object]) -> float:
    """The sum of the percentage widths among `specs`."""
    return sum(p[1] for s in specs if (p := parse_width(s)) is not None and p[0] == "percent")


def resolve_table_widths_cm(
    specs: Sequence[str | None], usable_cm: float, weights: Sequence[float] | None = None,
) -> list[float]:
    """The width of each column of a table whose columns have forced widths.

    Fixed columns take their width; auto columns share the rest in proportion to `weights`; then the whole row is scaled
    to `usable_cm`, so the table is as wide as its section and never wider.

    Args:
        specs: One width per column (`None` = auto).
        usable_cm: The width available to the table, in cm.
        weights: Relative sizes of the columns, used among the auto ones (`None` = equal).

    Returns:
        One width in cm per column, adding up to `usable_cm`.
    """
    fixed: list[float | None] = []
    for spec in specs:
        parsed = parse_width(spec) if spec else None
        fixed.append(None if parsed is None else parsed[1] / 100 * usable_cm if parsed[0] == "percent" else parsed[1])
    autos = [i for i, width in enumerate(fixed) if width is None]
    shares = [weights[i] if weights and weights[i] > 0 else 1.0 for i in range(len(specs))]
    resolved = [width or 0.0 for width in fixed]
    if autos:
        left = max(usable_cm - sum(resolved), MIN_AUTO_CM * len(autos))
        total = sum(shares[i] for i in autos)
        for i in autos:
            resolved[i] = left * shares[i] / total
    return _fit(resolved, usable_cm)


def _fit(widths: list[float], usable_cm: float) -> list[float]:
    """Scales `widths` to add up to `usable_cm`, no column narrower than `MIN_COLUMN_CM` (or an equal share, if smaller).

    A column squeezed to the floor keeps it and the others give up the difference, so a cell always has room for its padding
    and a long word breaks inside it instead of failing the layout.
    """
    count = len(widths)
    if count == 0:
        return []
    floor = min(MIN_COLUMN_CM, usable_cm / count)
    pinned: set[int] = set()
    while True:
        free = [i for i in range(count) if i not in pinned]
        room = usable_cm - floor * len(pinned)
        total = sum(widths[i] for i in free)
        scaled = {i: (widths[i] * room / total if total > 0 else room / len(free)) for i in free}
        narrow = {i for i, width in scaled.items() if width < floor}
        if not narrow:
            return [floor if i in pinned else scaled[i] for i in range(count)]
        pinned |= narrow


def sheet_widths_cm(specs: Sequence[str | None]) -> list[float | None]:
    """The width of each column of a sheet in cm; `None` keeps the column's content-sized width.

    Args:
        specs: One width per column (`None` = auto).
    """
    widths: list[float | None] = []
    for spec in specs:
        parsed = parse_width(spec) if spec else None
        widths.append(None if parsed is None else parsed[1] / 100 * SHEET_REFERENCE_CM if parsed[0] == "percent" else parsed[1])
    return widths
