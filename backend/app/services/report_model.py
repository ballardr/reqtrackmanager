"""
Module: services.report_model

The neutral report document every renderer consumes . A report is built once, as a
`ReportDocument` of simple blocks, and then rendered by `report_pdf`
(ReportLab) and `report_docx` (python-docx), so a layout change is made in one
place rather than once per output format.

Responsibilities:
- Block types: `Heading`, `Paragraph`, `Note`, `BulletList`, `Image`, `Table`,
  `Gap`, `PageBreak`, and the `ReportDocument` that holds them with the
  title, branding and page orientation.
- `Sheet`: one named table of a table-family report (CSV, XLSX, ODS); not a
  document block, so it is never inside a `ReportDocument`.
- Cell tones: `Table.tones` marks cells the screen colours (a rating band, a
  matrix cell) and `TONE_FILL` is the one tone-to-colour table both renderers use;
  `text_on` picks black or white text for any fill by contrast.
- `markdown_to_blocks`: the restricted Markdown reader (headings, paragraphs,
  bullet lists, images on their own line) that turns author-written intro,
  chapter and appendix content into blocks.

Design decisions:
- Blocks hold plain strings and bytes only. Nothing here knows about ReportLab
  markup or Word XML, so escaping is the renderer's job, done at one choke
  point per renderer.
- Inline Markdown (bold, links) is deliberately not interpreted: a paragraph's
  text is the author's source verbatim, exactly as the PDF has always shown
  it. That keeps the two formats identical and means no hyperlink or markup
  path exists to attack; richer inline text would be a change to both
  renderers together.
- Images arrive pre-resolved as bytes (`report_document.resolve_report_images`
  does the tenant check), so this module and the renderers never fetch
  anything.
- A tone is a name (the same five as the on-screen `BadgeTone`), never a colour,
  so a collector cannot put an arbitrary value into PDF or Word XML. The text of
  a toned cell still carries its meaning (the band name), so a greyscale print
  reads the same.
- `Gap` is a vertical-whitespace hint kept so the PDF layout is exactly what it
  was before the model existed; the DOCX renderer ignores it and relies on
  paragraph spacing.

Dependencies: markdown-it-py. `ReportBranding` is imported for typing only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

from app.services.branding import contrast_text_hex

if TYPE_CHECKING:
    from app.services.report_document import ReportBranding

_md = MarkdownIt()

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

# The fixed allow-list of `{{name}}` placeholders content may use. Not a
# template engine: a name is replaced by plain string substitution and anything
# else (unknown names, other braces) stays literal text.
PLACEHOLDER_NAMES: tuple[str, ...] = ("project_name", "report_title", "generated_on", "organisation")
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
    """A section heading. `level` is 1 (chapter) to 4; deeper levels clamp to 4."""

    text: str
    level: int = 1


@dataclass(frozen=True)
class Paragraph:
    """A body paragraph of plain text."""

    text: str


@dataclass(frozen=True)
class Note:
    """Small, muted explanatory text (scope line, caveats, a section's note)."""

    text: str


@dataclass(frozen=True)
class BulletList:
    """A bulleted list of plain-text items."""

    items: list[str]


@dataclass(frozen=True)
class Image:
    """An image, already resolved to bytes. A renderer that cannot decode it
    skips it: a bad image never breaks report generation."""

    data: bytes


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


Block = Heading | Paragraph | Note | BulletList | Image | Table | Gap | PageBreak


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
    """

    title: str
    blocks: list[Block] = field(default_factory=list)
    branding: ReportBranding | None = None
    landscape: bool = False


def markdown_to_blocks(
    markdown_text: str, images: dict[str, bytes] | None = None, placeholders: Mapping[str, str] | None = None,
) -> list[Block]:
    """Converts a Markdown string into blocks.

    Covers headings, paragraphs, bullet lists and images on their own line,
    enough for introduction, chapter and appendix content.

    Args:
        markdown_text: The Markdown source.
        images: Maps an image reference (as in `![alt](ref)`, e.g.
            `"attachment:<uuid>"`) to already-resolved bytes. A paragraph
            holding *only* an image becomes an `Image`; a reference missing
            from `images` (unresolved, another organisation's, not an image)
            is skipped silently. An image mixed with other text is not
            supported: the paragraph keeps its literal source text.
        placeholders: Values for the `PLACEHOLDER_NAMES` placeholders. They are
            substituted into the parsed heading, paragraph and list text, never
            into the Markdown source, so a value is ordinary text that cannot
            introduce headings, lists or images.

    Returns:
        The blocks (empty for blank input).
    """
    blocks: list[Block] = []
    if not markdown_text.strip():
        return blocks
    images = images or {}

    tokens = _md.parse(markdown_text)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            level = int(token.tag[1:]) if token.tag[1:].isdigit() else 3
            blocks.append(Heading(fill_placeholders(tokens[i + 1].content, placeholders), min(level, 4)))
            i += 3
        elif token.type == "paragraph_open":
            inline = tokens[i + 1]
            image_children = [c for c in (inline.children or []) if c.type == "image"]
            if len(image_children) == 1 and len(inline.children) == 1:
                image_bytes = images.get(image_children[0].attrs.get("src", ""))
                if image_bytes:
                    blocks.append(Image(image_bytes))
                    blocks.append(Gap(0.2))
            else:
                blocks.append(Paragraph(fill_placeholders(inline.content, placeholders)))
                blocks.append(Gap(0.2))
            i += 3
        elif token.type == "bullet_list_open":
            items = []
            j = i + 1
            while tokens[j].type != "bullet_list_close":
                if tokens[j].type == "inline":
                    items.append(fill_placeholders(tokens[j].content, placeholders))
                j += 1
            blocks.append(BulletList(items))
            i = j + 1
        else:
            i += 1
    return blocks
