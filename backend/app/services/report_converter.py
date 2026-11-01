"""
Module: services.report_converter

Client for the picture converter service: turns an uploaded EPS or PDF logo into a plain, sanitised SVG so a report can
print it as a vector.

Responsibilities:
- `is_eps` / `is_pdf`: recognise the two formats by their bytes.
- `eps_to_svg` / `pdf_to_svg`: send the file to the converter (`converter/`, a separate container) and pass the
  returned SVG through `report_svg.sanitize_svg`.

Design decisions:
- **The backend never runs a PostScript interpreter or a PDF parser.** Ghostscript has a long history of sandbox
  bypasses and both formats are complex, so the tools live in their own container with no network beyond an internal one
  the backend shares, no secrets, a read-only filesystem and no capabilities. A successful exploit there finds
  nothing to read and nowhere to send it. See docs/solution-architecture.md.
- **Converted once, at upload.** The library stores the resulting SVG, so no converter runs for a stored file, at report
  time or for a record attachment (`sniff_image` still rejects both formats).
- **The reply is untrusted.** The SVG goes through the same allow-list sanitiser as any SVG. A file that leaves nothing
  drawable is refused with a reason rather than stored blank.
- **Vector, not a bitmap.** Text becomes glyph shapes, so no font is needed at report time. A bitmap inside the file is
  kept as an embedded raster (`report_svg`); soft masks are lost. A PDF contributes its first page.
- **The converter is optional.** A deployment that does not run it leaves `REPORT_CONVERTER_URL` empty: EPS and PDF
  upload is then not offered (the library listing says so, `is_configured`) and a file sent anyway is refused as "not
  available on this server". An unreachable converter is reported the same way, never as a bad file, and the backend
  never falls back to running the tools itself.
- The reply is read with a size cap, with no redirects and no proxy settings, to an address the administrator set.

Dependencies: `httpx`, `app.config` (`report_converter_url`), `report_svg`; the converter service.
"""

from __future__ import annotations

import json

import httpx

from app.config import get_settings
from app.services.report_svg import MAX_EMBEDDED_CHARS, MAX_SVG_CHARS, UnsafeSvgError, sanitize_svg

_DOS_EPS_MAGIC = b"\xc5\xd0\xd3\xc6"
_PS_MAGIC = b"%!PS-Adobe"
_PDF_MAGIC = b"%PDF-"
#: Seconds to wait to connect, and to wait for a conversion (the converter's own limit is 30 s per tool, two tools).
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 75.0
#: Largest reply read, in bytes: the markup cap plus the embedded-bitmap allowance, with room for the encoding.
MAX_REPLY_BYTES = (MAX_SVG_CHARS + MAX_EMBEDDED_CHARS) * 2
#: Elements that make an SVG worth keeping: something is actually drawn.
_DRAWN_TAGS = ("<path", "<rect", "<circle", "<ellipse", "<line", "<polygon", "<polyline", "<use", "<text", "<image")
UNAVAILABLE = "EPS and PDF files cannot be read on this server (the converter is not available). Export an SVG or PNG instead."
FALLBACK_ADVICE = "Export an SVG or PNG instead."


class ConversionError(ValueError):
    """The file could not be turned into a safe SVG (the message is shown to the uploader)."""


def is_eps(data: bytes) -> bool:
    """Whether `data` is an EPS, judged by its first bytes.

    Args:
        data: The uploaded bytes.

    Returns:
        `True` for a `%!PS-Adobe` header or the binary DOS EPS wrapper.
    """
    return data.startswith(_PS_MAGIC) or data.startswith(_DOS_EPS_MAGIC)


def is_pdf(data: bytes) -> bool:
    """Whether `data` is a PDF: the `%PDF-` header may follow up to 1 KiB of leading bytes.

    Args:
        data: The uploaded bytes.

    Returns:
        `True` for a PDF header.
    """
    return _PDF_MAGIC in data[:1024]


def is_configured() -> bool:
    """Whether the optional converter service is configured (`REPORT_CONVERTER_URL`), so EPS and PDF uploads can work.

    Returns:
        `True` when a converter URL is set. Reachability is not probed: an unreachable converter is reported when a file
        is uploaded.
    """
    return bool(get_settings().report_converter_url.strip())


def _convert(kind: str, data: bytes) -> str:
    """Posts `data` to the converter and returns its reply, sanitised.

    Args:
        kind: `eps` or `pdf` (the converter route).
        data: The file (already within the upload size limit).

    Returns:
        The sanitised SVG markup.

    Raises:
        ConversionError: Not configured, not reachable, refused by the converter, or the result is unusable.
    """
    base = get_settings().report_converter_url.strip().rstrip("/")
    if not base:
        raise ConversionError(UNAVAILABLE)
    timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            with client.stream(
                "POST", f"{base}/convert/{kind}", content=data, headers={"Content-Type": "application/octet-stream"},
            ) as reply:
                status = reply.status_code
                body = bytearray()
                for chunk in reply.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_REPLY_BYTES:
                        raise ConversionError(f"The file is too complex to use. {FALLBACK_ADVICE}")
    except httpx.HTTPError:
        raise ConversionError(UNAVAILABLE) from None
    if status == 200:
        return _sanitised(bytes(body))
    if status == 422:
        raise ConversionError(f"{_detail(bytes(body))} {FALLBACK_ADVICE}")
    if status == 503:
        raise ConversionError(f"{_detail(bytes(body))} {FALLBACK_ADVICE}")
    if status == 413:
        raise ConversionError(f"The file is too large. {FALLBACK_ADVICE}")
    raise ConversionError(f"The file could not be converted. {FALLBACK_ADVICE}")


def _detail(body: bytes) -> str:
    """The converter's own message from a JSON error reply, or a generic one; never longer than a sentence or two."""
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        detail = None
    return detail[:200] if isinstance(detail, str) and detail else "The file could not be converted."


def _sanitised(body: bytes) -> str:
    """Decodes and sanitises the converter's SVG and checks that something is drawn."""
    try:
        clean = sanitize_svg(body.decode("utf-8", errors="replace"))
    except UnsafeSvgError as exc:
        raise ConversionError(f"The converted file could not be used: {str(exc).rstrip('.').lower()}.") from None
    if not any(tag in clean for tag in _DRAWN_TAGS):
        raise ConversionError(f"The file holds nothing a report can print. {FALLBACK_ADVICE}")
    return clean


def eps_to_svg(data: bytes) -> str:
    """Converts an EPS to a sanitised SVG.

    Args:
        data: A file for which `is_eps` is true (already within the upload size limit).

    Returns:
        The SVG markup, ready to store and draw.

    Raises:
        ConversionError: The converter is unavailable, or the file is damaged, too complex or empty of drawing.
    """
    return _convert("eps", data)


def pdf_to_svg(data: bytes) -> str:
    """Converts the first page of a PDF to a sanitised SVG.

    Args:
        data: A file for which `is_pdf` is true (already within the upload size limit).

    Returns:
        The SVG markup, ready to store and draw.

    Raises:
        ConversionError: The converter is unavailable, or the file is damaged, encrypted, too complex or empty of
            drawing.
    """
    return _convert("pdf", data)


__all__ = ["ConversionError", "eps_to_svg", "is_configured", "is_eps", "is_pdf", "pdf_to_svg"]
