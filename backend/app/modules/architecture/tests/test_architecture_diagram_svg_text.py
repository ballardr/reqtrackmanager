"""Tests for `diagram_svg._text`, which makes a person's text safe for an XML text node or attribute in the server SVG: it
removes the characters XML 1.0 cannot carry (control characters other than tab, line feed and carriage return, U+FFFE and
U+FFFF), keeps every other character, and escapes markup and double quotes. Pure functions; no database or organisation."""

from __future__ import annotations

import pytest

from app.modules.architecture.diagram_svg import _text


@pytest.mark.parametrize("code", [*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0xFFFE, 0xFFFF])
def test_a_character_xml_cannot_carry_is_removed(code):
    """Every forbidden code point is dropped and the text around it is kept."""
    assert _text(f"a{chr(code)}b") == "ab"


@pytest.mark.parametrize("char", ["\t", "\n", "\r", " ", "é", "漢", "\U0001F600", "\x7f"])
def test_a_character_xml_can_carry_is_kept(char):
    """Whitespace XML allows, accented and wide characters, an emoji and DEL are left as they are."""
    assert _text(f"a{char}b") == f"a{char}b"


def test_markup_and_quotes_are_escaped():
    """Angle brackets, ampersands and double quotes cannot break out of a text node or an attribute."""
    assert _text('<b a="1">&') == "&lt;b a=&quot;1&quot;&gt;&amp;"
