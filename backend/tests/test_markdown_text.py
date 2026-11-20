"""
Module: tests.test_markdown_text

Pins `services.markdown_text`: the size, depth and diagram limits, the plain-text extraction, the diagram finder
and its agreement with the interface's diagram limits (`mermaidRenderConfig.json`).
"""

import json
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, ValidationError

from app.services import markdown_text as md

CONFIG = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "mermaidRenderConfig.json"
PACKAGE = Path(__file__).resolve().parents[2] / "frontend" / "package.json"


def test_diagram_limit_equals_the_interface_limit() -> None:
    config = json.loads(CONFIG.read_text())
    assert md.MAX_MERMAID_SOURCE_CHARS == config["limits"]["sourceChars"]


def test_interface_diagram_version_is_the_exact_package_pin() -> None:
    config = json.loads(CONFIG.read_text())
    assert json.loads(PACKAGE.read_text())["dependencies"]["mermaid"] == config["version"]


def test_depth_limit_is_below_the_readers_cut_off() -> None:
    assert md.MAX_DEPTH < md.READER_NESTING


def test_reader_drops_content_past_its_own_cut_off() -> None:
    """The reason the depth limit exists: text nested past the reader's limit is not read at all."""
    deep = "> " * (md.READER_NESTING + 10) + "lost"
    assert "lost" not in md.plain_text(deep)


def test_valid_text_is_returned_unchanged() -> None:
    text = "# Title\r\n\r\n- one\r\n- two\r\n\r\n| a | b |\r\n| - | - |\r\n| 1 | 2 |\r\n"
    assert md.validate_markdown(text, max_chars=1000) == text


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("x" * 11, "over the limit of 10"),
        ("a\x00b", "control character"),
        ("> " * 60 + "deep", "levels deep"),
        ("```mermaid\n" + "A-->B\n" * 4000 + "```", "over the limit of 20000"),
        ("\n\n".join("```mermaid\nflowchart LR\n A-->B\n```" for _ in range(21)), "more than 20 diagrams"),
    ],
)
def test_breaches_are_refused_with_the_limit_named(text: str, fragment: str) -> None:
    max_chars = 10 if len(text) == 11 else 200_000
    with pytest.raises(md.MarkdownLimitError, match=fragment):
        md.validate_markdown(text, max_chars=max_chars)


def test_tab_and_newline_are_not_control_characters() -> None:
    assert md.validate_markdown("a\tb\nc", max_chars=10) == "a\tb\nc"


def test_pydantic_validator_gives_a_validation_error() -> None:
    class Body(BaseModel):
        note: Annotated[str, md.markdown_limit(5)]

    assert Body(note="short").note == "short"
    with pytest.raises(ValidationError, match="over the limit of 5"):
        Body(note="too long")


def test_plain_text_has_no_marks_and_keeps_words() -> None:
    text = "# Title\n\nSome **bold**, _italic_ and `code`.\n\n- one\n- two\n\n> quoted\n\n| a | b |\n| - | - |\n| 1 | 2 |"
    assert md.plain_text(text) == "Title Some bold, italic and code. one two quoted a b 1 2"


def test_plain_text_links_show_their_label_not_the_address() -> None:
    assert md.plain_text("See [the plan](https://example.com/plan) now") == "See the plan now"


def test_raw_html_is_read_as_text_not_dropped_or_run() -> None:
    assert "<script>" in md.plain_text("<script>alert(1)</script>")


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("omit", "Before After"), ("label", "Before Diagram After"), ("source", "Before flowchart LR A-->B After")],
)
def test_diagram_modes(mode: md.DiagramMode, expected: str) -> None:
    text = "Before\n\n```mermaid\nflowchart LR\n  A-->B\n```\n\nAfter"
    assert md.plain_text(text, diagrams=mode) == expected  # type: ignore[arg-type]


def test_plain_text_truncates_with_an_ellipsis() -> None:
    assert md.plain_text("abcdefghij", limit=5) == "abcd…"
    assert md.plain_text("abc", limit=5) == "abc"


def test_other_fenced_code_keeps_its_text() -> None:
    assert md.plain_text("```python\nprint(1)\n```") == "print(1)"


def test_mermaid_sources_in_order() -> None:
    text = "```mermaid\nA\n```\n\n```python\nx\n```\n\n```Mermaid extra\nB\n```"
    assert md.mermaid_sources(text) == ["A\n", "B\n"]


def test_empty_text() -> None:
    assert md.plain_text("") == ""
    assert md.mermaid_sources("") == []


def _full_check_refuses(text: str) -> bool:
    """The limits as a full parse sees them (what `validate_markdown` must agree with without parsing when it can)."""
    tokens = md.parse(text)
    diagrams = [token.content for token in tokens if md.is_mermaid_fence(token)]
    return (
        any(token.level >= md.MAX_DEPTH for token in tokens)
        or len(diagrams) > md.MAX_MERMAID_BLOCKS
        or any(len(source) > md.MAX_MERMAID_SOURCE_CHARS for source in diagrams)
    )


@pytest.mark.parametrize("depth", range(1, 60))
def test_the_parse_free_shortcut_never_disagrees_with_a_full_parse_on_nesting(depth: int) -> None:
    quotes = "> " * depth + "text"
    lists = "".join("  " * level + "- item\n" for level in range(depth))
    for text in (quotes, lists, ">" * depth + "text", "1. " * depth + "x"):
        try:
            md.validate_markdown(text, max_chars=50_000)
            refused = False
        except md.MarkdownLimitError:
            refused = True
        assert refused == _full_check_refuses(text), (depth, text[:40])


def test_the_parse_free_shortcut_still_counts_diagrams_and_sizes() -> None:
    diagram = "```mermaid\nflowchart LR\n  A --> B\n```\n"
    with pytest.raises(md.MarkdownLimitError):
        md.validate_markdown(diagram * (md.MAX_MERMAID_BLOCKS + 1), max_chars=50_000)
    with pytest.raises(md.MarkdownLimitError):
        md.validate_markdown("x" * 11, max_chars=10)
    assert md.validate_markdown("plain words with no marks at all", max_chars=100) == "plain words with no marks at all"
