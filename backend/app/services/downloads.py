"""
Module: services.downloads

Shared helpers for generated downloads (reports, CSV/bundle exports): safe
`Content-Disposition` filenames (`filename_safe`) and the report file response
with its content type (`file_response`), used by every router that serves a
file so the sanitization and content types exist in exactly one place.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import Response


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


def content_disposition(disposition: str, filename: str, *, fallback: str = "file") -> str:
    """Builds a `Content-Disposition` header value for a user-supplied filename.

    The plain `filename` is the printable-ASCII form (`filename_safe`), so a header never carries a quote, a
    control character or a character Latin-1 cannot encode (which would turn the download into a 500); a
    name that had to be altered also gets the RFC 5987 `filename*` form so the browser saves the real name.

    Args:
        disposition: `attachment` or `inline`.
        filename: The stored, uploader-chosen name.
        fallback: Used when nothing printable is left of `filename`.

    Returns:
        The header value.
    """
    safe = filename_safe(filename, fallback=fallback)
    value = f'{disposition}; filename="{safe}"'
    if filename and safe != filename:
        value += f"; filename*=UTF-8''{quote(re.sub(r'[\\\r\n\t]', '', filename), safe='')}"
    return value


_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "html": "text/html; charset=utf-8",
    "zip": "application/zip",
}


def file_response(content: bytes, stem: str, ext: str) -> Response:
    """A download response for a generated file.

    Args:
        content: The file bytes.
        stem: The filename without extension. It goes through `content_disposition`, so a quote, a line break or a
            character outside printable ASCII can never reach the header unencoded.
        ext: One of `pdf`, `csv`, `docx`, `xlsx`, `odt`, `ods`, `html`, `zip`; selects the content type.

    Returns:
        A response with the content type and an `attachment` disposition.

    Raises:
        KeyError: If `ext` is not a known format.
    """
    return Response(
        content=content, media_type=_MEDIA_TYPES[ext],
        headers={"Content-Disposition": content_disposition("attachment", f"{stem}.{ext}")},
    )
