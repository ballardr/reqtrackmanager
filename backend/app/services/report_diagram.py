"""
Module: services.report_diagram

Draws Mermaid diagrams for documents with the same engine, version and font as the screen.

Responsibilities:
- `DiagramBudget.draw`: ask the converter service for a diagram's SVG, make it safe (`svg_styles.flatten_styles`,
  `report_svg.sanitize_svg`), size and cache it; bound one run by a diagram count and a total drawing time.
- `DiagramError`: why a diagram could not be drawn, in words a report reader can see.

Design decisions:
- Drawing runs in the converter container (no external network, read-only filesystem, killed at a time limit); the
  backend sends text and sanitises the untrusted markup it receives.
- Screen and report agree because both read the Mermaid version, font and limits in `diagram_config.json` and
  `frontend/src/utils/mermaidRenderConfig.json`; `tests/test_diagram_config.py` fails when they differ.
- A diagram that cannot be drawn never fails a report: the source prints as a labelled block with a warning, and after
  the converter itself fails the run stops trying.
- The cache key is the hash of (version, theme, source); failures are not cached. Documents use the `light` theme.
- Each diagram gets its own element identifiers so several inline in one HTML page never share a marker or style.

Dependencies: `httpx`, `app.config` (`report_converter_url`), `svg_styles`, `report_svg`, `markdown_text`.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.services.markdown_text import MAX_MERMAID_SOURCE_CHARS
from app.services.report_svg import MAX_EMBEDDED_CHARS, MAX_SVG_CHARS, sanitize_svg
from app.services.svg_styles import flatten_styles

#: The Mermaid version and font the converter and the screen draw with (checked against both by a test).
MERMAID_VERSION = "12.3.0"
FONT_FAMILY = "DejaVu Sans"
#: Seconds to wait to connect, and to wait for a drawing (the converter's own limit is 30 s).
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 45.0
#: The most diagrams one report run may ask the converter for, and the most seconds all those drawings may take together.
MAX_DIAGRAMS_PER_RUN = 40
MAX_SECONDS_PER_RUN = 150.0
#: Largest reply read, in characters of SVG (the markup cap plus the embedded-bitmap allowance, with room for the encoding).
MAX_REPLY_BYTES = (MAX_SVG_CHARS + MAX_EMBEDDED_CHARS) * 2
#: The cache holds at most this many drawings and this many characters of SVG.
CACHE_MAX_ENTRIES = 200
CACHE_MAX_CHARS = 24_000_000

UNAVAILABLE = "Diagrams are not drawn because the converter service is not available."
#: The engine's fixed drawing name where it names the drawing: an `id` value, a `#id` reference or selector, and the identifiers
#: derived from it (`my-svg_pointEnd`, `my-svg-flowchart-A-0`), but not a word of the drawing's own text.
_ID = re.compile(r'(?<=["#])my-svg(?![A-Za-z0-9])')
_ROOT = re.compile(r"<svg\b[^>]*>")
_VIEW_BOX = re.compile(r'viewBox="\s*(-?[\d.]+)[ ,]+(-?[\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)\s*"')
_ROOT_SIZE = re.compile(r'\s(?:width|height)="[^"]*"')
_TEXT = re.compile(r"<text\b[^>]*>(.*?)</text>", re.DOTALL)
_TAG = re.compile(r"<[^>]*>")
#: The longest text alternative built from a drawing's labels, in characters.
MAX_LABEL_CHARS = 300


class DiagramError(Exception):
    """A diagram could not be drawn; the message is safe to show in a report's warning."""


@dataclass(frozen=True)
class DrawnDiagram:
    """A drawing ready to embed.

    Attributes:
        svg: Sanitised SVG with explicit `width` and `height` (user units, 96 to the inch) and no style sheet.
        width: The drawing's width in those units.
        height: The drawing's height in those units.
        labels: The words the drawing prints (node and edge labels), joined, for the picture's text alternative.
    """

    svg: str
    width: float
    height: float
    labels: str = ""


class _Cache:
    """A thread-safe, size-bounded least-recently-used cache of drawings."""

    def __init__(self) -> None:
        self._items: OrderedDict[str, DrawnDiagram] = OrderedDict()
        self._chars = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> DrawnDiagram | None:
        with self._lock:
            drawn = self._items.get(key)
            if drawn is not None:
                self._items.move_to_end(key)
            return drawn

    def put(self, key: str, drawn: DrawnDiagram) -> None:
        with self._lock:
            previous = self._items.pop(key, None)
            if previous is not None:
                self._chars -= len(previous.svg)
            self._items[key] = drawn
            self._chars += len(drawn.svg)
            while self._items and (len(self._items) > CACHE_MAX_ENTRIES or self._chars > CACHE_MAX_CHARS):
                _, evicted = self._items.popitem(last=False)
                self._chars -= len(evicted.svg)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._chars = 0


_cache = _Cache()


def clear_cache() -> None:
    """Empties the drawing cache (for tests, and after the Mermaid version changes)."""
    _cache.clear()


def is_configured() -> bool:
    """Whether the converter service is configured (`REPORT_CONVERTER_URL`), so diagrams can be drawn.

    Returns:
        `True` when a converter URL is set. Reachability is not probed: an unreachable converter is reported on use.
    """
    return bool(get_settings().report_converter_url.strip())


def cache_key(source: str, theme: str) -> str:
    """The cache key of a drawing: the hash of the Mermaid version, the theme and the text.

    Args:
        source: The Mermaid text.
        theme: `light` or `dark`.

    Returns:
        A hex digest.
    """
    return hashlib.sha256(f"{MERMAID_VERSION}\n{theme}\n{source}".encode()).hexdigest()


def _post(source: str, theme: str) -> bytes:
    """Asks the converter for the SVG of `source`.

    Raises:
        DiagramError: Not configured, not reachable, refused by the converter, or the reply is too large.
    """
    base = get_settings().report_converter_url.strip().rstrip("/")
    if not base:
        raise DiagramError(UNAVAILABLE)
    timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", f"{base}/diagram", json={"source": source, "theme": theme}) as reply:
                status = reply.status_code
                body = bytearray()
                for chunk in reply.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_REPLY_BYTES:
                        raise DiagramError("The diagram is too large to draw.")
    except httpx.HTTPError:
        raise DiagramError(UNAVAILABLE) from None
    if status == 200:
        return bytes(body)
    if status in (413, 422, 503):
        raise DiagramError(_detail(bytes(body)))
    raise DiagramError("The diagram could not be drawn.")


def _detail(body: bytes) -> str:
    """The converter's own message from a JSON error reply, or a generic one; never longer than a sentence or two."""
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        detail = None
    return detail[:200] if isinstance(detail, str) and detail else "The diagram could not be drawn."


def _own_ids(svg: str, key: str) -> str:
    """`svg` with the engine's fixed drawing name replaced by one derived from `key`, in the markup and its style sheet."""
    return _ID.sub(f"diagram-{key[:12]}", svg)


def _sized(svg: str) -> tuple[str, float, float]:
    """The root's size from its `viewBox`, written as explicit `width` and `height`.

    Returns:
        The markup and the drawing's width and height.

    Raises:
        DiagramError: The drawing has no readable size.
    """
    root = _ROOT.search(svg)
    box = _VIEW_BOX.search(root.group(0)) if root else None
    if root is None or box is None:
        raise DiagramError("The diagram has nothing to draw.")
    width, height = float(box.group(3)), float(box.group(4))
    if width <= 0 or height <= 0:
        raise DiagramError("The diagram has nothing to draw.")
    tag = _ROOT_SIZE.sub("", root.group(0))
    tag = tag[:-1] + f' width="{width:g}" height="{height:g}">'
    return svg[:root.start()] + tag + svg[root.end():], width, height


def _labels(svg: str) -> str:
    """The distinct words-in-order a drawing prints, comma-joined and cut, as its text alternative."""
    seen: dict[str, None] = {}
    for found in _TEXT.finditer(svg):
        text = " ".join(html.unescape(_TAG.sub(" ", found.group(1))).split())
        if text:
            seen.setdefault(text)
    joined = ", ".join(seen)
    return joined if len(joined) <= MAX_LABEL_CHARS else joined[:MAX_LABEL_CHARS].rstrip(", ") + "…"


def _made_safe(raw: str, key: str) -> DrawnDiagram:
    """The converter's SVG made ready to embed: own identifiers, styles flattened, sized, sanitised.

    Raises:
        DiagramError: The markup cannot be used (not well-formed, nothing drawn, or something that is not allowed).
    """
    try:
        flat = flatten_styles(_own_ids(raw, key))
        sized, width, height = _sized(flat)
        clean = sanitize_svg(sized)
        return DrawnDiagram(clean, width, height, _labels(clean))
    except ValueError:  # includes `UnsafeSvgError`
        raise DiagramError("The drawing could not be used.") from None


def draw(source: str, theme: str = "light") -> DrawnDiagram:
    """Draws one diagram, from the cache when it was drawn before.

    Args:
        source: The Mermaid text (at most `MAX_MERMAID_SOURCE_CHARS` characters).
        theme: `light` or `dark`.

    Returns:
        The drawing, ready to embed.

    Raises:
        DiagramError: The text is empty or too long, the converter is not available, or the diagram could not be drawn.
    """
    text = source.strip()
    if not text:
        raise DiagramError("The diagram is empty.")
    if len(text) > MAX_MERMAID_SOURCE_CHARS:
        raise DiagramError(f"The diagram text is over the limit of {MAX_MERMAID_SOURCE_CHARS} characters.")
    key = cache_key(text, theme)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    drawn = _made_safe(_post(text, theme).decode("utf-8", errors="replace"), key)
    _cache.put(key, drawn)
    return drawn


class DiagramBudget:
    """Draws the diagrams of one report run within a count and a time budget.

    Attributes:
        down: Why the converter could not be used, once it has failed; the remaining diagrams are not tried.
    """

    def __init__(self, *, max_diagrams: int = MAX_DIAGRAMS_PER_RUN, max_seconds: float = MAX_SECONDS_PER_RUN) -> None:
        self._max_diagrams = max_diagrams
        self._max_seconds = max_seconds
        self._asked = 0
        self._spent = 0.0
        self.down: str | None = None

    def draw(self, source: str, theme: str = "light") -> DrawnDiagram:
        """Draws a diagram if the run's budget allows.

        Args:
            source: The Mermaid text.
            theme: `light` or `dark`.

        Returns:
            The drawing.

        Raises:
            DiagramError: The reason it was not drawn (see `draw`, the exhausted budget, or an earlier converter failure).
        """
        if self.down is not None:
            raise DiagramError(self.down)
        text = source.strip()
        cached = _cache.get(cache_key(text, theme)) if text else None
        if cached is not None:
            return cached
        if self._asked >= self._max_diagrams:
            raise DiagramError(f"A run draws at most {self._max_diagrams} diagrams; the rest are shown as text.")
        if self._spent >= self._max_seconds:
            raise DiagramError("Drawing the diagrams of this run took too long; the rest are shown as text.")
        self._asked += 1
        started = time.monotonic()
        try:
            return draw(source, theme)
        except DiagramError as exc:
            if str(exc) == UNAVAILABLE:
                self.down = UNAVAILABLE
            raise
        finally:
            self._spent += time.monotonic() - started


__all__ = [
    "DiagramBudget", "DiagramError", "DrawnDiagram", "FONT_FAMILY", "MERMAID_VERSION", "UNAVAILABLE", "cache_key",
    "clear_cache", "draw", "is_configured",
]
