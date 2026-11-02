"""
Module: services.report_styles

The fonts and heading colour a document layout sets once, for the whole document: the `styles` and `embed_fonts` keys of
its tree.

Responsibilities:
- `document_styles_problems`: the tree rules for `styles` (a closed shape, a font key's form, a size of 6 to 72 in half points, a
  heading colour word) as `(path, message)` pairs.
- `resolve_styles`: turns the stored words into a `DocumentStyles` the renderers read: font keys into families (the
  administrator's name and generic applied; a family the server no longer has falls back to the bundled one of the same
  kind, with a note), the heading colour into `#rrggbb`.
- `font_keys`: every font key a tree names (for the save warning and the run notes).
- `used_extra_families`: the administrator-provided families a built document draws and the faces of each, for the
  Word and OpenDocument embedding step.

Design decisions:
- A key that is well formed but not on this server is **not** a validation error: a layout moved between servers keeps
  its key and prints in the fallback with a note (the save route and every run report it), as the font admin page says.
- Nothing set means each format's own look, so a layout without `styles` renders as it did before this existed.
- The heading font follows the body font when it has none of its own, so a document set in one family does not keep
  sans headings by accident.

Dependencies: `report_colours`, `report_font_catalogue`, `report_fonts`, `report_model`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.services import report_font_catalogue
from app.services.report_colours import colour_word_problem, is_name, resolve_colour
from app.services.report_font_parts import FontUse
from app.services.report_fonts import FontFamily
from app.services.report_model import (
    SLOT_NAMES,
    BulletList,
    DocumentStyles,
    Grid,
    Heading,
    Note,
    NumberedList,
    PageStyleChange,
    Paragraph,
    ReportDocument,
    Styled,
    Table,
    text_runs,
)
from app.services.report_running import unmark

MIN_SIZE = 6.0
MAX_SIZE = 72.0
_FONT_KEY = re.compile(r"(?:sans|serif|mono|unicode|x-[a-z0-9][a-z0-9-]{0,59})")
_PARTS = {"body": ("font", "size"), "headings": ("font", "bold", "italic", "colour")}


def font_key_form_problem(value: Any) -> str | None:
    """Why `value` cannot be a font key (`None` when it can).

    A key's form is checked, not that the server has it: see the module docstring.
    """
    if isinstance(value, str) and _FONT_KEY.fullmatch(value):
        return None
    return "Must be a font: sans, serif, mono, unicode or a family the server administrator provides."


def size_problem(value: Any) -> str | None:
    """Why `value` is not a font size in points (`None` when it is): a number from 6 to 72 in steps of half a point."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return f"Must be a number of points from {MIN_SIZE:g} to {MAX_SIZE:g}."
    if not MIN_SIZE <= value <= MAX_SIZE:
        return f"Must be from {MIN_SIZE:g} to {MAX_SIZE:g} points."
    if value * 2 != int(value * 2):
        return "Must be a whole or half point."
    return None


def document_styles_problems(styles: Any, names: frozenset[str] | None, path: str = "styles") -> list[tuple[str, str]]:
    """The rule breaks in a layout's `styles` value, each with the path it concerns.

    Args:
        styles: The stored value.
        names: The colour names in scope (`report_colours.known_names`), or `None` when they are not known here.
        path: Where the value sits in the tree.

    Returns:
        `(path, message)` pairs; empty when the value is valid.
    """
    if not isinstance(styles, dict):
        return [(path, "Must be an object.")]
    if not styles:
        return [(path, "Leave the key out instead of writing it empty.")]
    problems: list[tuple[str, str]] = []
    for part, value in styles.items():
        here = f"{path}.{part}"
        if part not in _PARTS:
            problems.append((here, "Unknown key."))
            continue
        if not isinstance(value, dict):
            problems.append((here, "Must be an object."))
            continue
        if not value:
            problems.append((here, "Leave the key out instead of writing it empty."))
        for key, setting in value.items():
            where = f"{here}.{key}"
            if key not in _PARTS[part]:
                problems.append((where, "Unknown key."))
            elif key == "font":
                if message := font_key_form_problem(setting):
                    problems.append((where, message))
            elif key == "size":
                if message := size_problem(setting):
                    problems.append((where, message))
            elif key == "colour":
                if message := colour_word_problem(setting, names, allow_none=False):
                    problems.append((where, message))
            elif not isinstance(setting, bool):
                problems.append((where, "Must be true or false."))
    return problems


def _block_fonts(value: Any) -> Iterable[str]:
    """The `font` of every text and heading block, and of every custom table and its columns, under `value` (a node, or a
    list of them), at any depth."""
    if isinstance(value, dict):
        if value.get("type") in ("text", "heading", "grid") and isinstance(value.get("font"), str):
            yield value["font"]
        if value.get("type") == "grid" and isinstance(value.get("columns"), list):
            yield from (c["font"] for c in value["columns"] if isinstance(c, dict) and isinstance(c.get("font"), str))
        for child in value.values():
            if isinstance(child, dict | list):
                yield from _block_fonts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _block_fonts(child)


def _band_fonts(tree: Mapping[str, Any]) -> Iterable[str]:
    """The `font` of the header and footer of the root and of each page style."""
    holders = [tree, *(s for s in tree.get("page_styles") or [] if isinstance(s, dict))]
    for holder in holders:
        for kind in ("header", "footer"):
            band = holder.get(kind)
            if isinstance(band, dict) and isinstance(band.get("font"), str):
                yield band["font"]


def font_keys(tree: Mapping[str, Any]) -> list[str]:
    """The font keys a tree names, in the order body, headings, blocks, then header and footer bands, without repeats."""
    styles = tree.get("styles")
    keys: list[Any] = []
    if isinstance(styles, dict):
        keys = [(styles.get(part) or {}).get("font") for part in ("body", "headings") if isinstance(styles.get(part), dict)]
    keys.extend(_block_fonts(tree.get("nodes")))
    keys.extend(_band_fonts(tree))
    return list(dict.fromkeys(k for k in keys if isinstance(k, str)))


def font_warnings(db: Session, tree: Mapping[str, Any]) -> list[str]:
    """One sentence for each font a tree names that this server does not have (empty when all are available)."""
    return report_font_catalogue.font_problems(db, font_keys(tree))


def resolve_styles(
    db: Session, tree: Mapping[str, Any], *, accent: str, scheme: Mapping[str, str],
) -> tuple[DocumentStyles, list[str], dict[str, str]]:
    """The document styles a run draws with.

    Args:
        db: A database session (the administrator's font settings).
        tree: The valid layout tree.
        accent: The organisation's report accent as `#rrggbb`.
        scheme: The run's colour scheme (`report_colours.effective_scheme`).

    Returns:
        The styles, the run notes for fonts the server lacks, and `{colour name: #rrggbb}` for the scheme name the heading
        colour used (for the run's provenance).
    """
    embed = bool(tree.get("embed_fonts", False))
    styles = tree.get("styles")
    if not isinstance(styles, dict):
        return DocumentStyles(embed_fonts=embed), [], {}
    body = styles.get("body") or {}
    headings = styles.get("headings") or {}
    notes: list[str] = []

    def family(key: str | None) -> FontFamily | None:
        if key is None:
            return None
        found, note = report_font_catalogue.family_or_fallback(db, key)
        if note and note not in notes:
            notes.append(note)
        return found

    colour_word = headings.get("colour")
    colour = resolve_colour(colour_word, accent, scheme) if colour_word else None
    # Only a name in the scheme is recorded, not a hex colour or a reserved word.
    used: dict[str, str] = {colour_word: colour} if colour and colour_word and is_name(colour_word) else {}
    resolved = DocumentStyles(
        body_font=family(body.get("font")), body_size=float(body["size"]) if "size" in body else None,
        heading_font=family(headings.get("font")), heading_bold=headings.get("bold"),
        heading_italic=bool(headings.get("italic", False)), heading_colour=colour, embed_fonts=embed,
    )
    return resolved, notes, used


def _texts(document: ReportDocument) -> Iterable[str]:
    """Every marked-up text a document prints, for finding the bold and italic runs."""
    for block in document.blocks:
        if isinstance(block, Heading | Paragraph):
            yield block.text
        elif isinstance(block, BulletList | NumberedList):
            yield from block.items
        elif isinstance(block, Table):
            for row in block.rows:
                yield from (c for c in row if isinstance(c, str))
        elif isinstance(block, Grid):
            for grid_row in block.rows:
                for cell in grid_row.cells:
                    yield from cell.paragraphs


def used_extra_families(document: ReportDocument) -> list[FontUse]:
    """The administrator-provided families a document draws, each with the styles it uses.

    Regular is always used. Bold is used by headings (unless switched off), table headings and any bold run; italic by
    italic headings, notes and any italic run. The scan is a safe over-estimate: embedding a face a document ends up not
    needing costs size, never correctness.

    Args:
        document: The document.

    Returns:
        One entry per extra family (body first), empty when only bundled families are used.
    """
    styles = document.styles
    bold = italic = False
    for text in _texts(document):
        for run in text_runs(text):
            if isinstance(run, Styled):
                bold = bold or run.bold
                italic = italic or run.italic
    bands = [
        band for style in (document.style, *(b.style for b in document.blocks if isinstance(b, PageStyleChange)))
        for band in (style.header, style.footer) if band is not None and not band.empty
    ]
    marks = [(b, i) for band in bands if band.font is None for slot in SLOT_NAMES for _, b, i in map(unmark, band.slot(slot))]
    bold = bold or any(b for b, _ in marks)  # a band without a font of its own is set in the body font
    italic = italic or any(i for _, i in marks)
    has_tables = any(isinstance(b, Table) for b in document.blocks)
    uses: dict[str, FontUse] = {}

    def add(family: FontFamily | None, *wanted: str) -> None:
        if family is None or family.bundled:
            return
        before = uses[family.key].styles if family.key in uses else frozenset()
        uses[family.key] = FontUse(family, before | frozenset(wanted))

    add(
        styles.body_font, "regular", *(["bold"] if bold or has_tables else []),
        *(["italic"] if italic or any(isinstance(b, Note) for b in document.blocks) else []),
    )
    heading_bold = styles.heading_bold is not False  # the title is always set in the heading face
    heading_style = ("bold" if heading_bold else "") + ("italic" if styles.heading_italic else "")
    add(styles.text_font, heading_style or "regular")
    for band in bands:
        if band.font is not None:
            parts = [unmark(p) for slot in SLOT_NAMES for p in band.slot(slot)]
            wanted = (["bold"] if any(b for _, b, _ in parts) else []) + (["italic"] if any(i for _, _, i in parts) else [])
            add(band.font, "regular", *wanted, *(["bolditalic"] if any(b and i for _, b, i in parts) else []))
    for block in document.blocks:
        if isinstance(block, Heading | Paragraph | BulletList | NumberedList) and block.font is not None:
            texts = [block.text] if isinstance(block, Heading | Paragraph) else block.items
            runs = [run for text in texts for run in text_runs(text) if isinstance(run, Styled)]
            wanted = ["bold"] if any(r.bold for r in runs) else []
            wanted += ["italic"] if any(r.italic for r in runs) else []
            if isinstance(block, Heading):
                wanted += ["bold"] if heading_bold else []
                wanted += ["italic"] if styles.heading_italic else []
            add(block.font, "regular", *wanted, *(["bolditalic"] if {"bold", "italic"} <= set(wanted) else []))
        if isinstance(block, Grid):
            for row in block.rows:
                for cell in row.cells:
                    runs = [run for text in cell.paragraphs for run in text_runs(text) if isinstance(run, Styled)]
                    wanted = ["bold"] if cell.bold or any(r.bold for r in runs) else []
                    wanted += ["italic"] if any(r.italic for r in runs) else []
                    add(cell.font, "regular", *wanted, *(["bolditalic"] if {"bold", "italic"} <= set(wanted) else []))
    return list(uses.values())
