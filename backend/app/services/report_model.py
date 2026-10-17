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

if TYPE_CHECKING:
    from app.services.report_document import ReportBranding

_md = MarkdownIt()

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
    """

    columns: list[str]
    rows: list[list[str]]
    col_widths_cm: list[float] | None = None
    compact: bool = False


@dataclass(frozen=True)
class Gap:
    """Vertical whitespace of `cm` centimetres (a PDF layout hint)."""

    cm: float


@dataclass(frozen=True)
class PageBreak:
    """Starts a new page."""


Block = Heading | Paragraph | Note | BulletList | Image | Table | Gap | PageBreak


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
