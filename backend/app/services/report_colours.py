"""
Module: services.report_colours

Colour words for custom reports: one vocabulary every colour setting reads, and the one resolver that turns a word into a
`#rrggbb` colour for the renderers.

Responsibilities:
- Name the reserved words (`accent`, `accent_light`, `accent_dark`, `white`, `black`, `none`) and the four standard scheme
  names (`primary`, `secondary`, `tint`, `neutral`) that always resolve, with no scheme of the layout's or the organisation's.
- Check a scheme (`palette_problems`) and a colour word (`colour_word_problem`).
- `effective_scheme`: the names a layout can use, resolved in the order layout, organisation, built-in standard set.
- `resolve_colour`: a word to a hex colour, or `None` for `none`.
- `colour_names_used`: the scheme names a tree refers to (so a name still in use cannot be removed, and a run records them).

Design decisions:
- **A colour is stored by name.** A block keeps `"fill": "primary"`, so changing the scheme re-colours everything that uses
  it; a hex typed into a block stays a hex. A layout with no scheme of its own follows the organisation's, live.
- **The resolver is the only door to markup.** A renderer writes a colour only from the `#rrggbb` this returns, never from
  the words an author typed.
- **A scheme entry is a hex colour or a derived/reserved word, never another name**, so resolution is one step and cannot
  loop.

Dependencies: none (pure functions; `services.report_layout_tree` and the evaluator call them).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

#: Words that mean a colour wherever one is set. `accent` is the organisation's report accent; the other two derive from it.
RESERVED_WORDS: tuple[str, ...] = ("accent", "accent_light", "accent_dark", "white", "black", "none")
#: Names that always resolve (the built-in Branding set); a scheme may redefine one.
STANDARD_COLOURS: dict[str, str] = {"primary": "accent", "secondary": "accent_dark", "tint": "accent_light", "neutral": "#6b7280"}
#: Most entries in one scheme.
MAX_PALETTE = 8
#: Share of the way `accent_light` is from the accent to white, and `accent_dark` from the accent to black.
TINT_TOWARDS_WHITE = 0.85
SHADE_TOWARDS_BLACK = 0.25
#: Words a scheme entry's colour may be (a name may not point at another name).
_ENTRY_WORDS = tuple(word for word in RESERVED_WORDS if word != "none")

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,23}")
DEFAULT_ACCENT = "#475569"


def is_name(value: Any) -> bool:
    """Whether `value` has the shape of a scheme name (it may still be unknown)."""
    return isinstance(value, str) and _NAME.fullmatch(value) is not None and value not in RESERVED_WORDS


def entries_of(palette: Any) -> dict[str, str]:
    """`{name: colour word}` of a scheme that may be missing or malformed (only well-formed entries are kept)."""
    if not isinstance(palette, list):
        return {}
    return {
        e["name"]: e["colour"] for e in palette
        if isinstance(e, dict) and isinstance(e.get("name"), str) and isinstance(e.get("colour"), str)
    }


def palette_problems(palette: Any, path: str = "palette") -> list[tuple[str, str]]:
    """Why `palette` is not a valid scheme.

    Args:
        palette: The stored list of `{name, colour}` objects.
        path: Where it sits in the tree, for the messages.

    Returns:
        `(path, message)` pairs; empty when it is valid.
    """
    if not isinstance(palette, list):
        return [(path, "Must be a list of colours, each with a name and a colour.")]
    problems: list[tuple[str, str]] = []
    if len(palette) > MAX_PALETTE:
        problems.append((path, f"A colour scheme holds at most {MAX_PALETTE} colours."))
    seen: set[str] = set()
    for i, entry in enumerate(palette[: MAX_PALETTE * 2]):
        here = f"{path}[{i}]"
        if not isinstance(entry, dict) or set(entry) != {"name", "colour"}:
            problems.append((here, "Must have exactly a name and a colour."))
            continue
        name, colour = entry["name"], entry["colour"]
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            problems.append((f"{here}.name", "Must be 1 to 24 lower-case letters, digits or underscores, starting with a letter."))
        elif name in RESERVED_WORDS:
            problems.append((f"{here}.name", f"{name} is a reserved colour word; choose another name."))
        elif name in seen:
            problems.append((f"{here}.name", f"The name {name} is used twice."))
        else:
            seen.add(name)
        if not isinstance(colour, str) or not (_HEX.fullmatch(colour) or colour in _ENTRY_WORDS):
            problems.append((f"{here}.colour", f"Must be a hex colour such as #1f3a5f, or one of: {', '.join(_ENTRY_WORDS)}."))
    return problems


def known_names(palette: Any, organization_names: Iterable[str] | None) -> frozenset[str] | None:
    """Every name a layout may use: its own scheme, the organisation's and the standard four.

    Args:
        palette: The layout's stored scheme.
        organization_names: The organisation's scheme names, or `None` when they are not known here (a name that looks like
            one is then accepted unchecked and the run decides).

    Returns:
        The names, or `None` when the organisation's are not known.
    """
    if organization_names is None:
        return None
    return frozenset((*STANDARD_COLOURS, *organization_names, *entries_of(palette)))


def colour_word_problem(value: Any, names: frozenset[str] | None, *, allow_none: bool = True) -> str | None:
    """Why `value` is not a colour a setting may hold (`None` when it is).

    Args:
        value: A hex colour, a reserved word or a scheme name.
        names: The names in scope (`known_names`); `None` accepts anything shaped like a name.
        allow_none: Whether `none` (no colour) is allowed here.
    """
    if isinstance(value, str):
        if _HEX.fullmatch(value) or (value in RESERVED_WORDS and (allow_none or value != "none")):
            return None
        if is_name(value) and (names is None or value in names):
            return None
        if is_name(value):
            return f"There is no colour called {value} in this layout's scheme or the organisation's."
    return f"Must be a hex colour such as #475569, a scheme name or one of: {', '.join(w for w in RESERVED_WORDS if allow_none or w != 'none')}."


def _mix(hex_value: str, target: int, share: float) -> str:
    """`hex_value` moved `share` of the way towards the grey level `target` (255 white, 0 black), as `#rrggbb`."""
    h = hex_value.lstrip("#")
    channels = [int(h[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(c + (target - c) * share):02x}" for c in channels)


def _full_hex(value: str) -> str:
    value = value.lower()
    return "#" + "".join(c * 2 for c in value[1:]) if len(value) == 4 else value


def effective_scheme(layout_palette: Any, organization_palette: Any) -> dict[str, str]:
    """`{name: colour word}` the layout resolves names by: the standard set, then the organisation's, then its own.

    A later source overrides an earlier one of the same name.
    """
    return {**STANDARD_COLOURS, **entries_of(organization_palette), **entries_of(layout_palette)}


def resolve_colour(word: str, accent: str, scheme: Mapping[str, str] | None = None) -> str | None:
    """A colour word as `#rrggbb`.

    Args:
        word: A hex colour, a reserved word or a scheme name (already checked by `colour_word_problem`).
        accent: The organisation's report accent as `#rrggbb`.
        scheme: `effective_scheme` of the run; without one only the standard names resolve.

    Returns:
        The colour, or `None` for `none`. A name the scheme lacks resolves as the accent, so a run never fails on one (the
        check that refuses it runs before the run).
    """
    accent = _full_hex(accent) if _HEX.fullmatch(accent) else DEFAULT_ACCENT
    if word in RESERVED_WORDS:
        return {
            "none": None, "accent": accent, "white": "#ffffff", "black": "#000000",
            "accent_light": _mix(accent, 255, TINT_TOWARDS_WHITE), "accent_dark": _mix(accent, 0, SHADE_TOWARDS_BLACK),
        }[word]
    if _HEX.fullmatch(word):
        return _full_hex(word)
    target = (scheme if scheme is not None else STANDARD_COLOURS).get(word)
    if target is None or target == word:
        return accent
    return resolve_colour(target, accent, None) if target in RESERVED_WORDS or _HEX.fullmatch(target) else accent


def colour_names_used(words: Iterable[Any]) -> set[str]:
    """The scheme names among colour words (not hex colours and not reserved words)."""
    return {w for w in words if is_name(w)}


__all__ = [
    "DEFAULT_ACCENT", "MAX_PALETTE", "RESERVED_WORDS", "STANDARD_COLOURS", "colour_names_used", "colour_word_problem", "effective_scheme",
    "entries_of", "is_name", "known_names", "palette_problems", "resolve_colour",
]
