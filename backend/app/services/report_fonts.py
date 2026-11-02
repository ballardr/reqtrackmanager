"""
Module: services.report_fonts

Lets PDF reports print text the built-in Helvetica cannot: Cyrillic, Polish and other Latin
Extended letters, Greek and anything else DejaVu Sans covers.

Responsibilities:
- Register the bundled DejaVu Sans (regular, bold, italic and bold italic) with ReportLab once.
- `FAMILIES` / `get_family`: the closed table of document font families (Sans, Serif, Mono, Unicode Sans),
  each with the PDF face files and the names Word, OpenDocument and HTML are told. Nothing reads it for
  drawing yet; renderers adopt it one at a time.
- `register_family`, `pdf_face`, `covers`: register a family's four faces with ReportLab, name the face for
  a weight and slant, and say whether a family's face has a glyph for a character.
- `mark_fallback`: wrap each run of characters Helvetica cannot encode in a `<font>` tag for the
  Paragraph markup `report_document.safe` produces.
- `text_width`, `draw_aligned` and `draw_centred`: measure and draw mixed text where markup is not available
  (column sizing, the page footer).
- `needs_fallback`: tell a plain table cell that must become a Paragraph from one that can stay a string.
- `using_family`: draw and measure in a document font family for the duration of one render (a layout's body font);
  with none active everything is Helvetica as before.

Design decisions:
- A family's PDF faces are metric-compatible with the name Word/ODT/HTML ask for (Liberation Sans for
  Arial, Liberation Serif for Times New Roman, Liberation Mono for Courier New), so a line breaks the same
  in all four formats when the reader has the named font or a metric-compatible one. Measured, with the
  numbers, in docs/decisions.md (the custom reports fonts spike entry). A reader with neither substitutes a
  different-width face and reflows; the generic fallback names below limit but do not remove that.
- Fonts offered are a closed list: the four bundled families and the families a server administrator
  mounts. Organisation-uploaded fonts are refused on purpose (untrusted bytes, unknown licence).
- Text Helvetica can encode (Windows-1252, the encoding ReportLab's built-in fonts use) is left
  exactly as it was, so the look of existing reports is unchanged; only other characters switch font.
- A fallback run inside a bold or italic style keeps that style because the caller says so (`bold`, `italic`): a
  `<font>` tag replaces the style's font name, so weight and slant cannot be inherited.
- The active family is a context variable, not a parameter, because `safe` and `text_width` are called from a hundred
  places that do not know the layout; `render_pdf_document` sets it once around a whole render.
- ReportLab does not shape or reorder text, so Arabic and Indic scripts remain unsupported in PDFs,
  and CJK needs a font this module does not ship (those characters print as the font's missing-glyph
  box, as before). DOCX, ODT and HTML are unaffected.

Dependencies: ReportLab (also reads each face's glyph coverage); the font files in `app/assets/fonts` (DejaVu Sans) and
`app/assets/report_fonts` (Liberation Sans, Serif and Mono), each with its licence alongside.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
UNICODE_FONT = "ReportUnicode"
UNICODE_FONT_BOLD = "ReportUnicode-Bold"
UNICODE_FONT_ITALIC = "ReportUnicode-Italic"
UNICODE_FONT_BOLD_ITALIC = "ReportUnicode-BoldItalic"
_LIBERATION_DIR = _FONT_DIR.parent / "report_fonts"

STYLES = ("regular", "bold", "italic", "bolditalic")

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
    pdfmetrics.registerFont(TTFont(UNICODE_FONT_ITALIC, str(_FONT_DIR / "DejaVuSans-Oblique.ttf")))
    pdfmetrics.registerFont(TTFont(UNICODE_FONT_BOLD_ITALIC, str(_FONT_DIR / "DejaVuSans-BoldOblique.ttf")))
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


_active: ContextVar[str | None] = ContextVar("report_font_family", default=None)


@contextmanager
def using_family(key: str | None) -> Iterator[None]:
    """Makes `key` the family the fallback and the measuring functions draw in, until the block ends.

    Args:
        key: A family key, or `None` for the built-in Helvetica.

    Raises:
        KeyError: If `key` is not an offered family.
        OSError: If a bundled font file is missing from the installation.
    """
    if key is not None:
        register_family(key)
    token = _active.set(key)
    try:
        yield
    finally:
        _active.reset(token)


def _printable(char: str) -> bool:
    """Whether the active font (the family's regular face, else Helvetica) has a glyph for `char`."""
    key = _active.get()
    return _builtin_ok(char) if key is None else covers(key, char)


def active_face(bold: bool = False) -> str:
    """The regular or bold face of the active font (Helvetica when no family is active)."""
    key = _active.get()
    if key is None:
        return "Helvetica-Bold" if bold else "Helvetica"
    return pdf_face(key, bold=bold)


def _fallback_font(bold: bool, italic: bool) -> str:
    """The bundled Unicode face for a weight and slant."""
    if bold and italic:
        return UNICODE_FONT_BOLD_ITALIC
    return UNICODE_FONT_BOLD if bold else UNICODE_FONT_ITALIC if italic else UNICODE_FONT


def needs_fallback(text: str) -> bool:
    """Whether `text` has a character the active font (Helvetica unless a family is active) cannot print.

    Args:
        text: Any string.

    Returns:
        `True` when the Unicode font is needed for part of it.
    """
    return any(not _printable(c) for c in text)


def _runs(text: str) -> list[tuple[str, bool]]:
    """Splits `text` into consecutive `(run, uses_unicode_font)` pieces, joining neighbours of one kind."""
    runs: list[tuple[str, bool]] = []
    for char in text:
        unicode_char = not _printable(char)
        if runs and runs[-1][1] == unicode_char:
            runs[-1] = (runs[-1][0] + char, unicode_char)
        else:
            runs.append((char, unicode_char))
    return runs


def mark_fallback(escaped: str, *, bold: bool = False, italic: bool = False) -> str:
    """Wraps the characters the active font cannot print in a Unicode `<font>` tag.

    Args:
        escaped: Text already escaped for Paragraph markup (`&`, `<`, `>` replaced); the tag is the
            only markup added, and an entity such as `&amp;` is plain ASCII so it is never wrapped.
        bold: `True` when the paragraph's style is bold, so the fallback run is bold too.
        italic: `True` when the text is italic, so the fallback run is too.

    Returns:
        The text with each run of unprintable characters wrapped; unchanged when there are none.
    """
    if not needs_fallback(escaped):
        return escaped
    _register()
    name = _fallback_font(bold, italic)
    parts: list[str] = []
    pending_space = ""
    in_run = False
    for char in escaped:
        if not _printable(char):
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
        return stringWidth(text, active_face(bold), size)
    _register()
    return sum(_run_width(run, unicode_font, size, bold) for run, unicode_font in _runs(text))


def _run_width(run: str, unicode_font: bool, size: float, bold: bool) -> float:
    """Width of one single-font run."""
    if unicode_font:
        return stringWidth(run, UNICODE_FONT_BOLD if bold else UNICODE_FONT, size)
    return stringWidth(run, active_face(bold), size)


def draw_aligned(canvas, x: float, y: float, text: str, size: float, align: str = "center") -> None:
    """Draws `text` on a ReportLab canvas, switching font per run.

    Args:
        canvas: The ReportLab canvas.
        x: The anchor in points: the left edge, the centre or the right edge of the text, by `align`.
        y: Baseline in points.
        text: Plain text (a footer line).
        size: Font size in points.
        align: `left`, `center` or `right`.
    """
    start = x - text_width(text, size) * {"left": 0.0, "center": 0.5, "right": 1.0}[align]
    if not needs_fallback(text):
        canvas.setFont(active_face(False), size)
        canvas.drawString(start, y, text)
        return
    _register()
    cursor = start
    for run, unicode_font in _runs(text):
        canvas.setFont(UNICODE_FONT if unicode_font else active_face(False), size)
        canvas.drawString(cursor, y, run)
        cursor += _run_width(run, unicode_font, size, False)


def draw_centred(canvas, x: float, y: float, text: str, size: float) -> None:
    """Draws `text` centred on `x` (see `draw_aligned`)."""
    draw_aligned(canvas, x, y, text, size, "center")


@dataclass(frozen=True)
class FontFamily:
    """One document font family: what the PDF draws and what the other formats are told.

    Attributes:
        key: Stable identifier stored in layouts (`sans`, `serif`, `mono`, `unicode`).
        label: Name shown to authors.
        files: PDF face file per style in `STYLES` (regular, bold, italic, bolditalic).
        word_name: Font name written to Word (`w:rFonts`), OpenDocument and HTML; a metric-compatible
            PDF face is chosen so the layouts match where the reader has this font.
        generic: Generic family for fallback: `sans-serif`, `serif` or `monospace`.
        bundled: `False` for a family the server administrator mounted (`report_font_directory`).
        faces_found: The styles the family really has a file for; a missing style reuses the nearest face in `files`.
    """

    key: str
    label: str
    files: dict[str, Path]
    word_name: str
    generic: str
    bundled: bool = True
    faces_found: tuple[str, ...] = STYLES

    @property
    def css_stack(self) -> str:
        """The CSS `font-family` value: the name, then the generic family."""
        return f'"{self.word_name}", {self.generic}'

    @property
    def odf_generic(self) -> str:
        """The OpenDocument `style:font-family-generic` value for `generic`."""
        return {"sans-serif": "swiss", "serif": "roman", "monospace": "modern"}[self.generic]

    def pdf_name(self, style: str) -> str:
        """The ReportLab font name this family's `style` face is registered under."""
        return f"Report-{self.key}-{style}"


def _faces(directory: Path, stem: str, names: tuple[str, str, str, str]) -> dict[str, Path]:
    """Maps `STYLES` to the files `directory/stem-<name>.ttf` for the four style names given."""
    return {style: directory / f"{stem}{name}.ttf" for style, name in zip(STYLES, names, strict=True)}


_LIBERATION_NAMES = ("-Regular", "-Bold", "-Italic", "-BoldItalic")

FAMILIES: dict[str, FontFamily] = {
    f.key: f
    for f in (
        FontFamily("sans", "Sans", _faces(_LIBERATION_DIR, "LiberationSans", _LIBERATION_NAMES), "Arial", "sans-serif"),
        FontFamily("serif", "Serif", _faces(_LIBERATION_DIR, "LiberationSerif", _LIBERATION_NAMES), "Times New Roman", "serif"),
        FontFamily("mono", "Mono", _faces(_LIBERATION_DIR, "LiberationMono", _LIBERATION_NAMES), "Courier New", "monospace"),
        FontFamily(
            "unicode", "Unicode Sans", _faces(_FONT_DIR, "DejaVuSans", ("", "-Bold", "-Oblique", "-BoldOblique")),
            "DejaVu Sans", "sans-serif",
        ),
    )
}


_extras: dict[str, FontFamily] = {}


def set_extra_families(families: dict[str, FontFamily]) -> None:
    """Replaces the administrator-provided families `get_family` also knows (`report_font_catalogue` calls this).

    Args:
        families: Extra families by key; a key that is also a bundled key is ignored.
    """
    global _extras
    _extras = {k: f for k, f in families.items() if k not in FAMILIES}


def get_family(key: str) -> FontFamily:
    """Looks up a document font family, bundled or administrator-provided.

    Args:
        key: A key from `FAMILIES` or an extra family's `x-<slug>` key.

    Returns:
        The family.

    Raises:
        KeyError: If `key` is not an offered family.
    """
    return FAMILIES[key] if key in FAMILIES else _extras[key]


def register_family(key: str) -> FontFamily:
    """Registers a family's four faces with ReportLab (once) so `<b>` and `<i>` pick the right face.

    Args:
        key: A key from `FAMILIES`.

    Returns:
        The family.

    Raises:
        KeyError: If `key` is not an offered family.
        OSError: If a bundled font file is missing from the installation.
    """
    family = get_family(key)
    if family.pdf_name("regular") not in pdfmetrics.getRegisteredFontNames():
        for style, path in family.files.items():
            pdfmetrics.registerFont(TTFont(family.pdf_name(style), str(path)))
        pdfmetrics.registerFontFamily(
            family.pdf_name("regular"), normal=family.pdf_name("regular"), bold=family.pdf_name("bold"),
            italic=family.pdf_name("italic"), boldItalic=family.pdf_name("bolditalic"),
        )
    return family


def pdf_face(key: str, *, bold: bool = False, italic: bool = False) -> str:
    """The ReportLab font name for a family's weight and slant, registering the family if needed.

    Args:
        key: A key from `FAMILIES`.
        bold: Whether the text is bold.
        italic: Whether the text is italic.

    Returns:
        The registered font name.

    Raises:
        KeyError: If `key` is not an offered family.
    """
    family = register_family(key)
    return family.pdf_name(("bold" if bold else "") + ("italic" if italic else "") or "regular")


@lru_cache(maxsize=16)
def _cmap(path: Path) -> frozenset[int]:
    """The code points a font file has a glyph for."""
    return frozenset(TTFont("coverage", str(path)).face.charToGlyph)


def covers(key: str, char: str) -> bool:
    """Whether a family's regular face has a glyph for `char`.

    Used to decide which characters need the Unicode Sans fallback inside another family.

    Args:
        key: A key from `FAMILIES`.
        char: One character.

    Returns:
        `True` when the face draws it (whitespace always counts as covered).

    Raises:
        KeyError: If `key` is not an offered family.
    """
    return char.isspace() or ord(char) in _cmap(get_family(key).files["regular"])
