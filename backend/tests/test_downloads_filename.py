"""Tests for `app.services.downloads.filename_safe` — the one place every
generated download's `Content-Disposition` filename is sanitised."""

from __future__ import annotations

import pytest

from app.services.downloads import filename_safe


@pytest.mark.parametrize(("name", "expected"), [
    ("Falcon-3", "Falcon-3"),
    ('a"b/c\\d\r\n\te', "abcde"),
    ("Café — Project", "Caf_ _ Project"),  # only printable ASCII survives
    ("日本語", "___"),
])
def test_filename_safe_strips_breaking_and_non_ascii_characters(name, expected):
    assert filename_safe(name) == expected
    filename_safe(name).encode("ascii")  # must be sendable as an HTTP header value


def test_filename_safe_uses_the_fallback_for_an_empty_result():
    assert filename_safe('"/"', fallback="report") == "report"
    assert filename_safe("   ") == "download"
