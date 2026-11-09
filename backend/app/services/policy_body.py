"""
Module: services.policy_body

Validation of a policy's rich-text body.

Responsibilities:
- Accept a ProseMirror document (the shape the editor produces) limited to a fixed vocabulary of blocks and
  marks, and return a rebuilt copy holding only the allowed fields.
- Reject anything else (an unknown node, an unsafe link, an oversized or too deeply nested tree).
- Give the plain text and the length of a body for emptiness checks and audit detail.

Design decisions:
- The body is never markup. A value outside the vocabulary is rejected, not cleaned, so a stored body cannot
  carry a script, an event handler or a `javascript:` link, and the frontend renders it as React elements
  (no HTML insertion). The rebuild copies only named fields, so unknown attributes never persist.
- Links may use `https`, `http` or `mailto`; the page adds `rel="noopener noreferrer"` when it renders them.
- `allow_links=False` rejects any link mark (an organisation may choose to forbid web addresses).

Dependencies: standard library only.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, status

#: Most characters of text in one body.
MAX_TEXT_LENGTH = 100_000
MAX_NODES = 5_000
MAX_DEPTH = 8
MAX_LINK_LENGTH = 2_000
_LINK_SCHEMES = {"https", "http", "mailto"}
_BLOCKS = {"paragraph", "heading", "bulletList", "orderedList", "listItem", "blockquote", "horizontalRule", "hardBreak"}
_CONTAINERS = {"doc", "bulletList", "orderedList", "listItem", "blockquote", "paragraph", "heading"}
_MARKS = {"bold", "italic", "link"}

EMPTY_BODY: dict[str, Any] = {"type": "doc", "content": []}


def _reject(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid policy text: {message}")


class _Walk:
    """Counters shared by one validation pass."""

    def __init__(self, allow_links: bool) -> None:
        self.allow_links = allow_links
        self.nodes = 0
        self.text_length = 0


def _link_href(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_LINK_LENGTH:
        raise _reject("a link needs a web address of at most 2000 characters.")
    href = value.strip()
    try:
        scheme = urlsplit(href).scheme.lower()
    except ValueError:
        raise _reject("a link is not a valid web address.") from None
    if scheme not in _LINK_SCHEMES or any(ord(c) < 32 or ord(c) == 127 for c in href):
        raise _reject("a link must start with https://, http:// or mailto:.")
    return href


def _marks(raw: object, walk: _Walk) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _reject("marks must be a list.")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mark in raw:
        kind = mark.get("type") if isinstance(mark, dict) else None
        if kind not in _MARKS or kind in seen:
            raise _reject(f"'{kind}' is not an allowed text style.")
        seen.add(kind)
        if kind == "link":
            if not walk.allow_links:
                raise _reject("links are not allowed in this policy.")
            attrs = mark.get("attrs")
            out.append({"type": "link", "attrs": {"href": _link_href(attrs.get("href") if isinstance(attrs, dict) else None)}})
        else:
            out.append({"type": kind})
    return out


def _node(raw: object, depth: int, walk: _Walk) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _reject("a content node must be an object.")
    walk.nodes += 1
    if walk.nodes > MAX_NODES or depth > MAX_DEPTH:
        raise _reject("the text is too large or too deeply nested.")
    kind = raw.get("type")
    if kind == "text":
        text = raw.get("text")
        if not isinstance(text, str) or not text:
            raise _reject("text must be a non-empty string.")
        walk.text_length += len(text)
        if walk.text_length > MAX_TEXT_LENGTH:
            raise _reject(f"the text is longer than {MAX_TEXT_LENGTH} characters.")
        out: dict[str, Any] = {"type": "text", "text": text}
        marks = _marks(raw.get("marks"), walk)
        if marks:
            out["marks"] = marks
        return out
    if kind not in _BLOCKS:
        raise _reject(f"'{kind}' is not an allowed content type.")
    out = {"type": kind}
    attrs = raw.get("attrs")
    if kind == "heading":
        level = attrs.get("level") if isinstance(attrs, dict) else None
        if level not in (1, 2, 3) or isinstance(level, bool):
            raise _reject("a heading level must be 1, 2 or 3.")
        out["attrs"] = {"level": level}
    if kind == "orderedList":
        start = attrs.get("start", 1) if isinstance(attrs, dict) else 1
        if not isinstance(start, int) or isinstance(start, bool) or not 1 <= start <= 10_000:
            raise _reject("a list start must be a number from 1 to 10000.")
        out["attrs"] = {"start": start}
    content = raw.get("content")
    if kind in _CONTAINERS:
        if content is not None and not isinstance(content, list):
            raise _reject("content must be a list.")
        out["content"] = [_node(child, depth + 1, walk) for child in content or []]
    elif content:
        raise _reject(f"'{kind}' cannot hold content.")
    return out


def validate_body(raw: object, *, allow_links: bool = True) -> dict[str, Any]:
    """Validates a body and returns a rebuilt copy holding only allowed fields.

    Args:
        raw: The submitted document (`{"type": "doc", "content": [...]}`); `None` or `{}` means an empty body.
        allow_links: Whether link marks are accepted.

    Returns:
        The cleaned document.

    Raises:
        HTTPException: 422 when the document is outside the vocabulary or limits.
    """
    if raw is None or raw == {}:
        return {"type": "doc", "content": []}
    if not isinstance(raw, dict) or raw.get("type") != "doc":
        raise _reject("the body must be a document.")
    content = raw.get("content")
    if content is not None and not isinstance(content, list):
        raise _reject("content must be a list.")
    walk = _Walk(allow_links)
    return {"type": "doc", "content": [_node(child, 1, walk) for child in content or []]}


def plain_text(body: dict[str, Any]) -> str:
    """The text of a validated body, blocks separated by a newline (for emptiness checks and lengths)."""
    parts: list[str] = []

    def visit(node: dict[str, Any]) -> None:
        if node.get("type") == "text":
            parts.append(node.get("text", ""))
            return
        for child in node.get("content", []):
            visit(child)
        if node.get("type") in {"paragraph", "heading", "listItem", "blockquote"}:
            parts.append("\n")

    visit(body)
    return "".join(parts).strip()
