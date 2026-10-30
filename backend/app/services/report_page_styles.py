"""
Module: services.report_page_styles

The page-style part of a document layout: the root's paper, orientation and margins, the named page styles a
`section` block can switch to, and the checks and conversion between the tree's JSON and `report_model.PageStyle`.

Responsibilities:
- Define the vocabulary and limits (`PAGE_SIZES`, `ORIENTATIONS`, the margin range, how many styles, how long a name).
- Check a margins object, a page style and the list of styles (`margins_problems`, `style_problems`,
  `styles_problems`), returning positioned messages the tree validator records.
- Resolve a valid tree to the neutral `PageStyle` of the document and of each named style (`resolve_page_styles`).
- Check a running header or footer (`band_problems`: its cells, logo and first-page choice; the space it needs, `band_height_cm`,
  against the margin it sits in) and say which one each style prints (`effective_bands`).

Design decisions:
- The root's `page_size`, `orientation` and `margins` are the document's own style; a named style leaves out what it
  shares with it (size, orientation, any margin side) and inherits that, so changing the document's paper changes
  every style that did not choose its own.
- Mirrored margins are one setting for the whole layout (`mirror_margins` on the root), not per style: Word keeps the
  setting for the document, and one rule behaves the same in PDF, Word, OpenDocument text and HTML.
- A header or footer belongs to the document or to a named style; a style that writes none prints the document's, and the
  fit check uses the style's own margin, so a style with a small margin cannot take over a header that no longer fits.
  The placeholders in a band's text are checked by the tree validator, which knows the layout's variables.
- A margin has a minimum (the room a header or footer needs) and every style must leave at least `MIN_TEXT_CM` of
  text width and height, so no layout can produce a page that holds nothing.

Dependencies: `services.report_model` (the neutral page style).
"""

from __future__ import annotations

from typing import Any

from app.services.report_model import DEFAULT_MARGIN_CM, DEFAULT_PAGE_SIZE, Margins, PageStyle

ORIENTATIONS = ("portrait", "landscape")
#: The page sizes a document layout can choose (`report_model.PAGE_SIZES_CM`); A4 when none is written.
PAGE_SIZES = ("A3", "A4", "A5", "Letter", "Legal")
#: The sides of a page, in the order the text view writes them.
MARGIN_SIDES = ("top", "bottom", "left", "right")
MARGIN_KEYS = (*MARGIN_SIDES, "gutter")
MIN_MARGIN_CM = 1.0
MAX_MARGIN_CM = 10.0
MAX_GUTTER_CM = 5.0
#: The least text width and height a page style must leave between its margins.
MIN_TEXT_CM = 5.0
MAX_PAGE_STYLES = 10
MAX_STYLE_NAME_CHARS = 40
STYLE_KEYS = ("name", "page_size", "orientation", "margins", "header", "footer")
#: A running header or footer: its three cells, a logo and whether the first page shows it.
BAND_KEYS = ("left", "centre", "right", "logo", "first_page")
FIRST_PAGE_CHOICES = ("same", "none")
MAX_SLOT_CHARS = 300
MAX_SLOT_LINES = 3
LOGO_KEYS = ("file", "height", "slot")
MIN_LOGO_CM, MAX_LOGO_CM = 0.3, 5.0
#: Space between the page edge and a header or footer, and the height of one line of its text, in cm.
BAND_EDGE_CM = 0.5
BAND_LINE_CM = 0.4
#: The names a header or footer may use beyond the layout's own: the page number and the number of pages.
PAGE_FIELD_NAMES = ("page", "pages")


def margins_problems(margins: Any) -> list[tuple[str, str]]:
    """What is wrong with a `margins` object.

    Args:
        margins: The JSON value: `{"top": 2, "gutter": 1, ...}`, every key optional.

    Returns:
        `(key, message)` pairs, `key` empty for a problem with the object itself.
    """
    if not isinstance(margins, dict):
        return [("", "Must be an object with any of: " + ", ".join(MARGIN_KEYS) + ".")]
    found: list[tuple[str, str]] = []
    for key, value in margins.items():
        if key not in MARGIN_KEYS:
            found.append((str(key), "Unknown key."))
            continue
        low, high = (0.0, MAX_GUTTER_CM) if key == "gutter" else (MIN_MARGIN_CM, MAX_MARGIN_CM)
        if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
            found.append((key, f"Must be a number of cm from {low:g} to {high:g}."))
    return found


def band_height_cm(band: dict[str, Any]) -> float:
    """The height in cm a header or footer needs: its tallest cell (lines of text, or the logo) and the gap to the page edge."""
    lines = max((str(band.get(slot, "")).count("\n") + 1 for slot in ("left", "centre", "right") if band.get(slot)), default=0)
    logo = band.get("logo")
    logo_cm = float(logo["height"]) if isinstance(logo, dict) and isinstance(logo.get("height"), int | float) else 0.0
    return BAND_EDGE_CM + max(lines * BAND_LINE_CM, logo_cm) if lines or logo_cm else 0.0


def band_problems(band: Any) -> list[tuple[str, str]]:
    """What is wrong with the structure of a header or footer object (not the placeholders in its text, or its fit).

    Args:
        band: The JSON value: `{"left": ..., "centre": ..., "right": ..., "logo": {...}, "first_page": ...}`, every key
            optional; `{}` is a header or footer that prints nothing.

    Returns:
        `(subpath, message)` pairs relative to the band (`logo.height`, empty for the object itself).
    """
    if not isinstance(band, dict):
        return [("", "Must be an object with any of: " + ", ".join(BAND_KEYS) + ".")]
    found = [(str(key), "Unknown key.") for key in band if key not in BAND_KEYS]
    for slot in ("left", "centre", "right"):
        if slot not in band:
            continue
        text = band[slot]
        if not isinstance(text, str):
            found.append((slot, "Must be text."))
        elif len(text) > MAX_SLOT_CHARS or text.count("\n") + 1 > MAX_SLOT_LINES:
            found.append((slot, f"Too long (at most {MAX_SLOT_CHARS} characters on {MAX_SLOT_LINES} lines)."))
    if "first_page" in band and band["first_page"] not in FIRST_PAGE_CHOICES:
        found.append(("first_page", f"Must be one of: {', '.join(FIRST_PAGE_CHOICES)}."))
    if "logo" in band:
        logo = band["logo"]
        if not isinstance(logo, dict):
            found.append(("logo", "Must be an object with: " + ", ".join(LOGO_KEYS) + "."))
        else:
            found += [(f"logo.{key}", "Unknown key.") for key in logo if key not in LOGO_KEYS]
            if not isinstance(logo.get("file"), str) or not logo.get("file"):
                found.append(("logo.file", "Required: pick an image from the library."))
            height = logo.get("height")
            if isinstance(height, bool) or not isinstance(height, int | float) or not MIN_LOGO_CM <= height <= MAX_LOGO_CM:
                found.append(("logo.height", f"Required: a height in cm from {MIN_LOGO_CM:g} to {MAX_LOGO_CM:g}."))
            if logo.get("slot", "left") not in ("left", "centre", "right"):
                found.append(("logo.slot", "Must be one of: left, centre, right."))
    return found


def _bounds_problem(style: PageStyle) -> str | None:
    """A message when `style`'s margins leave too little room for text, else `None`."""
    if style.usable_width_cm < MIN_TEXT_CM or style.usable_height_cm < MIN_TEXT_CM:
        return f"The margins leave less than {MIN_TEXT_CM:g} cm for text on a {style.page_size} page."
    return None


def style_problems(
    style: Any, defaults: PageStyle, *, mirror: bool, inherited: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """What is wrong with one named page style.

    Args:
        style: The JSON object `{"name": ..., "page_size"?: ..., "orientation"?: ..., "margins"?: ...}`.
        defaults: The document's own style, which fills what the style leaves out.
        mirror: The layout's `mirror_margins`.
        inherited: The document's own `header` and `footer` JSON (see `_fit_problems`).

    Returns:
        `(subpath, message)` pairs relative to the style (`margins.top`, `name`, empty for the object itself).
    """
    if not isinstance(style, dict):
        return [("", "Must be an object.")]
    found = [(key, "Unknown key.") for key in style if key not in STYLE_KEYS]
    if "page_size" in style and style["page_size"] not in PAGE_SIZES:
        found.append(("page_size", f"Must be one of: {', '.join(PAGE_SIZES)}."))
    if "orientation" in style and style["orientation"] not in ORIENTATIONS:
        found.append(("orientation", f"Must be one of: {', '.join(ORIENTATIONS)}."))
    if "margins" in style:
        found += [(f"margins.{key}" if key else "margins", message) for key, message in margins_problems(style["margins"])]
    for band in ("header", "footer"):
        if band in style:
            found += [(f"{band}.{sub}" if sub else band, message) for sub, message in band_problems(style[band])]
    if not found:
        resolved = _style_of(style, defaults, mirror)
        problem = _bounds_problem(resolved)
        if problem:
            found.append(("margins" if "margins" in style else "", problem))
        found += _fit_problems(style, resolved, inherited)
    return found


def _fit_problems(holder: dict[str, Any], style: PageStyle, inherited: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Problems when a header or footer of `holder` (a root or a named style) is taller than the margin it sits in.

    Args:
        holder: The root or page style JSON, whose `header` and `footer` are structurally valid.
        style: Its resolved style (the margins the band must fit).
        inherited: The document's own `header`/`footer` JSON for a named style, which uses them when it has none of its
            own, so a style with small margins cannot take over a header that no longer fits.

    Returns:
        `(subpath, message)` pairs: `header` or `footer`, or `margins` (`top` or `bottom` when the band is inherited).
    """
    found: list[tuple[str, str]] = []
    for band, margin in (("header", style.margins.top), ("footer", style.margins.bottom)):
        own = isinstance(holder.get(band), dict)
        source = holder.get(band) if own else (inherited or {}).get(band)
        needed = band_height_cm(source) if isinstance(source, dict) else 0.0
        if needed > margin + 1e-9:
            side = "top" if band == "header" else "bottom"
            where = band if own else f"margins.{side}" if "margins" in holder and side in holder["margins"] else "margins"
            whose = "" if own else " (the document's)"
            found.append((
                where,
                f"The {band}{whose} needs a {side} margin of at least {needed:.1f} cm (it is {margin:g} cm), or a smaller logo and fewer lines.",
            ))
    return found


def effective_bands(tree: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The header and footer JSON each page style prints, after inheritance.

    Args:
        tree: A valid layout tree.

    Returns:
        The document's own `{"header": …, "footer": …}` (a key only when the layout wrote one; `{}` is an empty band),
        and `{style name: {...}}` where a style that wrote none takes the document's.
    """
    document: dict[str, Any] = {band: tree[band] for band in ("header", "footer") if band in tree}
    return document, {
        style["name"]: {**document, **{band: style[band] for band in ("header", "footer") if band in style}}
        for style in tree.get("page_styles", [])
    }


def styles_problems(
    styles: Any, defaults: PageStyle, *, mirror: bool, inherited: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """What is wrong with the `page_styles` list.

    Args:
        styles: The JSON value: a list of named styles.
        defaults: The document's own style.
        mirror: The layout's `mirror_margins`.
        inherited: The document's own `header` and `footer` JSON.

    Returns:
        `(subpath, message)` pairs relative to the list (`[1].margins.top`, empty for the list itself).
    """
    if not isinstance(styles, list):
        return [("", "Must be a list of page styles.")]
    if len(styles) > MAX_PAGE_STYLES:
        return [("", f"Too many page styles (the limit is {MAX_PAGE_STYLES}).")]
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, style in enumerate(styles):
        here = f"[{index}]"
        found += [(f"{here}.{sub}" if sub else here, message) for sub, message in style_problems(style, defaults, mirror=mirror, inherited=inherited)]
        name = style.get("name") if isinstance(style, dict) else None
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            found.append((f"{here}.name", "Required: a name without spaces at either end."))
        elif len(name) > MAX_STYLE_NAME_CHARS:
            found.append((f"{here}.name", f"Too long ({len(name)} characters; the limit is {MAX_STYLE_NAME_CHARS})."))
        elif any(ord(c) < 32 for c in name) or '"' in name or "\\" in name:
            found.append((f"{here}.name", "Must not contain control characters, quotes or backslashes."))
        elif name in seen:
            found.append((f"{here}.name", f'The name "{name}" is used by another page style.'))
        else:
            seen.add(name)
    return found


def _style_of(overrides: dict[str, Any], defaults: PageStyle, mirror: bool) -> PageStyle:
    """`defaults` with what `overrides` (a root or a named style) states instead."""
    merged = {side: getattr(defaults.margins, side) for side in MARGIN_KEYS}
    merged.update({k: v for k, v in (overrides.get("margins") or {}).items() if k in MARGIN_KEYS})
    return PageStyle(
        overrides.get("page_size", defaults.page_size),
        overrides.get("orientation", "landscape" if defaults.landscape else "portrait") == "landscape",
        Margins(**{key: float(value) for key, value in merged.items()}),
        mirror,
    )


def resolve_page_styles(tree: dict[str, Any]) -> tuple[PageStyle, dict[str, PageStyle]]:
    """The document's own page style and the named ones, from a valid document tree.

    Args:
        tree: A valid layout tree.

    Returns:
        The document's style and `{name: style}` for each entry of `page_styles`.
    """
    mirror = tree.get("mirror_margins") is True
    base = PageStyle(DEFAULT_PAGE_SIZE, False, Margins(), mirror)
    document = _style_of(
        {"page_size": tree.get("page_size", DEFAULT_PAGE_SIZE), "orientation": tree.get("orientation", "portrait"),
         "margins": tree.get("margins")},
        base, mirror,
    )
    return document, {style["name"]: _style_of(style, document, mirror) for style in tree.get("page_styles", [])}


def document_style_problems(tree: dict[str, Any]) -> list[tuple[str, str]]:
    """What is wrong with the root's own margins (used once the root's keys have been checked).

    Args:
        tree: The layout tree, whose root `page_size`, `orientation` and `margins` are valid on their own.

    Returns:
        `(path, message)` pairs from the tree's root.
    """
    found: list[tuple[str, str]] = []
    if "margins" in tree:
        found += [(f"margins.{key}" if key else "margins", message) for key, message in margins_problems(tree["margins"])]
    for band in ("header", "footer"):
        if band in tree:
            found += [(f"{band}.{sub}" if sub else band, message) for sub, message in band_problems(tree[band])]
    if not found:
        document, _ = resolve_page_styles({k: v for k, v in tree.items() if k != "page_styles"})
        problem = _bounds_problem(document)
        if problem:
            found.append(("margins" if "margins" in tree else "page_size", problem))
        found += _fit_problems(tree, document)
    return found


__all__ = [
    "DEFAULT_MARGIN_CM", "MARGIN_KEYS", "MARGIN_SIDES", "MAX_GUTTER_CM", "MAX_MARGIN_CM", "MAX_PAGE_STYLES", "MAX_STYLE_NAME_CHARS",
    "BAND_EDGE_CM", "BAND_KEYS", "BAND_LINE_CM", "FIRST_PAGE_CHOICES", "MAX_LOGO_CM", "MAX_SLOT_CHARS", "MAX_SLOT_LINES",
    "MIN_LOGO_CM", "MIN_MARGIN_CM", "MIN_TEXT_CM", "ORIENTATIONS", "PAGE_FIELD_NAMES", "PAGE_SIZES",
    "band_height_cm", "band_problems", "document_style_problems", "effective_bands", "margins_problems", "resolve_page_styles",
    "style_problems", "styles_problems",
]
