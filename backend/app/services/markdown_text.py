"""
Module: services.markdown_text

The server's view of Markdown text: the limits a stored value must meet, the plain text a list, search result or
notification shows in its place, and the Mermaid diagrams a document contains.

Responsibilities:
- Parse Markdown with the same reading the interface uses (CommonMark with tables, raw HTML read as text).
- `validate_markdown` / `markdown_limit`: refuse a value over its size, nested too deeply, with too many or too large
  diagrams, or holding a control character, so a write path rejects it with a 422 instead of storing it.
- `plain_text`: the readable text of a document (no marks, no diagram source unless asked) for list cells, search
  snippets and notifications, which never show raw Markdown.
- `mermaid_sources`: the diagram sources of a document, in order, for the report renderer.

Design decisions:
- Limits, not sanitising: the stored value is the author's Markdown source and is never rewritten. Output safety is
  the reader's job (HTML is never produced from it; the browser builds elements, a report walks tokens).
- The depth limit (50) sits below the reader's own cut-off (100 levels, past which markdown-it silently drops the
  rest of the document), so no accepted text can lose content to the reader.
- The diagram limits are the values in `frontend/src/utils/mermaidRenderConfig.json`; `tests/test_markdown_text.py`
  fails when the two differ, so the screen and the server refuse the same diagrams.
- The report engine's own inline reader (`report_model`) is a separate, narrower configuration for report cell text
  and is unchanged here.

Dependencies: `markdown-it-py`, `pydantic` (the `markdown_limit` validator).
"""

from __future__ import annotations

import re
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

DiagramMode = Literal["omit", "label", "source"]

_reader = MarkdownIt("commonmark", {"html": False, "breaks": True, "maxNesting": READER_NESTING}).enable("table")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
#: Characters that open a nested block (a quotation `>`, a list marker `-`, `*`, `+`, `1.` or `1)`). A document nested
#: `MAX_DEPTH` levels deep has at least `MAX_DEPTH // 2` of them (a list adds two levels per marker, a quotation one).
_NESTING_MARKS = re.compile(r"[>\-*+.)]")
_SPACE = re.compile(r"\s+")


class MarkdownLimitError(ValueError):
    """A Markdown value breaks a limit; the message names the limit and is safe to show a person."""


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
            parts.append(child.content)
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
