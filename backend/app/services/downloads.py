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
    to build a downloaded file's filename."""
    return re.sub(r'[\\"/\r\n\t]', "", name).strip() or fallback
