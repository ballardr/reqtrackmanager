"""
Module: services.markdown_text

The server's view of Markdown text: the limits a stored value must meet, the plain text a list, search result
or notification shows in its place, and the Mermaid diagrams a document contains.

Responsibilities: parse with the interface's reading (CommonMark with tables, raw HTML read as text);
`validate_markdown` / `markdown_limit` refuse a value over its size, nested too deeply, with too many or too
large diagrams, or holding a control character (a 422, not stored); `plain_text` gives readable text (no marks,
no diagram source unless asked); `mermaid_sources` gives diagram sources for the report renderer;
`image_references` / `check_images` read and limit pictures (`![alt](attachment:<file id>)`), whose alternative
text is what `plain_text` shows.

Design decisions:
- Limits, not sanitising: the stored value is the author's source and is never rewritten. Output safety is the
  reader's job (HTML is never produced from it).
- The depth limit (50) sits below the reader's cut-off (100 levels, past which markdown-it drops the rest), so
  no accepted text loses content.
- The diagram limits equal `frontend/src/utils/mermaidRenderConfig.json`; `tests/test_markdown_text.py` fails
  when they differ, so the screen and the server refuse the same diagrams.
- A picture is only an attachment (`attachment:` and a file id, never an outside address), so reading a record
  makes no request to another site. Whether the file belongs to the record is the write hook's check
  (`services.markdown_fields`).
- The report engine's inline reader (`report_model`) is a separate, narrower configuration for cell text.

Dependencies: `markdown-it-py`, `pydantic` (the `markdown_limit` validator).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from functools import partial
from typing import Literal

from markdown_it import MarkdownIt
from markdown_it.token import Token
from pydantic import AfterValidator

#: The reader's own nesting cut-off; deeper content is silently not read.
READER_NESTING = 100
#: The deepest nesting a stored value may have (below the reader's cut-off).
MAX_DEPTH = 50
#: Per-diagram source limit, characters (equal to the interface's `limits.sourceChars`).
MAX_MERMAID_SOURCE_CHARS = 20_000
#: Diagrams allowed in one field.
MAX_MERMAID_BLOCKS = 20

#: The address scheme of a picture that is an attachment of the record.
ATTACHMENT_SCHEME = "attachment:"
#: Pictures allowed in one field.
MAX_IMAGES = 20
#: Longest caption (the picture's title text), characters.
MAX_CAPTION_CHARS = 200

DiagramMode = Literal["omit", "label", "source"]

_reader = MarkdownIt("commonmark", {"html": False, "breaks": True, "maxNesting": READER_NESTING}).enable("table")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
#: Characters that open a nested block (a quotation `>`, a list marker `-`, `*`, `+`, `1.` or `1)`). A document nested
#: `MAX_DEPTH` levels deep has at least `MAX_DEPTH // 2` of them (a list adds two levels per marker, a quotation one).
_NESTING_MARKS = re.compile(r"[>\-*+.)]")
_SPACE = re.compile(r"\s+")


class MarkdownLimitError(ValueError):
    """A Markdown value breaks a limit; the message names the limit and is safe to show a person."""


@dataclass(frozen=True)
class ImageReference:
    """One picture of a Markdown document.

    Attributes:
        file_id: The attachment's file id.
        alt: The alternative text (may be empty).
        caption: The caption (the picture's title), may be empty.
    """

    file_id: uuid.UUID
    alt: str
    caption: str


def parse(text: str) -> list[Token]:
    """
    Reads Markdown into the reader's block tokens.

    Args:
        text: Markdown source.

    Returns:
        The token list (an `inline` token's `children` hold its inline tokens).
    """
    return _reader.parse(text.replace("\r\n", "\n").replace("\r", "\n"))


def is_mermaid_fence(token: Token) -> bool:
    """Whether `token` is a fenced block whose info string starts with `mermaid`."""
    return token.type == "fence" and token.info.strip().split(" ")[0].lower() == "mermaid"


def mermaid_sources(text: str) -> list[str]:
    """
    The diagram sources in a document.

    Args:
        text: Markdown source.

    Returns:
        The body of each `mermaid` fenced block, in document order.
    """
    return [token.content for token in parse(text) if is_mermaid_fence(token)]


def _image_tokens(text: str) -> list[Token]:
    """The `image` tokens whose address is an attachment, in document order (empty with no `attachment:` in the text)."""
    if ATTACHMENT_SCHEME not in text:
        return []
    found: list[Token] = []

    def walk(tokens: list[Token]) -> None:
        for token in tokens:
            if token.type == "image" and str(token.attrGet("src") or "").startswith(ATTACHMENT_SCHEME):
                found.append(token)
            if token.children:
                walk(token.children)

    walk(parse(text))
    return found


def image_references(text: str) -> list[ImageReference]:
    """
    The attachment pictures in a document.

    Args:
        text: Markdown source.

    Returns:
        One reference per `![alt](attachment:<file id>)` picture, in order; an address that is not a file id is left out
        (`check_images` refuses it on write).
    """
    refs: list[ImageReference] = []
    for token in _image_tokens(text):
        raw = str(token.attrGet("src"))[len(ATTACHMENT_SCHEME):]
        try:
            file_id = uuid.UUID(raw)
        except ValueError:
            continue
        if str(file_id) != raw:
            continue  # only the canonical lower-case form, so a reference can be found and rewritten as text
        refs.append(ImageReference(file_id, token.content, str(token.attrGet("title") or "")))
    return refs


def check_images(text: str, *, allowed: bool, field: str = "text") -> list[ImageReference]:
    """
    Checks the pictures of a Markdown value against the limits.

    Args:
        text: The value as submitted.
        allowed: Whether the field may hold pictures (it carries a `MarkdownImages` declaration).
        field: A name for the messages.

    Returns:
        The pictures (empty when there are none).

    Raises:
        MarkdownLimitError: When the field holds pictures and may not, has more than `MAX_IMAGES`, has a picture whose
            address is not a file id, or a caption over `MAX_CAPTION_CHARS`.
    """
    tokens = _image_tokens(text)
    if not tokens:
        return []
    if not allowed:
        raise MarkdownLimitError(f"{field} cannot hold pictures.")
    if len(tokens) > MAX_IMAGES:
        raise MarkdownLimitError(f"{field} has more than {MAX_IMAGES} pictures.")
    refs = image_references(text)
    if len(refs) != len(tokens):
        raise MarkdownLimitError(f"A picture in {field} does not name an attachment.")
    if any(len(ref.caption) > MAX_CAPTION_CHARS for ref in refs):
        raise MarkdownLimitError(f"A picture caption in {field} is over the limit of {MAX_CAPTION_CHARS} characters.")
    return refs


def validate_markdown(text: str, *, max_chars: int, field: str = "text") -> str:
    """
    Checks a Markdown value against the limits.

    Args:
        text: The value as submitted.
        max_chars: The field's size limit, in characters.
        field: A name for the messages.

    Returns:
        `text`, unchanged.

    Raises:
        MarkdownLimitError: When the value is too long, holds a control character, nests more than `MAX_DEPTH`
            levels, has more than `MAX_MERMAID_BLOCKS` diagrams or a diagram over `MAX_MERMAID_SOURCE_CHARS`.
    """
    if len(text) > max_chars:
        raise MarkdownLimitError(f"{field} is over the limit of {max_chars} characters.")
    if _CONTROL.search(text):
        raise MarkdownLimitError(f"{field} contains a control character.")
    if "mermaid" not in text.lower() and len(_NESTING_MARKS.findall(text)) < MAX_DEPTH // 2:
        # No diagram can be present and too few block markers exist to nest 50 levels, so the parse (the dearest
        # step, run on every write of every declared field) cannot change the answer.
        return text
    tokens = parse(text)
    if any(token.level >= MAX_DEPTH for token in tokens):
        raise MarkdownLimitError(f"{field} is nested more than {MAX_DEPTH} levels deep.")
    diagrams = [token.content for token in tokens if is_mermaid_fence(token)]
    if len(diagrams) > MAX_MERMAID_BLOCKS:
        raise MarkdownLimitError(f"{field} has more than {MAX_MERMAID_BLOCKS} diagrams.")
    if any(len(source) > MAX_MERMAID_SOURCE_CHARS for source in diagrams):
        raise MarkdownLimitError(f"A diagram in {field} is over the limit of {MAX_MERMAID_SOURCE_CHARS} characters.")
    return text


def markdown_limit(max_chars: int) -> AfterValidator:
    """
    A pydantic validator for a Markdown field: `description: Annotated[str, markdown_limit(20_000)]`.

    Args:
        max_chars: The field's size limit, in characters.

    Returns:
        The validator; a breach is a 422 response.
    """
    return AfterValidator(partial(validate_markdown, max_chars=max_chars))


def _inline_text(token: Token) -> str:
    parts: list[str] = []
    for child in token.children or []:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif child.type == "image":
            parts.append(_inline_text(child))  # the alternative text as words (`content` keeps its raw source)
    return "".join(parts)


def plain_text(text: str, *, diagrams: DiagramMode = "label", limit: int | None = None) -> str:
    """
    The readable text of a Markdown document, with no marks.

    Args:
        text: Markdown source.
        diagrams: What a `mermaid` block contributes: `omit` (nothing), `label` (the word "Diagram") or `source`
            (its text, for search).
        limit: Truncate to this many characters, ending in an ellipsis; `None` keeps everything.

    Returns:
        One line of text: blocks and table cells separated by a space, runs of white space collapsed.
    """
    parts: list[str] = []
    for token in parse(text):
        if token.type == "inline":
            parts.append(_inline_text(token))
        elif is_mermaid_fence(token):
            if diagrams == "label":
                parts.append("Diagram")
            elif diagrams == "source":
                parts.append(token.content)
        elif token.type in ("fence", "code_block"):
            parts.append(token.content)
    result = _SPACE.sub(" ", " ".join(parts)).strip()
    if limit is not None and len(result) > limit:
        return result[: max(limit - 1, 0)].rstrip() + "…"
    return result
