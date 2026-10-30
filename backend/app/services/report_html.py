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
- A header or footer shows as a band at the start and end of each page style's stretch, with `n` and `N` standing for the page
  numbers; printing hides the bands and uses CSS margin boxes (`@top-left` …), which the browser fills with the real page
  numbers where it supports them (the logo is not printed this way).
- Page styles: HTML has no pages, so a `PageStyleChange` opens a `<section>` that is as wide as that page would be and
  carries a small label naming its paper and margins (hidden when printed). Printing uses CSS named pages
  (`@page psN { size; margin }`, with `:left` / `:right` for mirrored margins) that the section selects with `page:`,
  so a browser's print dialog gives each section its own paper. The CSS is built from numbers only, never from text.

Dependencies: `services.report_model`, `services.report_svg`, `services.report_math`, `services.report_document` (branding type).
"""

from __future__ import annotations

import base64
import html
import io
import re

from PIL import Image as PilImage

from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.report_image_layout import placed_size_cm
from app.services.report_math import INLINE_SIZE_PT, scaled_svg, typeset
from app.services.report_model import (
    SLOT_NAMES,
    TONE_FILL,
    BulletList,
    Equation,
    Gap,
    Heading,
    Image,
    Note,
    NumberedList,
    PageBreak,
    PageField,
    PageStyle,
    PageStyleChange,
    Paragraph,
    ReportDocument,
    RunningBand,
    Styled,
    Table,
    finalize_links,
    text_on,
    text_runs,
)
from app.services.report_running import cell_lines
from app.services.report_svg import UnsafeSvgError, sanitize_svg

_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"

_CSS = """
:root { --accent: %(accent)s; }
body { isolation: isolate;
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1a1a1a; margin: 2rem auto; max-width: %(width)s; padding: 0 1rem; }
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
figure.image { overflow-x: auto; } figure.image.align-center { text-align: center; } figure.image.align-right { text-align: right; }
figure.image.wrap-left { float: left; margin: .2rem 1rem .5rem 0; } figure.image.wrap-right { float: right; margin: .2rem 0 .5rem 1rem; }
table, .page-break { clear: both; }
div.layer-anchor { display: block; position: relative; height: 0; } div.layer-anchor > figure.image { position: absolute; margin: 0; }
div.layer-anchor.behind > figure.image { z-index: -1; } div.layer-anchor.front > figure.image { z-index: 1; }
figure.image figcaption { color: #444; font-size: .85rem; margin: .3rem 0; } span.picture { display: inline-block; }
figure.equation { text-align: center; overflow-x: auto; } span.math svg { display: inline-block; }
code.math-source { font-size: .9em; }
.logo { max-height: 4rem; margin-bottom: .5rem; }
footer { margin-top: 3rem; color: #666; font-size: .8rem; border-top: 1px solid #ddd; padding-top: .5rem; }
hr.page-break { border: 0; border-top: 1px dashed #bbb; margin: 2rem 0; }
@media print { hr.page-break { break-after: page; border: 0; } }
section.page-style { position: relative; left: 50%%; transform: translateX(-50%%); box-sizing: border-box; max-width: calc(100vw - 2rem); }
.page-frame { color: #666; font-size: .75rem; border: 1px dashed #bbb; border-radius: 4px; padding: .1rem .5rem; margin: 1.5rem 0 .5rem; }
.band { display: grid; grid-template-columns: repeat(3, 1fr); gap: .5rem; align-items: center; color: #555; font-size: .75rem; margin: .5rem 0; }
.band .cell { display: flex; align-items: center; gap: .4rem; white-space: pre-line; } .band .centre { justify-content: center; text-align: center; }
.band .right { justify-content: flex-end; text-align: right; } .band img { width: auto; } .band .pf { font-style: italic; }
.band.header { border-bottom: 1px solid #ddd; padding-bottom: .3rem; }
.band.footer { border-top: 1px solid #ddd; padding-top: .3rem; margin-top: 2rem; }
@media print { .band { display: none; } .page-frame { display: none; }
  section.page-style { position: static; transform: none; width: auto !important; max-width: none; } }
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


def _width_rem(style: PageStyle) -> float:
    """The width of a page in the HTML view: 50rem for a portrait A4 and 70rem for a landscape one, scaled by the
    page's short side for any other size."""
    short = min(style.dimensions_cm)
    return round((70 if style.landscape else 50) * short / 21.0, 1)


def _margin_css(style: PageStyle, *, verso: bool = False) -> str:
    """The CSS `margin` of a page: top, right, bottom, left in cm (the gutter in the left or, mirrored, the inner one)."""
    left, right = style.edges_cm(verso=verso)
    return f"{style.margins.top:g}cm {right:g}cm {style.margins.bottom:g}cm {left:g}cm"


def _page_rules(selector: str, style: PageStyle) -> str:
    """`@page` rules for one page style: its paper and margins, and the left-hand page's margins when they mirror."""
    width, height = style.dimensions_cm
    rules = f"@page{selector} {{ size: {width:g}cm {height:g}cm; margin: {_margin_css(style)}; }}"
    if style.mirror:
        rules += f" @page{selector}:left {{ margin: {_margin_css(style, verso=True)}; }}"
    return rules


_BOXES = {("header", "left"): "top-left", ("header", "centre"): "top-center", ("header", "right"): "top-right",
          ("footer", "left"): "bottom-left", ("footer", "centre"): "bottom-center", ("footer", "right"): "bottom-right"}


def _band_html(band: RunningBand | None, kind: str) -> str:
    """A header or footer as it shows on screen: three cells in a row, with the page numbers as placeholders.

    The page numbers are filled in only when the page is printed (HTML has no pages), so the screen shows `n` and `N`.
    """
    if band is None or band.empty:
        return ""
    cells = []
    for slot in SLOT_NAMES:
        text = "<br>".join(
            "".join(
                '<span class="pf" title="Filled in when printed">' + ("n" if part is PageField.PAGE else "N") + "</span>"
                if isinstance(part, PageField) else _esc(part)
                for part in line
            )
            for line in cell_lines(band.slot(slot))
        )
        logo = ""
        if band.logo is not None and band.logo_slot == slot:
            uri = _data_uri(band.logo.data) if band.logo.data else None
            if uri is None and band.logo.svg is not None:
                try:
                    uri = "data:image/svg+xml;base64," + base64.b64encode(sanitize_svg(band.logo.svg).encode()).decode("ascii")
                except UnsafeSvgError:
                    uri = None
            logo = f'<img src="{uri}" alt="" style="height:{band.logo_height_cm:g}cm">' if uri else ""
        cells.append(f'<div class="cell {slot}">{logo}<span>{text}</span></div>')
    return f'<div class="band {kind}">{"".join(cells)}</div>'


def _css_string(text: str) -> str:
    """`text` as the inside of a CSS string: backslash, quote, angle brackets, ampersand and line breaks escaped, controls dropped."""
    out = []
    for char in text:
        if char == "\n":
            out.append("\\A ")
        elif ord(char) < 32 or ord(char) == 127:
            continue
        elif char in '\\"<>&\'':
            out.append(f"\\{ord(char):x} ")
        else:
            out.append(char)
    return "".join(out)


def _box_content(parts: tuple) -> str:
    """The CSS `content` value of a margin box: strings and page counters."""
    tokens = []
    for part in parts:
        if isinstance(part, PageField):
            tokens.append("counter(page)" if part is PageField.PAGE else "counter(pages)")
        else:
            tokens.append(f'"{_css_string(part)}"')
    return " ".join(tokens) or '""'


def _box_rules(selector: str, style: PageStyle) -> str:
    """Margin-box rules for one page style: its header and footer cells, with the cells swapped on left-hand pages.

    Browsers that support CSS margin boxes print them (with the page numbers); the first page shows the band unless the
    band skips it (for the document's first page only: a browser has no first-page rule per section).
    """
    rules = []
    for kind, band in (("header", style.header), ("footer", style.footer)):
        if band is None or band.empty:
            continue
        for slot in SLOT_NAMES:
            box = _BOXES[(kind, slot)]
            swapped = _BOXES[(kind, {"left": "right", "centre": "centre", "right": "left"}[slot])]
            rules.append(
                f"@page{selector} {{ @{box} {{ content: {_box_content(band.slot(slot))}; font-size: 8pt; white-space: pre-line; }} }}"
            )
            if style.mirror:
                rules.append(
                    f"@page{selector}:left {{ @{swapped} {{ content: {_box_content(band.slot(slot))}; font-size: 8pt; white-space: pre-line; }} }}"
                )
            if not band.first_page:
                rules.append(f"@page{selector}:first {{ @{box} {{ content: none; }} }}")
    return "\n".join(rules)


def _frame_label(style: PageStyle) -> str:
    """The visible label of a page-style change: the paper, direction, margins and whether they mirror."""
    margins = style.margins
    sides = f"{margins.top:g} / {margins.bottom:g} / {margins.left:g} / {margins.right:g} cm"
    gutter = f", gutter {margins.gutter:g} cm" if margins.gutter else ""
    mirrored = ", mirrored" if style.mirror else ""
    direction = "landscape" if style.landscape else "portrait"
    return f"Page style: {style.page_size} {direction}; margins (top / bottom / left / right) {sides}{gutter}{mirrored}"


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _styled(run: Styled) -> str:
    """A bold / italic / code / link run as HTML: the escaped words inside the matching tags.

    A link was checked by `finalize_links`; its address is escaped as an attribute, and an outside address opens in a
    new tab without handing over the page (`noopener`, `noreferrer`) or its search weight (`nofollow`).
    """
    inner = _esc(run.text)
    if run.code:
        inner = f"<code>{inner}</code>"
    if run.italic:
        inner = f"<em>{inner}</em>"
    if run.bold:
        inner = f"<strong>{inner}</strong>"
    if run.href is None:
        return inner
    if run.href.startswith("#"):
        return f'<a href="{_esc(run.href)}">{inner}</a>'
    return f'<a href="{_esc(run.href)}" rel="noopener noreferrer nofollow" target="_blank">{inner}</a>'


def _rich(value: str) -> str:
    """Escaped HTML for model text, with its styles applied and its equations drawn inline (a plain string is just escaped)."""
    return "".join(
        _esc(run) if isinstance(run, str) else _styled(run) if isinstance(run, Styled) else _equation(run) for run in text_runs(value)
    )


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


def _figure(block: Image, usable_cm: float) -> str | None:
    """An image block as a `<figure>`: the picture at its placed width, alignment and alternative text, with its caption.

    A decorative picture has an empty `alt` and is hidden from assistive technology. `None` when it cannot be drawn.
    """
    size = placed_size_cm(block, usable_cm)
    if size is None:
        return None
    width, height = size
    label = "" if block.decorative or not block.alt else f' role="img" aria-label="{_esc(block.alt)}"'
    hidden = ' aria-hidden="true"' if block.decorative else ""
    # A floated figure shrinks to fit its content, so a percentage cap on the picture inside it would resolve against
    # nothing: the wrapped figure carries the width and the cap, and its picture fills it.
    wrapped = block.placement == "wrap"
    style = (
        f' style="width:100%;height:auto;aspect-ratio:{width:g}/{height:g}"' if wrapped
        else f' style="width:{width:g}cm;max-width:100%;height:auto;aspect-ratio:{width:g}/{height:g}"'
    )
    if block.svg is not None:
        try:
            picture = f'<span class="picture"{label}{hidden}{style}>{sanitize_svg(block.svg)}</span>'
        except UnsafeSvgError:
            return None
    else:
        uri = _data_uri(block.data)
        if uri is None:
            return None
        picture = f'<img src="{uri}" alt="{"" if block.decorative else _esc(block.alt)}"{style}>'
    caption = f"<figcaption>{_esc(block.caption)}</figcaption>" if block.caption else ""
    if block.placement == "wrap":
        side = "left" if block.align == "left" else "right"
        return f'<figure class="image wrap-{side}" style="width:{width:g}cm;max-width:60%">{picture}</figure>'
    if block.floats:
        # The browser has no pages: a margin or page anchor is measured from where the block sits, as a paragraph anchor is.
        place = f' style="left:{block.offset_x_cm:g}cm;top:{block.offset_y_cm:g}cm"'
        return f'<div class="layer-anchor {block.placement}"><figure class="image"{place}>{picture}</figure></div>'
    align = block.align if block.align in ("left", "center", "right") else "center"
    inner = caption + picture if block.caption_above else picture + caption
    return f'<figure class="image align-{align}">{inner}</figure>'


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
    document = finalize_links(document)
    accent = _accent(document)
    parts = [f"<h1>{_esc(document.title)}</h1>"]
    branding = document.branding
    if branding and branding.logo_bytes:
        uri = _data_uri(branding.logo_bytes)
        if uri:
            parts.insert(0, f'<img class="logo" src="{uri}" alt="">')
    sections: dict[PageStyle, int] = {}
    in_section = False
    current = document.style
    parts.append(_band_html(current.header, "header"))
    for block in document.blocks:
        if isinstance(block, Heading):
            tag = f"h{min(max(block.level, 1), 4) + 1}"
            anchor = f' id="{_esc(block.anchor)}"' if block.anchor else ""
            parts.append(f"<{tag}{anchor}>{_rich(block.text)}</{tag}>")
        elif isinstance(block, Paragraph):
            parts.append(f"<p>{_rich(block.text)}</p>")
        elif isinstance(block, Equation):
            parts.append(_equation(block))
        elif isinstance(block, Note):
            parts.append(f'<p class="note">{_esc(block.text)}</p>')
        elif isinstance(block, BulletList):
            parts.append("<ul>" + "".join(f"<li>{_rich(item)}</li>" for item in block.items) + "</ul>")
        elif isinstance(block, NumberedList):
            parts.append("<ol>" + "".join(f"<li>{_rich(item)}</li>" for item in block.items) + "</ol>")
        elif isinstance(block, Image):
            figure = _figure(block, current.usable_width_cm)
            if figure:
                parts.append(figure)
        elif isinstance(block, Table):
            parts.append(_table(block))
        elif isinstance(block, PageBreak):
            parts.append('<hr class="page-break">')
        elif isinstance(block, PageStyleChange):
            parts.append(_band_html(current.footer, "footer"))
            if in_section:
                parts.append("</section>")
            in_section = block.style != document.style
            current = block.style
            parts.append(f'<div class="page-frame">{_esc(_frame_label(block.style))}</div>')
            if in_section:
                index = sections.setdefault(block.style, len(sections) + 1)
                parts.append(f'<section class="page-style ps{index}" style="width: {_width_rem(block.style):g}rem">')
            parts.append(_band_html(block.style.header, "header"))
        elif isinstance(block, Gap):
            continue  # a PDF layout hint
    parts.append(_band_html(current.footer, "footer"))
    if in_section:
        parts.append("</section>")
    if branding and branding.footer_text and document.footer is None:
        parts.append(f"<footer>{_esc(branding.footer_text)}</footer>")
    css = _CSS % {
        "accent": accent, "width": f"{_width_rem(document.style):g}rem", "head_text": "#" + text_on(accent.lstrip("#")),
    }
    # `@page` rules sit outside `@media`: browsers ignore them on screen and do not accept them inside a media query.
    css += _page_rules("", document.style) + "\n" + _box_rules("", document.style) + "\n"
    for style, index in sections.items():
        selector = f" ps{index}"
        css += f"{_page_rules(selector, style)}\n{_box_rules(selector, style)}\n"
        css += f".ps{index} {{ page: ps{index}; break-before: page; break-after: page; }}\n"
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(document.title)}</title><style>{css}</style></head><body>\n" + "\n".join(parts) + "\n</body></html>\n"
    )
    return page.encode("utf-8")


__all__ = ["CSP", "render_html_document"]
