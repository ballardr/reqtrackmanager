"""
Module: services.report_markdown

The one Markdown walk that feeds every report format: Markdown text in, neutral blocks (`report_model`) out, for PDF,
Word, OpenDocument and HTML.

Responsibilities:
- Walk block tokens into `Heading`, `Paragraph`, `BulletList`, `NumberedList`, `CodeBlock`, `Quote`, `Grid` and `Image`;
  `markdown_to_blocks` is the author reader's entry, `record_markdown_blocks` the record reader's.
- Draw a `mermaid` fence through `report_diagram` within a budget, else print its source as a labelled `CodeBlock`.
- Print a record's `![alt](attachment:<file id>)` pictures as `Image` blocks through the run's resolver; one it cannot
  supply prints as its alternative text.

Design decisions:
- Two readers, one walk: the author reader keeps the narrow inline reading of a layout's own text (no autolinks,
  entities, strikethrough or reference links); the record reader is the screen's reading (`markdown_text`: CommonMark
  with tables, raw HTML as text, single line breaks kept).
- Nothing here produces markup: tokens become plain-text model objects each renderer escapes; a link is kept only when
  `report_model.link_problem` allows it.
- A value's structure is bounded (reader nesting limit, `MAX_TABLE_ROWS`, `MAX_TABLE_COLUMNS`, the diagram budget); a
  heading in a record's value is shifted below the report's heading for the record (`heading_offset`).

Dependencies: `markdown-it-py`, `report_model`, `report_diagram`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.services.markdown_text import ATTACHMENT_SCHEME
from app.services.report_diagram import DiagramBudget, DiagramError
from app.services.report_model import (
    IMAGE_ONLY,
    Block,
    BulletList,
    CodeBlock,
    Gap,
    Grid,
    GridCell,
    GridRow,
    Heading,
    Image,
    NumberedList,
    Paragraph,
    Quote,
    author_reader,
    inline_parts,
    markdown_image,
    rich_text,
    set_aside,
)

#: The reader's own nesting limit; deeper content is not read (the write-time limit is lower, see `markdown_text`).
_NESTING = 100
#: The most rows and columns of a Markdown table that are printed; the rest is dropped with a warning.
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 12
#: A table's header cells are shaded this grey.
_HEADER_FILL = "#eeeeee"

_record_reader = MarkdownIt("commonmark", {"html": False, "breaks": True, "maxNesting": _NESTING}).enable("table")

#: Supplies the picture of an attachment: `(file id)` to an `Image` (without alt or caption), or `None` when it cannot
#: be printed (the run's own rules: confidential, not a printable picture, not the record's file).
PictureResolver = Callable[[uuid.UUID], Image | None]


@dataclass
class _Walk:
    """What one walk shares: the reader's tokens, the equations set aside, and where warnings and diagrams go."""

    tokens: list[Token]
    written: list[str]
    placeholders: Mapping[str, str] | None
    images: Mapping[str, bytes]
    resolve_images: bool
    heading_offset: int
    diagrams: DiagramBudget | None
    warn: Callable[[str], None]
    pictures: PictureResolver | None = None


def _picture(walk: _Walk, inline: Token) -> list[Block] | None:
    """The blocks of a paragraph that holds only an attachment picture, or `None` when the paragraph is something else.

    Args:
        walk: The shared state (its resolver).
        inline: The paragraph's `inline` token.

    Returns:
        The `Image` (with the text's alternative text and caption) and a gap, or the alternative text as a paragraph when
        the picture cannot be printed (nothing when it has no alternative text either).
    """
    children = inline.children or []
    if len(children) != 1 or children[0].type != "image":
        return None
    token = children[0]
    source = str(token.attrGet("src") or "")
    if not source.startswith(ATTACHMENT_SCHEME):
        return None
    alt = token.content
    try:
        file_id = uuid.UUID(source[len(ATTACHMENT_SCHEME):])
    except ValueError:
        return [Paragraph(alt), Gap(0.2)] if alt else []
    image = walk.pictures(file_id) if walk.pictures is not None else None
    if image is None:
        return [Paragraph(alt), Gap(0.2)] if alt else []
    return [replace(image, alt=alt, decorative=not alt, caption=str(token.attrGet("title") or "")), Gap(0.2)]


def _close_of(tokens: list[Token], start: int) -> int:
    """The index of the token that closes the block opened at `start` (the last token when it never closes)."""
    depth = 0
    for index in range(start, len(tokens)):
        depth += tokens[index].nesting
        if depth == 0:
            return index
    return len(tokens) - 1


def _text_of(walk: _Walk, inline: Token) -> str:
    """The model text (plain, or `MathText` with styled runs) of an `inline` token."""
    return rich_text(inline_parts(inline, walk.written, walk.placeholders))


def _heading(walk: _Walk, opening: Token, inline: Token) -> Heading:
    """A heading: its words without styles, at its Markdown level shifted by `heading_offset` and clamped to 1 to 4."""
    level = int(opening.tag[1:]) if opening.tag[1:].isdigit() else 3
    words = "".join(part if isinstance(part, str) else part.text for part in inline_parts(inline, walk.written, walk.placeholders))
    return Heading(words, min(level + walk.heading_offset, 4))


def _diagram_label(source: str) -> str:
    """The kind of a diagram as its first word names it (`flowchart`, `sequenceDiagram`), for the text alternative."""
    first = source.strip().split(None, 1)[0] if source.strip() else "diagram"
    return first.removesuffix("-beta")


def _fence(walk: _Walk, token: Token) -> list[Block]:
    """A fenced or indented code block: a drawn diagram for `mermaid`, else a `CodeBlock` (and for a diagram that cannot
    be drawn, a `CodeBlock` of its source with a label and a warning)."""
    language = (token.info or "").strip().split(None, 1)[0].lower() if token.info else ""
    source = token.content.rstrip("\n")
    if language != "mermaid":
        return [CodeBlock(source, language), Gap(0.2)]
    if walk.diagrams is None:
        return [CodeBlock(source, "mermaid", "Diagram source"), Gap(0.2)]
    try:
        drawn = walk.diagrams.draw(source)
    except DiagramError as exc:
        walk.warn(f"A diagram is shown as its text. {exc}")
        return [CodeBlock(source, "mermaid", "Diagram source (the diagram could not be drawn)"), Gap(0.2)]
    alt = f"Diagram ({_diagram_label(source)})" + (f": {drawn.labels}" if drawn.labels else "")
    return [Image(svg=drawn.svg, alt=alt, raster=True, align="center"), Gap(0.2)]


def _table(walk: _Walk, start: int) -> tuple[Grid | None, int]:
    """A Markdown table as a `Grid` (header row shaded and bold, column alignment kept).

    Args:
        walk: The shared state.
        start: Index of the `table_open` token.

    Returns:
        The grid (`None` for an empty table) and the index of the `table_close` token.
    """
    tokens = walk.tokens
    end = _close_of(tokens, start)
    rows: list[GridRow] = []
    header_rows = 0
    cells: list[GridCell] = []
    in_header = False
    too_wide = False
    index = start + 1
    while index < end:
        token = tokens[index]
        if token.type == "thead_open":
            in_header = True
        elif token.type == "thead_close":
            in_header = False
        elif token.type == "tr_open":
            cells = []
        elif token.type in ("th_open", "td_open"):
            style = str(token.attrGet("style") or "")
            align = "right" if "right" in style else "center" if "center" in style else "left"
            text = _text_of(walk, tokens[index + 1]) if tokens[index + 1].type == "inline" else ""
            heading = token.type == "th_open"
            cells.append(GridCell(
                paragraphs=(text,), align=align, bold=heading, fill=_HEADER_FILL if heading else None,
            ))
            index += 2
        elif token.type == "tr_close":
            too_wide = too_wide or len(cells) > MAX_TABLE_COLUMNS
            rows.append(GridRow(cells[:MAX_TABLE_COLUMNS]))
            header_rows += 1 if in_header else 0
        index += 1
    if not rows:
        return None, end
    if len(rows) > MAX_TABLE_ROWS or too_wide:
        walk.warn(f"A table was cut to {MAX_TABLE_ROWS} rows and {MAX_TABLE_COLUMNS} columns.")
    columns = max(len(row.cells) for row in rows)
    padded = [
        GridRow(row.cells + [GridCell()] * (columns - len(row.cells)))
        for row in rows[:MAX_TABLE_ROWS]
    ]
    return Grid(widths=[None] * columns, rows=padded, header_rows=header_rows, repeat_header=True), end


def _list(walk: _Walk, start: int) -> tuple[list[Block], int]:
    """A (possibly nested) list as one list block, with a code block or table inside an item emitted after it.

    Args:
        walk: The shared state.
        start: Index of the `bullet_list_open` or `ordered_list_open` token.

    Returns:
        The blocks and the index of the list's closing token.
    """
    tokens = walk.tokens
    end = _close_of(tokens, start)
    items: list[str] = []
    levels: list[int] = []
    kinds: list[bool] = []
    after: list[Block] = []
    stack: list[bool] = []  # per open list: whether it is numbered
    index = start
    while index <= end:
        token = tokens[index]
        if token.type in ("bullet_list_open", "ordered_list_open"):
            stack.append(token.type == "ordered_list_open")
        elif token.type in ("bullet_list_close", "ordered_list_close"):
            stack.pop()
        elif token.type == "inline":
            items.append(_text_of(walk, token))
            levels.append(len(stack) - 1)
            kinds.append(stack[-1])
        elif token.type in ("fence", "code_block"):
            after.extend(_fence(walk, token))
        index += 1
    if not items:
        return after, end
    cls = NumberedList if kinds[0] else BulletList
    nested = any(levels) or any(kind != kinds[0] for kind in kinds)
    block = cls(items, levels=tuple(levels) if nested else (), ordered=tuple(kinds) if nested else ())
    return [block, *after], end


def _walk_blocks(walk: _Walk, start: int, stop: int) -> list[Block]:
    """The blocks of the tokens from `start` up to (not including) `stop`."""
    tokens = walk.tokens
    blocks: list[Block] = []
    index = start
    while index < stop:
        token = tokens[index]
        kind = token.type
        if kind == "heading_open":
            blocks.append(_heading(walk, token, tokens[index + 1]))
            index += 3
        elif kind == "paragraph_open":
            inline = tokens[index + 1]
            picture = IMAGE_ONLY.match(inline.content.strip()) if walk.resolve_images else None
            record_picture = None if walk.resolve_images else _picture(walk, inline)
            if record_picture is not None:
                blocks += record_picture
            elif picture:
                data = walk.images.get(picture.group(1))
                if data:
                    blocks += [markdown_image(data), Gap(0.2)]
            else:
                blocks += [Paragraph(_text_of(walk, inline)), Gap(0.2)]
            index += 3
        elif kind in ("bullet_list_open", "ordered_list_open"):
            produced, closing = _list(walk, index)
            blocks += produced
            index = closing + 1
        elif kind in ("fence", "code_block"):
            blocks += _fence(walk, token)
            index += 1
        elif kind == "blockquote_open":
            closing = _close_of(tokens, index)
            for inner in _walk_blocks(walk, index + 1, closing):
                blocks.append(Quote(inner.text) if isinstance(inner, Paragraph) else inner)
            index = closing + 1
        elif kind == "table_open":
            grid, closing = _table(walk, index)
            if grid is not None:
                blocks += [grid, Gap(0.2)]
            index = closing + 1
        elif kind == "hr":
            blocks.append(Gap(0.4))
            index += 1
        else:
            index += 1
    return blocks


def _blocks(
    text: str, *, reader: MarkdownIt, author: bool, images: Mapping[str, bytes], placeholders: Mapping[str, str] | None,
    heading_offset: int, diagrams: DiagramBudget | None, warn: Callable[[str], None], math: bool,
    pictures: PictureResolver | None = None,
) -> list[Block]:
    """Reads `text` and walks it; the shared body of the two entry points."""
    if not text.strip():
        return []
    if author:
        source, written = set_aside(text)
    elif math:
        source, written = set_aside(text, escapes=False)
    else:
        source, written = text, []
    tokens = reader.parse(source.replace("\r\n", "\n").replace("\r", "\n"))
    walk = _Walk(tokens, written, placeholders, images, author, heading_offset, diagrams, warn, pictures)
    return _walk_blocks(walk, 0, len(tokens))


def author_blocks(
    text: str, images: Mapping[str, bytes] | None = None, placeholders: Mapping[str, str] | None = None,
    *, diagrams: DiagramBudget | None = None, warn: Callable[[str], None] = lambda _message: None,
) -> list[Block]:
    """The blocks of text an author wrote in a layout (see `report_model.markdown_to_blocks`, which calls this).

    Args:
        text: The Markdown source.
        images: Maps an image reference to resolved bytes; a paragraph holding only such an image becomes an `Image`.
        placeholders: Values filled into the parsed runs, never into the source.
        diagrams: The run's diagram budget; `None` prints a diagram as its source.
        warn: Receives a sentence for each diagram that could not be drawn and each table that was cut.

    Returns:
        The blocks (empty for blank text).
    """
    return _blocks(
        text, reader=author_reader, author=True, images=images or {}, placeholders=placeholders, heading_offset=0,
        diagrams=diagrams, warn=warn, math=True,
    )


def record_markdown_blocks(
    text: str, *, math: bool = False, heading_offset: int = 2, diagrams: DiagramBudget | None = None,
    warn: Callable[[str], None] = lambda _message: None, pictures: PictureResolver | None = None,
) -> list[Block]:
    """The blocks of a record's Markdown field, read as the screen reads it.

    Args:
        text: The stored value.
        math: Whether the field holds equations (`\\( x \\)`, `$$ x $$`); they are kept as written for the caller to draw.
        heading_offset: Added to each heading's level, so a `#` sits below the heading the report printed for the record.
        diagrams: The run's diagram budget; `None` prints a diagram as its source.
        warn: Receives a sentence for each diagram that could not be drawn and each table that was cut.
        pictures: Supplies the pictures of the record's attachments; `None` prints each as its alternative text.

    Returns:
        The blocks (empty for blank text); links are only the ones `link_problem` allows and an image that is not an
        attachment picture stays as typed.
    """
    return _blocks(
        text, reader=_record_reader, author=False, images={}, placeholders=None, heading_offset=heading_offset,
        diagrams=diagrams, warn=warn, math=math, pictures=pictures,
    )


__all__ = ["MAX_TABLE_COLUMNS", "MAX_TABLE_ROWS", "PictureResolver", "author_blocks", "record_markdown_blocks"]
