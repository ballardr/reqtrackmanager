"""
Module: services.report_fonts

Lets PDF reports print text the built-in Helvetica cannot: Cyrillic, Polish and other Latin
Extended letters, Greek and anything else DejaVu Sans covers.

Responsibilities:
- Register the bundled DejaVu Sans (regular and bold) with ReportLab once.
- `mark_fallback`: wrap each run of characters Helvetica cannot encode in a `<font>` tag for the
  Paragraph markup `report_document.safe` produces.
- `text_width` and `draw_centred`: measure and draw mixed text where markup is not available
  (column sizing, the page footer).
- `needs_fallback`: tell a plain table cell that must become a Paragraph from one that can stay a string.

Design decisions:
- Text Helvetica can encode (Windows-1252, the encoding ReportLab's built-in fonts use) is left
  exactly as it was, so the look of existing reports is unchanged; only other characters switch font.
- A fallback run inside a bold style stays bold because the caller says so (`bold`): a `<font>` tag
  replaces the style's font name, so the weight cannot be inherited.
- ReportLab does not shape or reorder text, so Arabic and Indic scripts remain unsupported in PDFs,
  and CJK needs a font this module does not ship (those characters print as the font's missing-glyph
  box, as before). DOCX, ODT and HTML are unaffected.

Dependencies: ReportLab; the font files in `app/assets/fonts` (DejaVu Sans, licence alongside).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
UNICODE_FONT = "ReportUnicode"
UNICODE_FONT_BOLD = "ReportUnicode-Bold"

_registered = False


def _register() -> None:
    """Registers the bundled fonts and their regular/bold family on first use.

    Raises:
        OSError: If a bundled font file is missing from the installation.
    """
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont(UNICODE_FONT, str(_FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(UNICODE_FONT_BOLD, str(_FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(
        UNICODE_FONT, normal=UNICODE_FONT, bold=UNICODE_FONT_BOLD, italic=UNICODE_FONT, boldItalic=UNICODE_FONT_BOLD,
    )
    _registered = True


@lru_cache(maxsize=4096)
def _builtin_ok(char: str) -> bool:
    """Whether Helvetica can print `char` (it is in Windows-1252, or is whitespace)."""
    if char.isspace():
        return True
    try:
        char.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def needs_fallback(text: str) -> bool:
    """Whether `text` has a character Helvetica cannot print.

    Args:
        text: Any string.

    Returns:
        `True` when the Unicode font is needed for part of it.
    """
    return any(not _builtin_ok(c) for c in text)


def _runs(text: str) -> list[tuple[str, bool]]:
    """Splits `text` into consecutive `(run, uses_unicode_font)` pieces, joining neighbours of one kind."""
    runs: list[tuple[str, bool]] = []
    for char in text:
        unicode_char = not _builtin_ok(char)
        if runs and runs[-1][1] == unicode_char:
            runs[-1] = (runs[-1][0] + char, unicode_char)
        else:
            runs.append((char, unicode_char))
    return runs


def mark_fallback(escaped: str, *, bold: bool = False) -> str:
    """Wraps the characters Helvetica cannot print in a Unicode `<font>` tag.

    Args:
        escaped: Text already escaped for Paragraph markup (`&`, `<`, `>` replaced); the tag is the
            only markup added, and an entity such as `&amp;` is plain ASCII so it is never wrapped.
        bold: `True` when the paragraph's style is bold, so the fallback run is bold too.

    Returns:
        The text with each run of unprintable characters wrapped; unchanged when there are none.
    """
    if not needs_fallback(escaped):
        return escaped
    _register()
    name = UNICODE_FONT_BOLD if bold else UNICODE_FONT
    parts: list[str] = []
    pending_space = ""
    in_run = False
    for char in escaped:
        if not _builtin_ok(char):
            if not in_run:
                parts.append(f'<font name="{name}">')
                in_run = True
            parts.append(pending_space + char)
            pending_space = ""
        elif in_run and char.isspace():
            pending_space += char  # kept inside the run only if another unprintable character follows
        else:
            if in_run:
                parts.append("</font>")
                in_run = False
            parts.append(pending_space + char)
            pending_space = ""
    if in_run:
        parts.append("</font>")
    parts.append(pending_space)
    return "".join(parts)


def text_width(text: str, size: float, *, bold: bool = False) -> float:
    """The width of `text` in points, measuring each character in the font it will print in.

    Args:
        text: Plain (unescaped) text.
        size: Font size in points.
        bold: Whether the text is bold.

    Returns:
        The summed width.
    """
    if not needs_fallback(text):
        return stringWidth(text, "Helvetica-Bold" if bold else "Helvetica", size)
    _register()
    return sum(_run_width(run, unicode_font, size, bold) for run, unicode_font in _runs(text))


def _run_width(run: str, unicode_font: bool, size: float, bold: bool) -> float:
    """Width of one single-font run."""
    if unicode_font:
        return stringWidth(run, UNICODE_FONT_BOLD if bold else UNICODE_FONT, size)
    return stringWidth(run, "Helvetica-Bold" if bold else "Helvetica", size)


def draw_centred(canvas, x: float, y: float, text: str, size: float) -> None:
    """Draws `text` centred on `x`, switching font per run, on a ReportLab canvas.

    Args:
        canvas: The ReportLab canvas.
        x: Horizontal centre in points.
        y: Baseline in points.
        text: Plain text (a footer line).
        size: Font size in points.
    """
    if not needs_fallback(text):
        canvas.setFont("Helvetica", size)
        canvas.drawCentredString(x, y, text)
        return
    _register()
    cursor = x - text_width(text, size) / 2
    for run, unicode_font in _runs(text):
        canvas.setFont(UNICODE_FONT if unicode_font else "Helvetica", size)
        canvas.drawString(cursor, y, run)
        cursor += _run_width(run, unicode_font, size, False)
