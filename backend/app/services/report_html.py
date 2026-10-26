"""
Module: services.report_html

Renders a neutral `ReportDocument` (`services.report_model`) to one standalone HTML page: the document
family's HTML download and the designer's live preview.

Design decisions:
- **Nothing in the page can run or fetch.** Every string is escaped with `html.escape`; the page carries no
  script and a `Content-Security-Policy` meta tag (`default-src 'none'; img-src data:; style-src
  'unsafe-inline'`), so even a defect in escaping could not load anything. Raster images are inlined as
  `data:` URIs of a sniffed type (never the type a record claims), and an SVG figure is inlined only after
  `report_svg.sanitize_svg`.
- Equations are the server-made SVG from `report_math` (the same drawing the PDF embeds), sized in `em` so they
  follow the text size; one that cannot be drawn is shown as its source in a `<code>` element. The TeX is the
  accessible name (`aria-label`).
- A tone is looked up in `TONE_FILL`, never taken from the model as a colour, as in the PDF and Word renderers.
- Branding applies as in the other renderers: the accent colour (validated as six hex digits), the logo and
  the footer text; the cover page is a PDF and Word device, so the HTML shows a plain title.
- One stylesheet, inline and small, with a print rule so printing the page from a browser paginates at
  `PageBreak`.

Dependencies: `services.report_model`, `services.report_svg`, `services.report_math`, `services.report_document` (branding type).
"""

from __future__ import annotations

import base64
import html
import io
import re

from PIL import Image as PilImage

from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.report_math import INLINE_SIZE_PT, scaled_svg, typeset
from app.services.report_model import (
    TONE_FILL,
    BulletList,
    Equation,
    Gap,
    Heading,
    Image,
    Note,
    PageBreak,
    Paragraph,
    ReportDocument,
    Table,
    text_on,
    text_runs,
)
from app.services.report_svg import UnsafeSvgError, sanitize_svg

_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"

_CSS = """
:root { --accent: %(accent)s; }
body { font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1a1a1a; margin: 2rem auto; max-width: %(width)s; padding: 0 1rem; }
h1 { color: var(--accent); border-bottom: 3px solid var(--accent); padding-bottom: .3rem; }
h2, h3, h4, h5 { color: #222; margin: 1.6rem 0 .5rem; }
p { margin: .5rem 0; white-space: pre-line; }
p.note { color: #555; font-size: .85rem; }
table { border-collapse: collapse; width: 100%%; margin: .8rem 0; font-size: .85rem; }
th { background: var(--accent); color: %(head_text)s; text-align: left; }
th, td { border: 1px solid #ccc; padding: .3rem .5rem; vertical-align: top; overflow-wrap: anywhere; }
table.compact td { border-color: #ddd; }
tbody tr:nth-child(even) td { background-color: #f5f5f5; }
figure { margin: 1rem 0; } figure img, figure svg { max-width: 100%%; height: auto; }
figure.equation { text-align: center; overflow-x: auto; } span.math svg { display: inline-block; }
code.math-source { font-size: .9em; }
.logo { max-height: 4rem; margin-bottom: .5rem; }
footer { margin-top: 3rem; color: #666; font-size: .8rem; border-top: 1px solid #ddd; padding-top: .5rem; }
hr.page-break { border: 0; border-top: 1px dashed #bbb; margin: 2rem 0; }
@media print { hr.page-break { break-after: page; border: 0; } }
"""


def _accent(document: ReportDocument) -> str:
    """The accent colour as `#RRGGBB`: the branding's when it is six hex digits, else the default."""
    candidate = document.branding.accent_color_hex if document.branding else DEFAULT_ACCENT_COLOR_HEX
    match = _HEX.match(candidate or "")
    return "#" + (match.group(1) if match else DEFAULT_ACCENT_COLOR_HEX.lstrip("#"))


def _data_uri(data: bytes) -> str | None:
    """A `data:` URI for raster bytes of a type this renderer inlines, sniffed from the bytes; `None` otherwise."""
    try:
        with PilImage.open(io.BytesIO(data)) as image:
            media_type = _IMAGE_TYPES.get(image.format or "")
    except Exception:  # noqa: BLE001 - not an image: skipped, as in the other renderers
        return None
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}" if media_type else None


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _rich(value: str) -> str:
    """Escaped HTML for model text, with its equations drawn inline (a plain string is just escaped)."""
    return "".join(_esc(run) if isinstance(run, str) else _equation(run) for run in text_runs(value))


def _table(block: Table) -> str:
    head = "".join(f"<th>{_esc(c)}</th>" for c in block.columns)
    rows = []
    for r, row in enumerate(block.rows):
        cells = []
        for c, cell in enumerate(row):
            tone = block.tone_at(r, c)
            style = f' style="background-color:#{TONE_FILL[tone]};color:#{text_on(TONE_FILL[tone])}"' if tone else ""
            cells.append(f"<td{style}>{_rich(cell)}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    css = ' class="compact"' if block.compact else ""
    return f"<table{css}><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _figure(block: Image) -> str | None:
    label = f' role="img" aria-label="{_esc(block.alt)}"' if block.alt else ""
    if block.svg is not None:
        try:
            return f"<figure{label}>{sanitize_svg(block.svg)}</figure>"
        except UnsafeSvgError:
            return None
    uri = _data_uri(block.data)
    return f'<figure><img src="{uri}" alt="{_esc(block.alt)}"></figure>' if uri else None


def _equation(block: Equation) -> str:
    """One equation as HTML: the SVG (display: in a centred figure, inline: in a span on the text baseline), or its source."""
    drawn = typeset(block.tex, block.display)
    label = f' role="img" aria-label="{_esc(block.tex)}"'
    if drawn is None:
        return f'<code class="math-source">{_esc(block.text)}</code>' if not block.display else (
            f'<figure class="equation"><code class="math-source">{_esc(block.text)}</code></figure>'
        )
    svg = scaled_svg(drawn, 1 / INLINE_SIZE_PT, "em")
    if block.display:
        return f'<figure class="equation"{label}>{svg}</figure>'
    return f'<span class="math"{label} style="vertical-align:-{drawn.descent / INLINE_SIZE_PT:.3f}em">{svg}</span>'


def render_html_document(document: ReportDocument) -> bytes:
    """Renders `document` as a standalone, script-free HTML page.

    Args:
        document: The neutral document (title, blocks, optional branding, orientation).

    Returns:
        UTF-8 HTML bytes.
    """
    accent = _accent(document)
    parts = [f"<h1>{_esc(document.title)}</h1>"]
    branding = document.branding
    if branding and branding.logo_bytes:
        uri = _data_uri(branding.logo_bytes)
        if uri:
            parts.insert(0, f'<img class="logo" src="{uri}" alt="">')
    for block in document.blocks:
        if isinstance(block, Heading):
            parts.append(f"<h{min(max(block.level, 1), 4) + 1}>{_rich(block.text)}</h{min(max(block.level, 1), 4) + 1}>")
        elif isinstance(block, Paragraph):
            parts.append(f"<p>{_rich(block.text)}</p>")
        elif isinstance(block, Equation):
            parts.append(_equation(block))
        elif isinstance(block, Note):
            parts.append(f'<p class="note">{_esc(block.text)}</p>')
        elif isinstance(block, BulletList):
            parts.append("<ul>" + "".join(f"<li>{_rich(item)}</li>" for item in block.items) + "</ul>")
        elif isinstance(block, Image):
            figure = _figure(block)
            if figure:
                parts.append(figure)
        elif isinstance(block, Table):
            parts.append(_table(block))
        elif isinstance(block, PageBreak):
            parts.append('<hr class="page-break">')
        elif isinstance(block, Gap):
            continue  # a PDF layout hint
    if branding and branding.footer_text:
        parts.append(f"<footer>{_esc(branding.footer_text)}</footer>")
    css = _CSS % {
        "accent": accent, "width": "70rem" if document.landscape else "50rem", "head_text": "#" + text_on(accent.lstrip("#")),
    }
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(document.title)}</title><style>{css}</style></head><body>\n" + "\n".join(parts) + "\n</body></html>\n"
    )
    return page.encode("utf-8")


__all__ = ["CSP", "render_html_document"]
