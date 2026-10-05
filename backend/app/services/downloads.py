"""
Module: services.downloads

A single shared helper for building safe `Content-Disposition` filenames
for generated downloads (reports, CSV/bundle exports), used by every router
that serves a file response so the sanitization logic exists in exactly one
place.
"""

from __future__ import annotations

import re


def filename_safe(name: str, *, fallback: str = "download") -> str:
    """Strips characters that would break a quoted `Content-Disposition`
    filename (or be awkward on a filesystem) out of a name before it's used
    to build a downloaded file's filename.

    Anything outside printable ASCII (e.g. an accent, em dash or CJK in a
    project name) is replaced with `_`: header values are Latin-1 on the
    wire, so a wider character crashes the response with a
    `UnicodeEncodeError` (a 500), and even Latin-1 ones are mis-decoded by
    clients that assume UTF-8."""
    cleaned = re.sub(r'[\\"/\r\n\t]', "", name)
    cleaned = re.sub(r"[^\x20-\x7e]", "_", cleaned).strip()
    return cleaned or fallback
