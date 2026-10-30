"""
Module: services.report_page_styles

The page-style part of a document layout: the root's paper, orientation and margins, the named page styles a
`section` block can switch to, and the checks and conversion between the tree's JSON and `report_model.PageStyle`.

Responsibilities:
- Define the vocabulary and limits (`PAGE_SIZES`, `ORIENTATIONS`, the margin range, how many styles, how long a name).
- Check a margins object, a page style and the list of styles (`margins_problems`, `style_problems`,
  `styles_problems`), returning positioned messages the tree validator records.
- Resolve a valid tree to the neutral `PageStyle` of the document and of each named style (`resolve_page_styles`).

Design decisions:
- The root's `page_size`, `orientation` and `margins` are the document's own style; a named style leaves out what it
  shares with it (size, orientation, any margin side) and inherits that, so changing the document's paper changes
  every style that did not choose its own.
- Mirrored margins are one setting for the whole layout (`mirror_margins` on the root), not per style: Word keeps the
  setting for the document, and one rule behaves the same in PDF, Word, OpenDocument text and HTML.
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
STYLE_KEYS = ("name", "page_size", "orientation", "margins")


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


def _bounds_problem(style: PageStyle) -> str | None:
    """A message when `style`'s margins leave too little room for text, else `None`."""
    if style.usable_width_cm < MIN_TEXT_CM or style.usable_height_cm < MIN_TEXT_CM:
        return f"The margins leave less than {MIN_TEXT_CM:g} cm for text on a {style.page_size} page."
    return None


def style_problems(style: Any, defaults: PageStyle, *, mirror: bool) -> list[tuple[str, str]]:
    """What is wrong with one named page style.

    Args:
        style: The JSON object `{"name": ..., "page_size"?: ..., "orientation"?: ..., "margins"?: ...}`.
        defaults: The document's own style, which fills what the style leaves out.
        mirror: The layout's `mirror_margins`.

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
    if not found:
        problem = _bounds_problem(_style_of(style, defaults, mirror))
        if problem:
            found.append(("margins" if "margins" in style else "", problem))
    return found


def styles_problems(styles: Any, defaults: PageStyle, *, mirror: bool) -> list[tuple[str, str]]:
    """What is wrong with the `page_styles` list.

    Args:
        styles: The JSON value: a list of named styles.
        defaults: The document's own style.
        mirror: The layout's `mirror_margins`.

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
        found += [(f"{here}.{sub}" if sub else here, message) for sub, message in style_problems(style, defaults, mirror=mirror)]
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
    if not found:
        document, _ = resolve_page_styles({k: v for k, v in tree.items() if k != "page_styles"})
        problem = _bounds_problem(document)
        if problem:
            found.append(("margins" if "margins" in tree else "page_size", problem))
    return found


__all__ = [
    "DEFAULT_MARGIN_CM", "MARGIN_KEYS", "MARGIN_SIDES", "MAX_GUTTER_CM", "MAX_MARGIN_CM", "MAX_PAGE_STYLES", "MAX_STYLE_NAME_CHARS",
    "MIN_MARGIN_CM", "MIN_TEXT_CM", "ORIENTATIONS", "PAGE_SIZES", "document_style_problems", "margins_problems",
    "resolve_page_styles", "style_problems", "styles_problems",
]
