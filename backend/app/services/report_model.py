"""
Module: services.report_model

The neutral report document every renderer consumes . A report is built once, as a
`ReportDocument` of simple blocks, and then rendered by `report_pdf`
(ReportLab) and `report_docx` (python-docx), so a layout change is made in one
place rather than once per output format.

Responsibilities:
- Block types: `Heading`, `Paragraph`, `Equation` (a display equation), `Note`, `BulletList`, `Image` (raster bytes or SVG markup), `Table`,
  `Grid` (an author-written table: merged cells, per-cell alignment and colour), `Gap`, `VerticalSpace`,
  `BottomStart`/`BottomEnd` (a run placed at the page foot), `PageBreak`,
  `PageStyleChange` (a new page in another `PageStyle`: paper, orientation, `Margins`), and the
  `ReportDocument` that holds them with the title, branding and the page style of its own pages; `RunningBand` (a
  header or footer: an invisible left, centre and right table, with page fields and an optional logo).
- `Sheet`: one named table of a table-family report (CSV, XLSX, ODS); not a
  document block, so it is never inside a `ReportDocument`. Its cells are text or a typed `DataCell` (a real number,
  date or UTC instant, so a spreadsheet can sort, sum and filter it); `typed_cell` is the one place a value is judged
  safe to type.
- Cell tones: `Table.tones` marks cells the screen colours (a rating band, a
  matrix cell) and `TONE_FILL` is the one tone-to-colour table both renderers use;
  `text_on` picks black or white text for any fill by contrast.
- `markdown_to_blocks`: the restricted Markdown reader (headings, paragraphs,
  bullet and numbered lists, bold, italic and code spans, images on their own line) that turns author-written
  text (a layout's text block, and the introduction, chapters and appendices) into blocks.

Design decisions:
- Blocks hold plain strings and bytes only. Nothing here knows about ReportLab
  markup or Word XML, so escaping is the renderer's job, done at one choke
  point per renderer.
- Inline Markdown is read for four things only: bold (`**x**`), italic (`*x*`, `_x_`), code (`` `x` ``) and links
  (`[words](address)`). They ride in `MathText` as `Styled` runs, so every string-only consumer sees the plain words
  without the markers. Everything else stays the author's source verbatim, as it always was: bare addresses and
  autolinks, reference-style links, images inside a sentence, raw HTML and entities. The reader runs on the author's
  text alone, before any `{{value}}` is filled in, so a record value holding `**` or a backtick is plain text, never a
  style. Math (`\\( \\)`, `$$ $$`) is set aside first and put back unread, so `\\(a_1 * b_2\\)` is never taken for
  emphasis.
- A link is the one place text points somewhere else, so it is the most guarded: `link_problem` allows only an absolute
  http, https or mailto address (or `#heading` in the same document) and refuses whitespace, control characters, quotes,
  angle brackets and backslashes; an address with a `{{placeholder}}` is checked again after it is filled; a link that
  fails stays as written text; `finalize_links` (called first by every renderer) gives each heading an anchor and turns a
  link to a missing heading into plain words; and each renderer writes the address only as an attribute or relationship
  target, never as markup.
- Images arrive pre-resolved as bytes (`report_document.resolve_report_images`
  does the tenant check) or as SVG markup (sanitised by `report_svg` in each renderer), so this module
  and the renderers never fetch anything.
- A tone is a name (the same five as the on-screen `BadgeTone`), never a colour,
  so a collector cannot put an arbitrary value into PDF or Word XML. The text of
  a toned cell still carries its meaning (the band name), so a greyscale print
  reads the same.
- An equation is TeX source in the model, never a drawing: each renderer asks `report_math` for the form it needs
  (SVG for PDF and HTML, native markup or a picture for Word) and prints the source when it cannot draw it. Inline
  equations ride in `MathText`, a `str` subclass, so headings, paragraphs, list items and table cells need no new
  field and every string-only consumer is unaffected. Only the layout evaluator makes `Equation`, from text where
  math is switched on, so a module report's ordinary text is never scanned for delimiters.
- `Gap` is a vertical-whitespace hint kept so the PDF layout is exactly what it
  was before the model existed; the DOCX renderer ignores it and relies on
  paragraph spacing.

Dependencies: markdown-it-py. `ReportBranding` is imported for typing only.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

from app.services.branding import contrast_text_hex
from app.services.report_column_width import resolve_table_widths_cm

if TYPE_CHECKING:
    from app.services.report_document import ReportBranding
    from app.services.report_fonts import FontFamily

class _ReportMarkdown(MarkdownIt):
    """The Markdown reader with the author's link addresses left exactly as written.

    markdown-it percent-encodes an address and refuses some kinds; here neither happens, so a `{{placeholder}}` in an
    address survives to be filled later, and `link_problem` (not the library) decides what may be a link.
    """

    def normalizeLink(self, url: str) -> str:
        return url

    def validateLink(self, url: str) -> bool:
        return True


# The reader understands emphasis, code spans and `[words](address)` links and leaves the rest of the inline syntax as
# written text: no autolinks or bare addresses, no reference-style links, no raw HTML, no entities and no images inside
# a sentence. Backslash escapes are not the reader's either: only the six this module documents are honoured (see
# `_set_aside`), so a backslash anywhere else, as in `C:\temp` or an unclosed `\(`, prints as written.
_md = _ReportMarkdown().disable(["image", "autolink", "html_inline", "entity", "strikethrough", "escape", "reference"])
_IMAGE_ONLY = re.compile(r"^!\[[^\]]*\]\(([^)\s]+)[^)]*\)$")
# Where math or an escaped character was set aside while reading: a private-use pair around its number.
_MATH_MARK = re.compile("\ue000(\\d+)\ue001")

# Cell tones. Each is the on-screen `.scoring-cell--<tone>` tint (theme.css): the tone's base colour
# mixed into white (the light-theme surface) at the percentage the stylesheet uses. A print has no
# dark theme, so the light values are the only ones needed.
_TONE_BASE: dict[str, tuple[str, float]] = {
    "muted": ("#5a6472", 0.15),
    "info": ("#0e7490", 0.22),
    "accent": ("#2f855a", 0.22),
    "warning": ("#b7791f", 0.28),
    "danger": ("#c53030", 0.28),
}


def _tint(base: str, share: float) -> str:
    """`base` (`#RRGGBB`) mixed into white; returns six upper-case hex digits."""
    channels = (int(base[i:i + 2], 16) for i in (1, 3, 5))
    return "".join(f"{round(c * share + 255 * (1 - share)):02X}" for c in channels)


#: Cell fill by tone, six hex digits.
TONE_FILL: dict[str, str] = {tone: _tint(base, share) for tone, (base, share) in _TONE_BASE.items()}


def text_on(fill_hex: str) -> str:
    """The text colour that reads best on `fill_hex`: black or white by WCAG contrast (the rule the screen
    applies to the accent colour, `services.branding.contrast_text_hex`), so a dark fill gets white text and a
    light one black, whatever colour an organisation chose.

    Args:
        fill_hex: The background, `RRGGBB` or `#RRGGBB`.

    Returns:
        Six upper-case hex digits (`000000` or `FFFFFF`).
    """
    return contrast_text_hex(fill_hex).lstrip("#").upper()

#: The kinds of address a link may point at (`#anchor` links to a heading of the same document).
LINK_SCHEMES = ("http", "https", "mailto")
MAX_LINK_CHARS = 2000
_LINK_BAD = re.compile(r"[\s\x00-\x1f\x7f<>\"\\]")
_ANCHOR = re.compile(r"^[\w-]+$")
_MAILTO = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def link_problem(href: str) -> str | None:
    """Why `href` may not be a link, or `None` when it may.

    Allowed: an absolute `http` or `https` address with a host, a `mailto:` address, and `#anchor` (a heading of the
    same document). Whitespace, control characters, angle brackets, quotes and backslashes are refused, so an address
    can never carry markup into a renderer; every other kind of address (`javascript:`, `file:`, `data:`, a relative
    path) is refused.

    The message never repeats the address.
    """
    if not href or len(href) > MAX_LINK_CHARS:
        return "A link address must be between 1 and 2000 characters."
    if _LINK_BAD.search(href):
        return "A link address cannot hold spaces, control characters, quotes, angle brackets or backslashes."
    if href.startswith("#"):
        return None if _ANCHOR.match(href[1:]) else "A link to a section must name a heading."
    parts = urlsplit(href)
    scheme = parts.scheme.lower()
    if scheme in ("http", "https"):
        return None if parts.hostname else "A web link needs a host name."
    if scheme == "mailto":
        return None if _MAILTO.match(parts.path) else "An email link needs one email address."
    return "Only web (http, https), email (mailto) and section (#) links are allowed."


def heading_anchor(text: str) -> str:
    """The anchor name of a heading's words: lower case, letters and digits kept, every other run a single hyphen.

    `"Scope & Goals (2026)"` gives `"scope-goals-2026"`. Empty text gives `"section"`. `finalize_links` makes the names
    in one document unique by adding `-2`, `-3` to repeats.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    slug = re.sub(r"[^\w]+|_+", "-", folded).strip("-")
    return slug or "section"


# The fixed allow-list of `{{name}}` placeholders content may use. Not a
# template engine: a name is replaced by plain string substitution and anything
# else (unknown names, other braces) stays literal text.
PLACEHOLDER_NAMES: tuple[str, ...] = (
    "project_name", "project_report_name", "project_code", "project_description", "report_title", "generated_on", "organisation",
    "layout_version",
)
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
#: `{{name}}` (a global placeholder) or `{{alias.field}}` / `{{var.name}}`: every reference a layout's text, a record-image
#: name pattern and a file name template can hold. The name part may hold hyphens (a block's name does); a field never does.
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_-]*)(?:\.([a-z][a-z0-9_]*))?\s*\}\}")


def project_report_label(project: object | None, fallback: str) -> str:
    """What `{{project_report_name}}` prints: the project's Project report name when set, else `fallback` (the label
    `{{project_name}}` prints, so a run over several projects or an organisation reads the same for both).

    Args:
        project: The project the report is about, or None for an organisation-wide scope.
        fallback: The scope label `{{project_name}}` prints.

    Returns:
        The short name, or `fallback`.
    """
    return (getattr(project, "report_name", None) or "") or fallback


def fill_placeholders(text: str, placeholders: Mapping[str, str] | None) -> str:
    """Replaces allow-listed `{{name}}` placeholders in `text` in a single pass.

    Args:
        text: Author-written text.
        placeholders: Values by name; names outside `PLACEHOLDER_NAMES` are
            never substituted even if present.

    Returns:
        The text with known placeholders replaced. A substituted value is not
        re-scanned, so a value containing `{{...}}` stays literal.
    """
    if not placeholders or "{{" not in text:
        return text
    return _PLACEHOLDER.sub(
        lambda m: placeholders[m.group(1)] if m.group(1) in PLACEHOLDER_NAMES and m.group(1) in placeholders else m.group(0),
        text,
    )


@dataclass(frozen=True)
class Heading:
    """A section heading. `level` is 1 (chapter) to 4; deeper levels clamp to 4.

    Attributes:
        text: The heading's words.
        level: 1 to 4.
        anchor: The name an in-document link points at (see `heading_anchor`); set by `finalize_links` just before a
            document is rendered, `None` before.
        font: The family this heading alone is set in, `None` for the document's heading font.
        size: This heading's size in points, replacing its level's size; `None` for the level's own.
        colour: This heading's colour as `#rrggbb`; `None` for the document's heading colour.
    """

    text: str
    level: int = 1
    anchor: str | None = None
    font: FontFamily | None = None
    size: float | None = None
    colour: str | None = None


@dataclass(frozen=True)
class Paragraph:
    """A body paragraph of plain text.

    Attributes:
        text: The words (a `MathText` when it holds styles or equations).
        font: The family this paragraph alone is set in, `None` for the document's body font.
        size: This paragraph's size in points, `None` for the document's body size.
    """

    text: str
    font: FontFamily | None = None
    size: float | None = None


@dataclass(frozen=True)
class Equation:
    """An equation as TeX source (see `services.report_math` for what is accepted).

    Attributes:
        tex: The TeX, without delimiters.
        display: `True` for a block of its own (centred, larger), `False` when it sits inside a `MathText`.
    """

    tex: str
    display: bool = True

    @property
    def text(self) -> str:
        """The equation as the author wrote it, with its delimiters (what a text-only consumer shows)."""
        return f"$${self.tex}$$" if self.display else f"\\({self.tex}\\)"


@dataclass(frozen=True)
class Styled:
    """A run of text in bold, italic and/or code (a `` `span` ``) and/or a link, inside a `MathText`.

    Attributes:
        text: The words, without the Markdown markers.
        bold / italic / code: The styles.
        href: Where the run links to: an absolute `http`, `https` or `mailto` address, or `#anchor` for a heading of
            the same document (`link_problem` says what is allowed). At least one style or a link is set (plain text
            is a bare `str`).
    """

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: str | None = None


class MathText(str):
    """Text that holds equations or styled runs: a `str` whose value is the words (equations in their delimiters,
    styled runs without their markers), carrying the same text as `parts` for a renderer that can draw them.

    It is used wherever the model holds text (a heading, a paragraph, a list item, a table cell), so every consumer
    that only reads strings (CSV, the on-screen result, text-only exports) shows the words unchanged and only a
    renderer that asks `text_runs` draws the equations and styles.

    Attributes:
        parts: Plain text runs (`str`), `Styled` runs and inline `Equation`s (`display` false), in reading order.
    """

    parts: tuple[str | Equation | Styled, ...]

    def __new__(cls, parts: Sequence[str | Equation | Styled]) -> MathText:
        instance = super().__new__(cls, "".join(part if isinstance(part, str) else part.text for part in parts))
        instance.parts = tuple(parts)
        return instance


def text_runs(value: str) -> tuple[str | Equation | Styled, ...]:
    """The runs of a piece of model text: the parts of a `MathText`, else the string itself."""
    return value.parts if isinstance(value, MathText) else (value,)


@dataclass(frozen=True)
class Note:
    """Small, muted explanatory text (scope line, caveats, a section's note)."""

    text: str


@dataclass(frozen=True)
class BulletList:
    """A bulleted list of items (plain text, or `MathText` with styles and equations).

    `font` and `size` are as on `Paragraph`: set for this list alone, `None` for the document's body.
    """

    items: list[str]
    font: FontFamily | None = None
    size: float | None = None


@dataclass(frozen=True)
class NumberedList:
    """A numbered list of items (plain text, or `MathText` with styles and equations); numbering starts at 1.

    `font` and `size` are as on `Paragraph`.
    """

    items: list[str]
    font: FontFamily | None = None
    size: float | None = None


@dataclass(frozen=True)
class Image:
    """An image: raster bytes already resolved (`data`), or vector markup (`svg`).

    A renderer that cannot decode it skips it: a bad image never breaks report generation.

    Attributes:
        data: Raster image bytes (tenant-checked by `report_document.resolve_report_images` or, for a layout's image
            block, `report_images.load_image`, which also strips their metadata); empty for an SVG.
        svg: SVG markup for a vector figure (a diagram, an equation). It is untrusted until
            `report_svg.sanitize_svg` has allow-listed it, which every renderer does itself, so a module
            can hand over its markup without importing an engine. PDF and HTML keep it vector, Word gets a PNG.
        alt: Text alternative (HTML `alt`); not printed. Empty for a decorative image.
        decorative: A picture that adds no information: HTML marks it `alt=""` and hidden from assistive technology.
        width: The width to print it at, in `width_unit`; `None` for its own size, never wider than the text.
        width_unit: `cm`, or `percent` of the usable text width.
        height_cm: An exact height; `None` keeps the picture's shape.
        align: `left`, `center` or `right` across the text width.
        caption: The line printed with it (`"Figure 2: ..."` once numbered); empty for none.
        caption_above: Whether the caption is printed above the picture instead of below.
        placement: `inline` (on a line of its own), `wrap` (text of the blocks that follow runs beside it, on the side
            `align` names), `behind` or `front` (laid over the page, under or over the text, at an offset).
        anchor: What a `behind` or `front` picture is measured from: `paragraph` (where the block sits in the flow), `margin`
            (the corner of the text area of its page) or `page` (the corner of the sheet).
        offset_x_cm: Distance right of the anchor's corner (a layered picture), negative for left.
        offset_y_cm: Distance below the anchor's corner (a layered picture), negative for above.
    """

    data: bytes = b""
    svg: str | None = None
    alt: str = ""
    decorative: bool = False
    width: float | None = None
    width_unit: str = "cm"
    height_cm: float | None = None
    align: str = "center"
    caption: str = ""
    caption_above: bool = False
    placement: str = "inline"
    anchor: str = "paragraph"
    offset_x_cm: float = 0.0
    offset_y_cm: float = 0.0

    @property
    def floats(self) -> bool:
        """Whether the picture takes no line of its own: it sits beside the text or over the page."""
        return self.placement in ("wrap", "behind", "front")


def _markdown_image(data: bytes) -> Image:
    """An `Image` for resolved bytes of a Markdown picture: vector markup for an SVG (each renderer sanitises it), else raster."""
    head = data.lstrip()[:200]
    if head.startswith((b"<svg", b"<?xml")) and b"<svg" in head + data[:2000]:
        try:
            return Image(svg=data.decode("utf-8"))
        except UnicodeDecodeError:
            return Image(data=data)
    return Image(data=data)


#: How the pictures of one table cell are laid out.
CELL_ARRANGEMENTS = ("stacked", "side_by_side")


@dataclass(frozen=True)
class ImageCell:
    """A table cell that holds pictures (the files attached to a row's record).

    A renderer draws each picture at the size its `Image` asks for, measured against the width of the cell (so `width` in
    `percent` is a share of the column, which survives a change of page size or column widths). Where pictures cannot be
    drawn, `text` (the file names) stands in; it is also what `str()` gives, so code that only reads text keeps working.

    Attributes:
        images: The pictures in order. Their `width` / `width_unit` / `height_cm` are the column's size rule.
        arrange: `stacked` (one under another) or `side_by_side` (left to right, wrapping inside the cell).
        text: The pictures' file names, comma separated; empty when there are none.
    """

    images: list[Image]
    arrange: str = "stacked"
    text: str = ""

    def __str__(self) -> str:
        return self.text


#: What a table cell holds: text, or the pictures of an image column.
Cell = str | ImageCell


@dataclass(frozen=True)
class Table:
    """A table with a repeating header row.

    Attributes:
        columns: Header cells.
        rows: Body rows of cells: plain text, or an `ImageCell` in an image column.
        col_widths_cm: Column widths in centimetres, or `None` for equal
            widths across the page. The PDF uses them as given; the DOCX
            scales them to the page's usable width.
        compact: `True` for the light-grid, zebra-striped, small-text style
            module reports use; `False` for the requirement report's heavier
            grid.
        tones: Optional tone per body cell, shaped like `rows` (`None` = no
            tone; a name outside `TONE_FILL` is ignored by the renderers).
        weights: Relative column widths for a table that gave no `col_widths_cm`, one per column (a table with an image
            column gives it a larger share than an id); `None` for the renderer's own sizing.
        repeat_header: Whether the header row is printed again at the top of every page the table runs onto.
        widths: The author's forced width per column (`30%`, `4 cm`, `40 mm`, or `None` for auto), or `None` when no column
            has one. Takes precedence over `col_widths_cm` and `weights`: every renderer then lays the table out with
            fixed columns (`services.report_column_width.resolve_table_widths_cm`).
        aligned: Whether `weights` were set by the alignment rule (`services.report_table_alignment`), which may recompute them.
        usual_widths: The usual width per column a module report declared (`ReportDefinition.usual_widths`; `None` for a column
            with none), or `None` when it declared none. Unlike `widths` it is a starting point: the alignment rule fixes those
            columns at the width and sizes the rest by content, and nothing happens when the layout turns the rule off.
    """

    columns: list[str]
    rows: Sequence[Sequence[Cell]]
    col_widths_cm: list[float] | None = None
    compact: bool = False
    tones: list[list[str | None]] | None = None
    weights: list[float] | None = None
    repeat_header: bool = True
    widths: list[str | None] | None = None
    aligned: bool = False
    usual_widths: list[str | None] | None = None

    def relative_widths(self, usable_cm: float) -> list[float]:
        """The column widths a word-processor renderer scales to the page: the forced widths resolved against `usable_cm`,
        else `col_widths_cm`, else `weights`, else equal."""
        if self.widths:
            return resolve_table_widths_cm(self.widths, usable_cm, self.weights)
        return self.col_widths_cm or self.weights or [1.0] * len(self.columns)

    def tone_at(self, row: int, column: int) -> str | None:
        """The known tone of a body cell, or `None` (no tones, out of range, or an unknown name)."""
        if not self.tones or row >= len(self.tones) or column >= len(self.tones[row]):
            return None
        tone = self.tones[row][column]
        return tone if tone in TONE_FILL else None


@dataclass(frozen=True)
class GridCell:
    """One cell of a `Grid`, with its style already resolved (the cascade and colour words are the evaluator's job).

    Attributes:
        paragraphs: The cell's text, one entry per paragraph (plain text, or `MathText` with styles and equations); a blank
            cell holds one empty paragraph.
        colspan / rowspan: How many columns and rows the cell covers; the covered positions are not listed in their rows.
        align: `left`, `center`, `right` or `justify`.
        valign: `top`, `middle` or `bottom`.
        fill: Background as `#rrggbb`, or `None` for none.
        color: Text colour as `#rrggbb`, or `None` for the default.
        bold: Whether the text is bold.
        font: The family its column or grid sets, or `None` for the document's.
        size: The size in points its column or grid sets, or `None` for the table's own 9 pt.
    """

    paragraphs: tuple[str, ...] = ("",)
    colspan: int = 1
    rowspan: int = 1
    align: str = "left"
    valign: str = "top"
    fill: str | None = None
    color: str | None = None
    bold: bool = False
    font: FontFamily | None = None
    size: float | None = None


@dataclass(frozen=True)
class GridRow:
    """A row of a `Grid`: its cells left to right (positions covered from above are left out) and a minimum height in cm."""

    cells: list[GridCell]
    height_cm: float | None = None


@dataclass(frozen=True)
class Grid:
    """An author-written table, as opposed to a `Table`, whose rows are records.

    Attributes:
        widths: One forced width per column (`30%`, `4 cm`, `40 mm`, or `None` for automatic), resolved like a table's.
        rows: The rows.
        header_rows: How many leading rows form the header.
        repeat_header: Whether the header rows are printed again at the top of each page the grid runs onto.
        borders: `all`, `outer`, `horizontal` or `none`.
        border_color: Border colour as `#rrggbb`.
    """

    widths: list[str | None]
    rows: list[GridRow]
    header_rows: int = 0
    repeat_header: bool = True
    borders: str = "all"
    border_color: str = "#999999"


@dataclass(frozen=True)
class Gap:
    """Vertical whitespace of `cm` centimetres (a PDF layout hint)."""

    cm: float


@dataclass(frozen=True)
class VerticalSpace:
    """An author's vertical space of `cm` centimetres, kept in every format (unlike `Gap`, a PDF-only layout hint).

    Attributes:
        cm: The height, already clamped by the layout validation.
    """

    cm: float


@dataclass(frozen=True)
class BottomStart:
    """Opens a run of blocks (closed by `BottomEnd`) that a renderer places at the foot of the page they land on.

    The blocks between the two are ordinary blocks, but never a page break, page style change or another start.
    """


@dataclass(frozen=True)
class BottomEnd:
    """Closes the run of blocks a `BottomStart` opened."""


@dataclass(frozen=True)
class PageBreak:
    """Starts a new page."""


@dataclass(frozen=True)
class PageStyleChange:
    """Starts a new page in `style`; the pages that follow use it until the next change.

    The layout's section block makes two: one into the section's style and one back to the document's own style
    after the section's content.

    Attributes:
        style: The style the pages that follow use.
        section_start: Whether this opens a section (its first page may show a different header and footer), as
            opposed to the return to the document's own style, which continues the document.
    """

    style: PageStyle
    section_start: bool = True


Block = (
    Heading | Paragraph | Equation | Note | BulletList | NumberedList | Image | Table | Grid | Gap | VerticalSpace | BottomStart | BottomEnd
    | PageBreak | PageStyleChange
)


#: Most rows a sheet can hold in Excel and OpenDocument spreadsheets (a link past it cannot be made).
MAX_SHEET_ROWS = 1_048_576
#: Whole numbers a spreadsheet keeps exactly (Excel holds 15 significant digits); a larger one stays text.
MAX_EXACT_INTEGER = 10**15


@dataclass(frozen=True)
class CellLink:
    """Where a linked spreadsheet cell opens: a row of another sheet of the same workbook.

    The sheet is held by position, not name, because a renderer cleans and de-duplicates the tab names when it writes
    them (`report_render.unique_names`) and must write the name the tab really got.

    Attributes:
        sheet: Index of the target sheet in the workbook's `sheets` list.
        row: The target row, counting the header row as 1.
    """

    sheet: int
    row: int


@dataclass(frozen=True)
class DataCell:
    """A spreadsheet cell that holds a real number, date or instant instead of text.

    A spreadsheet can only sort, sum or filter such a value when it is stored typed. `text` is how the same value reads
    as text (what CSV, the designer preview and `str()` give), so a consumer that only reads text is unaffected.
    `typed_cell` is the one way to make one, and it is the only place that decides a value is safe to type.

    Attributes:
        text: The value as printed text, always derived from `value`, never from user text.
        value: An `int`, `float` or `Decimal` (finite, within `MAX_EXACT_INTEGER`), a `date` (a calendar date), or a
            timezone-naive `datetime` that is in UTC (a past instant; a spreadsheet has no timezone).
        link: Where the cell opens when it is clicked, else `None`.
    """

    text: str
    value: int | float | Decimal | date | datetime
    link: CellLink | None = None

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class LinkedText:
    """A text spreadsheet cell that opens a row of another sheet when it is clicked.

    Attributes:
        text: The cell's text (guarded against formulas by the renderer, as any text cell).
        link: Where it opens.
    """

    text: str
    link: CellLink

    def __str__(self) -> str:
        return self.text


#: What a sheet cell holds: text (formula-guarded by the renderer), a typed value, or text that links to another sheet.
SheetCell = str | DataCell | LinkedText


def linked(cell: SheetCell, link: CellLink) -> SheetCell:
    """`cell` with `link` added; the cell's own text and type are kept."""
    return replace(cell, link=link) if isinstance(cell, DataCell | LinkedText) else LinkedText(cell, link)


#: Name of the contents sheet a table layout can start with.
CONTENTS_SHEET_NAME = "Contents"


def contents_sheet(sheets: Sequence[Sheet]) -> Sheet:
    """The contents sheet for `sheets` (which will follow it, so tab `i` of `sheets` is tab `i + 1` of the workbook).

    Returns:
        A sheet of one row per sheet: its name, as a link to the sheet's heading row, and how many rows it holds.
    """
    rows: list[list[SheetCell]] = [
        [LinkedText(sheet.name, CellLink(i + 1, 1)), DataCell(str(len(sheet.rows)), len(sheet.rows))]
        for i, sheet in enumerate(sheets)
    ]
    return Sheet(CONTENTS_SHEET_NAME, ["Sheet", "Rows"], rows, contents=True)


def typed_cell(text: str, value: object) -> SheetCell:
    """`value` as a typed sheet cell, or `text` itself when the value cannot be held exactly.

    Args:
        text: The value as printed text (also the fallback).
        value: The loaded field value: a number, a `date`, an aware or naive-UTC `datetime`, or anything else.

    Returns:
        A `DataCell` for a finite number inside `MAX_EXACT_INTEGER`, a date, or an instant (converted to naive UTC);
        otherwise `text`. A boolean is never a number here: it reads `Yes` or `No`.
    """
    if not text or isinstance(value, bool):
        return text
    if isinstance(value, int):
        return DataCell(text, value) if abs(value) < MAX_EXACT_INTEGER else text
    if isinstance(value, float):
        return DataCell(text, value) if math.isfinite(value) and abs(value) < MAX_EXACT_INTEGER else text
    if isinstance(value, Decimal):
        return DataCell(text, value) if value.is_finite() and abs(value) < MAX_EXACT_INTEGER else text
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return DataCell(text, value)
        return DataCell(text, value.astimezone(UTC).replace(tzinfo=None))
    if isinstance(value, date):
        return DataCell(text, value)
    return text


@dataclass(frozen=True)
class Sheet:
    """One named table of a table-family report.

    Attributes:
        name: Sheet (tab) name, at most 31 characters.
        columns: Header cells.
        rows: Body rows of cells: text (a spreadsheet renderer guards formula injection), a typed `DataCell`, or a
            `LinkedText`.
        contents: Whether this is the workbook's generated contents sheet (a fan-out run rebuilds it rather than merging it).
        widths_cm: The forced width of each column in cm (`None` = sized from its content), or `None` when no column has one.
            A spreadsheet renderer uses it; CSV ignores it.
    """

    name: str
    columns: list[str]
    rows: Sequence[Sequence[SheetCell]]
    contents: bool = False
    widths_cm: list[float | None] | None = None


#: Page sizes a document can ask for, as (short side, long side) in cm.
PAGE_SIZES_CM: dict[str, tuple[float, float]] = {
    "A3": (29.7, 42.0), "A4": (21.0, 29.7), "A5": (14.8, 21.0), "Letter": (21.59, 27.94), "Legal": (21.59, 35.56),
}
DEFAULT_PAGE_SIZE = "A4"
#: The margin on every side of a page that names none, in cm.
DEFAULT_MARGIN_CM = 1.5


@dataclass(frozen=True)
class Margins:
    """The white space round a page's text, in cm.

    Attributes:
        top: Above the text.
        bottom: Below the text.
        left: Left of the text; the inner edge (the binding side) when the document mirrors its margins.
        right: Right of the text; the outer edge when the document mirrors its margins.
        gutter: Extra space on the binding edge (the left, or the inner edge when mirrored) for a punched or bound copy.
    """

    top: float = DEFAULT_MARGIN_CM
    bottom: float = DEFAULT_MARGIN_CM
    left: float = DEFAULT_MARGIN_CM
    right: float = DEFAULT_MARGIN_CM
    gutter: float = 0.0


class PageField(Enum):
    """A number the page fills in itself: the current page, or the number of pages in the whole document."""

    PAGE = "page"
    PAGES = "pages"


@dataclass(frozen=True)
class Marked:
    """A stretch of a running cell set in bold and/or italic (`**bold**`, `*italic*`).

    Attributes:
        part: The words, or a page field printed in the marks.
        bold: Whether it is bold.
        italic: Whether it is italic.
    """

    part: str | PageField
    bold: bool = False
    italic: bool = False


#: A running slot is text, page fields and marked stretches in order; the text may hold line breaks (`\n`).
SlotPart = str | PageField | Marked
SLOT_NAMES = ("left", "centre", "right")
#: The vertical places a band cell's content can sit in the band's row; a band that says nothing uses the first.
VALIGN_CHOICES = ("top", "middle", "bottom")


@dataclass(frozen=True)
class RunningBand:
    """A header or a footer: an invisible three-column table (left, centre and right) in the page margin.

    Attributes:
        left: The left cell's text and page fields (left-aligned).
        centre: The middle cell's (centred).
        right: The right cell's (right-aligned).
        logo: An image shown at the start of one cell, `None` for none.
        logo_slot: The cell the logo is in: `left`, `centre` or `right`.
        logo_height_cm: The logo's height; its width keeps its shape.
        first_page: Whether the first page of the document (or of a section) shows the band; `False` for a cover
            page with no header.
        font: The band's font family, `None` to follow the document's body font.
        size: The band's text size in points, `None` for the default (8 pt).
        colour: The band's text colour as `#rrggbb`, `None` for the default (black).
        widths: Each cell's fixed width (`25%` of the band, or `4 cm`) in `SLOT_NAMES` order, `None` for a cell that sizes to
            its content.
        valigns: Each cell's own vertical alignment in `SLOT_NAMES` order, `None` to follow `valign`.
        valign: The vertical alignment of the cells that set none (one of `VALIGN_CHOICES`).
    """

    left: tuple[SlotPart, ...] = ()
    centre: tuple[SlotPart, ...] = ()
    right: tuple[SlotPart, ...] = ()
    logo: Image | None = None
    logo_slot: str = "left"
    logo_height_cm: float = 1.0
    first_page: bool = True
    font: FontFamily | None = None
    size: float | None = None
    colour: str | None = None
    widths: tuple[str | None, str | None, str | None] = (None, None, None)
    valigns: tuple[str | None, str | None, str | None] = (None, None, None)
    valign: str = VALIGN_CHOICES[0]

    def slot(self, name: str) -> tuple[SlotPart, ...]:
        """The parts of cell `name` (`left`, `centre` or `right`)."""
        return getattr(self, name)

    @property
    def empty(self) -> bool:
        """Whether the band prints nothing."""
        return not (self.left or self.centre or self.right or self.logo)

    def mirrored(self) -> RunningBand:
        """The band for a left-hand page of a double-sided document: the left and right cells (and a logo in one of
        them, and their widths and alignments) swap, so what sits at the outer edge of a right-hand page sits at the outer
        edge of the left-hand one."""
        swap = {"left": "right", "right": "left", "centre": "centre"}
        return replace(
            self, left=self.right, right=self.left, logo_slot=swap[self.logo_slot],
            widths=(self.widths[2], self.widths[1], self.widths[0]), valigns=(self.valigns[2], self.valigns[1], self.valigns[0]),
        )


@dataclass(frozen=True)
class PageStyle:
    """How a page looks: its paper, direction and margins.

    Attributes:
        page_size: One of `PAGE_SIZES_CM`.
        landscape: Whether the page is turned on its side.
        margins: The margins.
        mirror: Whether left and right swap on every second page (double-sided printing): `left` and the gutter are
            then the inner edge of every page and `right` the outer.
        header: The running header printed in the top margin, or `None` for none.
        footer: The running footer printed in the bottom margin, or `None` for the renderer's plain footer.
    """

    page_size: str = DEFAULT_PAGE_SIZE
    landscape: bool = False
    margins: Margins = field(default_factory=Margins)
    mirror: bool = False
    header: RunningBand | None = None
    footer: RunningBand | None = None

    @property
    def dimensions_cm(self) -> tuple[float, float]:
        """The page's (width, height) in cm, turned on its side for landscape; A4 for an unknown size."""
        short, long = PAGE_SIZES_CM.get(self.page_size, PAGE_SIZES_CM[DEFAULT_PAGE_SIZE])
        return (long, short) if self.landscape else (short, long)

    @property
    def usable_width_cm(self) -> float:
        """The width between the margins (less the gutter), in cm."""
        return self.dimensions_cm[0] - self.margins.left - self.margins.right - self.margins.gutter

    @property
    def usable_height_cm(self) -> float:
        """The height between the margins, in cm."""
        return self.dimensions_cm[1] - self.margins.top - self.margins.bottom

    def edges_cm(self, *, verso: bool = False) -> tuple[float, float]:
        """The (left, right) white space of a page in cm, the gutter included.

        Args:
            verso: Whether this is a left-hand page of a double-sided document (every second page when mirrored).

        Returns:
            Left then right. Not mirrored, the gutter is on the left of every page; mirrored it is on the inner edge,
            which is the right of a verso page.
        """
        inner, outer = self.margins.left + self.margins.gutter, self.margins.right
        return (outer, inner) if self.mirror and verso else (inner, outer)


@dataclass(frozen=True)
class DocumentStyles:
    """The fonts and colour a layout sets once for the whole document (`report_styles.resolve_styles` builds it).

    Every field is optional; an unset one leaves that format's own look exactly as it was.

    Attributes:
        body_font: The family text, lists, tables, notes and the running bands are set in.
        body_size: The body size in points; headings, which scale with it, and text and lists follow it.
        heading_font: The family headings and the title are set in; the body family when unset.
        heading_bold: `False` to turn the heading weight off; `None` leaves headings bold.
        heading_italic: Whether headings are italic.
        heading_colour: The heading colour as `#rrggbb`.
        embed_fonts: Whether Word and OpenDocument files carry the files of the administrator-provided families used.
    """

    body_font: FontFamily | None = None
    body_size: float | None = None
    heading_font: FontFamily | None = None
    heading_bold: bool | None = None
    heading_italic: bool = False
    heading_colour: str | None = None
    embed_fonts: bool = False

    @property
    def text_font(self) -> FontFamily | None:
        """The family the headings are set in: their own, else the body's."""
        return self.heading_font or self.body_font

    @property
    def families(self) -> list[FontFamily]:
        """The families named, body first, without repeats."""
        found = [f for f in (self.body_font, self.heading_font) if f is not None]
        return [f for i, f in enumerate(found) if f.key not in {g.key for g in found[:i]}]

    @property
    def is_default(self) -> bool:
        """Whether nothing is set, so every renderer keeps its own look."""
        return self == DocumentStyles()


@dataclass
class ReportDocument:
    """A complete report, ready for any renderer.

    Attributes:
        title: The report title (cover page or title line, and file metadata).
        blocks: The body, in order.
        branding: Optional organisation template styling (accent colour, cover
            page, logo, footer); `None` renders the plain default.
        landscape: Whether pages are landscape (wide module tables) rather
            than portrait (the requirement report).
        page_size: One of `PAGE_SIZES_CM` (A4 unless a layout chooses another).
        margins: The margins of the document's own pages (a section's `PageStyleChange` brings its own).
        mirror: Whether margins mirror on facing pages, for every page style of the document.
        header: The running header of the document's own pages (`None`: a plain report, which prints none).
        footer: The running footer of the document's own pages (`None`: the branding's footer text and page number
            as before; a layout's document always has one).
        styles: The document's fonts and heading colour (nothing set: each format's own look).
        show_title: Whether the renderer prints `title` itself (a cover page or a title line). A custom layout's document
            sets this off: it prints a title only through a block of its own, and `title` stays the file's metadata.
        align_tables: Whether tables with the same headings are given one set of column widths (the layout's
            `align_tables` setting; `services.report_table_alignment`).
    """

    title: str
    blocks: list[Block] = field(default_factory=list)
    branding: ReportBranding | None = None
    landscape: bool = False
    page_size: str = DEFAULT_PAGE_SIZE
    margins: Margins = field(default_factory=Margins)
    mirror: bool = False
    header: RunningBand | None = None
    footer: RunningBand | None = None
    styles: DocumentStyles = field(default_factory=DocumentStyles)
    show_title: bool = True
    align_tables: bool = True

    @property
    def style(self) -> PageStyle:
        """The page style of the document's own pages."""
        return PageStyle(self.page_size, self.landscape, self.margins, self.mirror, self.header, self.footer)


def page_dimensions_cm(document: ReportDocument) -> tuple[float, float]:
    """The page's (width, height) in cm, turned on its side for a landscape document; A4 for an unknown size."""
    return document.style.dimensions_cm


_ESCAPED = re.compile(r"\\([*_`\\\[\]])")


def _set_aside(text: str) -> tuple[str, list[str]]:
    """Replaces each equation (`\\( \\)` or `$$ $$`) and each escaped marker (`\\*`, `\\_`, `` \\` ``, `\\[`, `\\]`, `\\\\`) with a
    marker, so the Markdown reader never sees what is inside an equation or takes an escaped character for syntax.

    Returns:
        The text with markers, and what each stood for as it should be printed (put back with `_MATH_MARK`): an
        equation as written, an escaped character as the bare character.
    """
    from app.services.report_math import split_math  # noqa: PLC0415 - report_math is heavy; only needed here

    text = text.replace("\ue000", "").replace("\ue001", "")
    kept: list[str] = []
    written: list[str] = []

    def keep_text(value: str) -> None:
        def mark(match: re.Match[str]) -> str:
            written.append(match.group(1))
            return f"\ue000{len(written) - 1}\ue001"

        kept.append(_ESCAPED.sub(mark, value))

    for segment in split_math(text):
        if segment.kind == "text":
            keep_text(segment.value)
        else:
            written.append(f"\\({segment.value}\\)" if segment.kind == "inline" else f"$${segment.value}$$")
            kept.append(f"\ue000{len(written) - 1}\ue001")
    return "".join(kept), written


def _inline_parts(
    token, written: list[str], placeholders: Mapping[str, str] | None,
) -> list[str | Styled]:
    """The runs of one inline token: plain text and `Styled` runs (bold, italic, code, links), equations put back as written.

    Placeholders are filled run by run after the Markdown has been read, so a value is never parsed. A link whose
    address (once placeholders are filled, when they are filled here) is not allowed is kept as written text. An address
    that still holds a `{{placeholder}}` is kept for the layout evaluator to fill and check.
    """
    parts: list[str | Styled] = []
    bold = italic = 0

    def add(text: str, href: str | None, code: bool = False) -> None:
        text = _MATH_MARK.sub(lambda m: written[int(m.group(1))], text)
        text = fill_placeholders(text, placeholders)
        if not text:
            return
        style = (bool(bold), bool(italic), code, href)
        last = parts[-1] if parts else None
        if not any(style):
            if isinstance(last, str):
                parts[-1] = last + text
            else:
                parts.append(text)
        elif isinstance(last, Styled) and (last.bold, last.italic, last.code, last.href) == style:
            parts[-1] = Styled(last.text + text, *style)
        else:
            parts.append(Styled(text, *style))

    def walk(items: list, href: str | None) -> None:
        nonlocal bold, italic
        i = 0
        while i < len(items):
            child = items[i]
            kind = child.type
            if kind == "link_open":
                end = next((j for j in range(i + 1, len(items)) if items[j].type == "link_close"), len(items))
                raw = str(child.attrGet("href") or "")
                target = fill_placeholders(_MATH_MARK.sub(lambda m: written[int(m.group(1))], raw), placeholders)
                if "{{" in target or link_problem(target) is None:
                    walk(items[i + 1:end], target)
                else:
                    add("[", href)
                    walk(items[i + 1:end], href)
                    add(f"]({raw})", href)
                i = end
            elif kind in ("text", "text_special", "html_inline"):
                add(child.content, href)
            elif kind in ("softbreak", "hardbreak"):
                add("\n", href)
            elif kind == "code_inline":
                add(child.content, href, code=True)
            elif kind == "strong_open":
                bold += 1
            elif kind == "strong_close":
                bold -= 1
            elif kind == "em_open":
                italic += 1
            elif kind == "em_close":
                italic -= 1
            i += 1

    walk(list(token.children or []), None)
    return parts


def _rich_text(parts: list[str | Styled]) -> str:
    """Model text for runs: a plain string when nothing is styled, else a `MathText` carrying the runs."""
    if all(isinstance(part, str) for part in parts):
        return "".join(str(part) for part in parts)
    return MathText(parts)


def inline_markdown(markdown_text: str) -> str:
    """Reads the bold, italic and code marks of one line of text, with no block syntax (a heading's words).

    Equations are set aside and put back unread, as in `markdown_to_blocks`; placeholders are left in the words, for the
    evaluator to fill run by run so a value is never read for marks.

    Args:
        markdown_text: One line; a leading `#`, `-` or `1.` stays as written.

    Returns:
        A plain string when nothing is marked, else a `MathText` carrying the runs.
    """
    source, written = _set_aside(markdown_text)
    tokens = _md.parseInline(source)
    return _rich_text(_inline_parts(tokens[0], written, None)) if tokens else markdown_text


_LIST_OPEN = ("bullet_list_open", "ordered_list_open")
_LIST_CLOSE = ("bullet_list_close", "ordered_list_close")


def markdown_to_blocks(
    markdown_text: str, images: dict[str, bytes] | None = None, placeholders: Mapping[str, str] | None = None,
) -> list[Block]:
    """Converts a Markdown string into blocks.

    Covers headings, paragraphs, bullet and numbered lists, bold (`**x**`), italic (`*x*`, `_x_`) and code
    (`` `x` ``) spans, and images on their own line. Links, autolinks, raw HTML, entities and images inside a
    sentence stay as written; equations are set aside and put back unread.

    Args:
        markdown_text: The Markdown source.
        images: Maps an image reference (as in `![alt](ref)`, e.g.
            `"attachment:<uuid>"`) to already-resolved bytes. A paragraph
            holding *only* an image becomes an `Image`; a reference missing
            from `images` (unresolved, another organisation's, not an image)
            is skipped silently. An image mixed with other text is not
            supported: the paragraph keeps its literal source text.
        placeholders: Values for the `PLACEHOLDER_NAMES` placeholders. They are
            substituted into the parsed runs, never into the Markdown source, so a value is ordinary text that
            cannot introduce headings, lists, images or styles.

    Returns:
        The blocks (empty for blank input). Text with styles is a `MathText`; the rest is a plain `str`.
    """
    blocks: list[Block] = []
    if not markdown_text.strip():
        return blocks
    images = images or {}
    source, written = _set_aside(markdown_text)

    tokens = _md.parse(source)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            level = int(token.tag[1:]) if token.tag[1:].isdigit() else 3
            heading = "".join(part if isinstance(part, str) else part.text for part in _inline_parts(tokens[i + 1], written, placeholders))
            blocks.append(Heading(heading, min(level, 4)))
            i += 3
        elif token.type == "paragraph_open":
            inline = tokens[i + 1]
            picture = _IMAGE_ONLY.match(inline.content.strip())
            if picture:
                image_bytes = images.get(picture.group(1))
                if image_bytes:
                    blocks.append(_markdown_image(image_bytes))
                    blocks.append(Gap(0.2))
            else:
                blocks.append(Paragraph(_rich_text(_inline_parts(inline, written, placeholders))))
                blocks.append(Gap(0.2))
            i += 3
        elif token.type in _LIST_OPEN:
            items: list[str] = []
            depth = 0
            j = i + 1
            while j < len(tokens):
                kind = tokens[j].type
                if kind in _LIST_OPEN:
                    depth += 1
                elif kind in _LIST_CLOSE:
                    if depth == 0:
                        break
                    depth -= 1
                elif kind == "inline":
                    items.append(_rich_text(_inline_parts(tokens[j], written, placeholders)))
                j += 1
            blocks.append(BulletList(items) if token.type == "bullet_list_open" else NumberedList(items))
            i = j + 1
        else:
            i += 1
    return blocks


def _resolved_links(value: str, targets: set[str]) -> str:
    """`value` with every link that cannot be followed turned back into plain words.

    A link to a heading that does not exist, and (as a second check, for text built some other way) an address
    `link_problem` refuses, keeps its style but loses the link.
    """
    if not isinstance(value, MathText) or not any(isinstance(p, Styled) and p.href for p in value.parts):
        return value
    parts: list[str | Equation | Styled] = []
    for part in value.parts:
        if isinstance(part, Styled) and part.href:
            followable = part.href[1:] in targets if part.href.startswith("#") else link_problem(part.href) is None
            if not followable:
                part = replace(part, href=None)
                if not (part.bold or part.italic or part.code):
                    parts.append(part.text)
                    continue
        parts.append(part)
    return MathText(parts) if any(not isinstance(p, str) for p in parts) else "".join(str(p) for p in parts)


def finalize_links(document: ReportDocument) -> ReportDocument:
    """The document ready to render: each heading has its anchor and every link points somewhere real.

    Anchors come from `heading_anchor`, made unique in reading order (`overview`, `overview-2`). A link to a heading
    that is not in the document becomes plain words, so no renderer ever writes a link that goes nowhere. Every
    renderer of a `ReportDocument` calls this first, so a block built anywhere gets the same treatment.

    Returns:
        A new document; the argument is not changed.
    """
    taken: set[str] = set()
    anchored: list[Block] = []
    for block in document.blocks:
        if isinstance(block, Heading):
            base = heading_anchor(str(block.text))
            anchor, number = base, 1
            while anchor in taken:
                number += 1
                anchor = f"{base}-{number}"
            taken.add(anchor)
            block = replace(block, anchor=anchor)
        anchored.append(block)
    blocks: list[Block] = []
    for block in anchored:
        if isinstance(block, Paragraph):
            block = replace(block, text=_resolved_links(block.text, taken))
        elif isinstance(block, BulletList):
            block = replace(block, items=[_resolved_links(item, taken) for item in block.items])
        elif isinstance(block, NumberedList):
            block = replace(block, items=[_resolved_links(item, taken) for item in block.items])
        elif isinstance(block, Grid):
            block = replace(block, rows=[
                replace(row, cells=[replace(cell, paragraphs=tuple(_resolved_links(p, taken) for p in cell.paragraphs)) for cell in row.cells])
                for row in block.rows
            ])
        blocks.append(block)
    return replace(document, blocks=blocks)
