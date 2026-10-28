"""
Module: services.report_model

The neutral report document every renderer consumes . A report is built once, as a
`ReportDocument` of simple blocks, and then rendered by `report_pdf`
(ReportLab) and `report_docx` (python-docx), so a layout change is made in one
place rather than once per output format.

Responsibilities:
- Block types: `Heading`, `Paragraph`, `Equation` (a display equation), `Note`, `BulletList`, `Image` (raster bytes or SVG markup), `Table`,
  `Gap`, `PageBreak`, and the `ReportDocument` that holds them with the
  title, branding and page orientation.
- `Sheet`: one named table of a table-family report (CSV, XLSX, ODS); not a
  document block, so it is never inside a `ReportDocument`.
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

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

from app.services.branding import contrast_text_hex

if TYPE_CHECKING:
    from app.services.report_document import ReportBranding

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
    "project_name", "project_code", "project_description", "report_title", "generated_on", "organisation",
)
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


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
    """

    text: str
    level: int = 1
    anchor: str | None = None


@dataclass(frozen=True)
class Paragraph:
    """A body paragraph of plain text."""

    text: str


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
    """A bulleted list of items (plain text, or `MathText` with styles and equations)."""

    items: list[str]


@dataclass(frozen=True)
class NumberedList:
    """A numbered list of items (plain text, or `MathText` with styles and equations); numbering starts at 1."""

    items: list[str]


@dataclass(frozen=True)
class Image:
    """An image: raster bytes already resolved (`data`), or vector markup (`svg`).

    A renderer that cannot decode it skips it: a bad image never breaks report generation.

    Attributes:
        data: Raster image bytes (tenant-checked by `report_document.resolve_report_images`); empty for an SVG.
        svg: SVG markup for a vector figure (a diagram, an equation). It is untrusted until
            `report_svg.sanitize_svg` has allow-listed it, which every renderer does itself, so a module
            can hand over its markup without importing an engine. PDF and HTML keep it vector, Word gets a PNG.
        alt: Text alternative (HTML `aria-label`); not printed.
    """

    data: bytes = b""
    svg: str | None = None
    alt: str = ""


@dataclass(frozen=True)
class Table:
    """A table with a repeating header row.

    Attributes:
        columns: Header cells.
        rows: Body rows of plain-text cells.
        col_widths_cm: Column widths in centimetres, or `None` for equal
            widths across the page. The PDF uses them as given; the DOCX
            scales them to the page's usable width.
        compact: `True` for the light-grid, zebra-striped, small-text style
            module reports use; `False` for the requirement report's heavier
            grid.
        tones: Optional tone per body cell, shaped like `rows` (`None` = no
            tone; a name outside `TONE_FILL` is ignored by the renderers).
    """

    columns: list[str]
    rows: list[list[str]]
    col_widths_cm: list[float] | None = None
    compact: bool = False
    tones: list[list[str | None]] | None = None

    def tone_at(self, row: int, column: int) -> str | None:
        """The known tone of a body cell, or `None` (no tones, out of range, or an unknown name)."""
        if not self.tones or row >= len(self.tones) or column >= len(self.tones[row]):
            return None
        tone = self.tones[row][column]
        return tone if tone in TONE_FILL else None


@dataclass(frozen=True)
class Gap:
    """Vertical whitespace of `cm` centimetres (a PDF layout hint)."""

    cm: float


@dataclass(frozen=True)
class PageBreak:
    """Starts a new page."""


Block = Heading | Paragraph | Equation | Note | BulletList | NumberedList | Image | Table | Gap | PageBreak


@dataclass(frozen=True)
class Sheet:
    """One named table of a table-family report.

    Attributes:
        name: Sheet (tab) name, at most 31 characters.
        columns: Header cells.
        rows: Body rows of plain-text cells; a spreadsheet renderer guards formula injection.
    """

    name: str
    columns: list[str]
    rows: list[list[str]]


#: Page sizes a document can ask for, as (short side, long side) in cm.
PAGE_SIZES_CM: dict[str, tuple[float, float]] = {
    "A3": (29.7, 42.0), "A4": (21.0, 29.7), "A5": (14.8, 21.0), "Letter": (21.59, 27.94), "Legal": (21.59, 35.56),
}
DEFAULT_PAGE_SIZE = "A4"


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
    """

    title: str
    blocks: list[Block] = field(default_factory=list)
    branding: ReportBranding | None = None
    landscape: bool = False
    page_size: str = DEFAULT_PAGE_SIZE


def page_dimensions_cm(document: ReportDocument) -> tuple[float, float]:
    """The page's (width, height) in cm, turned on its side for a landscape document; A4 for an unknown size."""
    short, long = PAGE_SIZES_CM.get(document.page_size, PAGE_SIZES_CM[DEFAULT_PAGE_SIZE])
    return (long, short) if document.landscape else (short, long)


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
                    blocks.append(Image(image_bytes))
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
            block = Paragraph(_resolved_links(block.text, taken))
        elif isinstance(block, BulletList):
            block = BulletList([_resolved_links(item, taken) for item in block.items])
        elif isinstance(block, NumberedList):
            block = NumberedList([_resolved_links(item, taken) for item in block.items])
        blocks.append(block)
    return replace(document, blocks=blocks)
