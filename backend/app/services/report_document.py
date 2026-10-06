"""
Module: services.report_document

The document-level layer every generated report shares, whatever it reports
on (requirements in `services.reports`, any module's report in
`services.report_framework`):

- `ReportBranding` and `resolve_branding`: an organisation `ReportTemplate`'s
  accent colour, cover page, logo and footer.
- `title_flowables`, `build_pdf`: the cover/title block, footer and A4 document
  build, parameterised by page size so tall requirement tables and wide module
  tables use the same shell.
- `markdown_to_flowables` and `resolve_report_images`: the restricted
  Markdown-to-PDF renderer and the tenant-checked image lookup it relies on.
- `safe`, `styled_table`: ReportLab-markup escaping and the accent-coloured
  table builder.

Design decisions:
- ReportLab's `Paragraph` parses markup, so every user-supplied string must go
  through `safe` first; otherwise `<img src="http://internal/...">` becomes a
  server-side fetch (SSRF / local file read). There is deliberately no second
  escaping helper to drift from this one.
- Images are never fetched by the renderer. `resolve_report_images` resolves
  `attachment:<id>` references to bytes beforehand, restricted to the
  organisation's own shared resources, so the renderer never reasons about
  tenant isolation.
- A template's intro, chapters and appendices are requirement-report content
  and are not part of this shell; only its branding is shared.

Dependencies: ReportLab, markdown-it-py, `services.files`, `services.branding`.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from uuid import UUID
from xml.sax.saxutils import escape as _xml_escape

from markdown_it import MarkdownIt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization, ReportTemplate
from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.files import read_file

_md = MarkdownIt()
STYLES = getSampleStyleSheet()
_MAX_IMAGE_WIDTH = A4[0] - 4 * cm  # matches SimpleDocTemplate's leftMargin+rightMargin default (2cm each)
_ATTACHMENT_REF = re.compile(r"attachment:([0-9a-fA-F-]{36})")


def safe(text: str) -> str:
    """Escapes `&`/`<`/`>` before handing text to a ReportLab `Paragraph`.

    ReportLab's `Paragraph` does not treat its `text` argument as plain
    text — it parses a restricted markup language supporting tags such as
    `<b>`, `<font>`, and `<img src="...">`. Since report content (Markdown
    sections, requirement names/reasoning, module record titles) is
    user-supplied, passing it to `Paragraph` unescaped would let a
    `<img src="http://internal-host/...">` (or a `file:`-scheme source,
    trusted by default in ReportLab < 5) be parsed as real markup and fetched
    server-side — an SSRF/local-file-read primitive triggerable by any project
    member generating a report. Escaping neutralises this: the text renders
    literally instead of being interpreted as markup.

    Args:
        text: Untrusted text.

    Returns:
        The text with markup characters escaped.
    """
    return _xml_escape(text)


@dataclass
class ReportBranding:
    """Optional per-report branding, sourced from an org's `ReportTemplate`
    (R-G-05). Builders fall back to plain, unbranded styling when this is
    omitted entirely."""

    accent_color_hex: str = DEFAULT_ACCENT_COLOR_HEX
    include_cover_page: bool = False
    footer_text: str | None = None
    logo_bytes: bytes | None = None


def load_report_template(db: Session, organization_id: UUID, template_id: UUID) -> ReportTemplate | None:
    """Loads a report template, enforcing that it belongs to `organization_id`.

    Args:
        db: Database session.
        organization_id: The organisation the report is generated for.
        template_id: The requested template.

    Returns:
        The template, or `None` when it does not exist or belongs to another
        organisation (the caller turns that into its own 400).
    """
    template = db.get(ReportTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        return None
    return template


def resolve_branding(db: Session, organization: Organization | None, template: ReportTemplate | None) -> ReportBranding | None:
    """Builds the branding a template selects.

    Args:
        db: Database session.
        organization: The owning organisation (source of the logo).
        template: The selected template, or `None` for an unbranded report.

    Returns:
        `None` when no template is selected; otherwise the template's accent
        colour, cover page flag, footer and (when it asks for one and the
        organisation has one) logo bytes.
    """
    if template is None:
        return None
    logo_bytes = None
    if template.include_logo:
        logo_asset = db.get(FileAsset, organization.logo_file_id) if organization and organization.logo_file_id else None
        if logo_asset is not None:
            logo_bytes = read_file(logo_asset)
    return ReportBranding(
        accent_color_hex=template.accent_color_hex, include_cover_page=template.include_cover_page,
        footer_text=template.footer_text, logo_bytes=logo_bytes,
    )


def title_flowables(title: str, branding: ReportBranding | None) -> list:
    """The opening block of a report: a branded cover page when the branding
    asks for one (logo, accent-coloured title, page break), otherwise a plain
    title.

    Args:
        title: The report title (escaped here).
        branding: Optional branding.

    Returns:
        Flowables to start the story with.
    """
    story: list = []
    if branding and branding.include_cover_page:
        accent_color = colors.HexColor(branding.accent_color_hex)
        cover_style = ParagraphStyle("cover_title", parent=STYLES["Title"], textColor=accent_color, fontSize=28)
        story.append(Spacer(1, 6 * cm))
        if branding.logo_bytes:
            try:
                story.append(Image(io.BytesIO(branding.logo_bytes), width=4 * cm, height=4 * cm, kind="proportional"))
                story.append(Spacer(1, 1 * cm))
            except Exception:  # noqa: BLE001 - a malformed/unsupported logo image must never break report generation
                pass
        story.append(Paragraph(safe(title), cover_style))
        story.append(PageBreak())
        story.append(Spacer(1, 0.5 * cm))
    else:
        story.append(Paragraph(safe(title), STYLES["Title"]))
        story.append(Spacer(1, 0.5 * cm))
    return story


def build_pdf(story: list, *, footer_text: str | None = None, pagesize=A4, **document_options) -> bytes:
    """Builds the PDF for `story`, drawing the branding footer on every page.

    Args:
        story: The flowables.
        footer_text: Centred footer text, or `None` for no footer.
        pagesize: ReportLab page size (portrait A4 by default).
        **document_options: Further `SimpleDocTemplate` options (margins, title).

    Returns:
        The PDF file content.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=pagesize, **document_options)

    def _draw_footer(canvas, doc_):
        if not footer_text:
            return
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(doc_.pagesize[0] / 2, 1 * cm, footer_text)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buffer.getvalue()


def styled_table(data: list[list], *, col_widths: list[float], accent_color, compact: bool = False) -> Table:
    """An accent-headed table with a repeating header row.

    Args:
        data: Rows including the header row; cells are strings or flowables.
        col_widths: Column widths in points.
        accent_color: Header background (a ReportLab colour).
        compact: `True` for the light-grid, zebra-striped style module reports
            use (header cells are expected to be white-text Paragraphs);
            `False` for the requirement report's heavier grid with white
            header text.

    Returns:
        The table flowable.
    """
    table = Table(data, repeatRows=1, colWidths=col_widths)
    if compact:
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent_color),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ]))
    else:
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
    return table


def _image_flowable(image_bytes: bytes):
    """Builds a page-width-constrained ReportLab `Image` flowable, or
    `None` if `image_bytes` isn't a decodable image — the same
    "a bad image must never break report generation" handling used for the
    cover-page logo."""
    try:
        img = Image(io.BytesIO(image_bytes))
        if img.imageWidth > _MAX_IMAGE_WIDTH:
            scale = _MAX_IMAGE_WIDTH / float(img.imageWidth)
            img.drawWidth = _MAX_IMAGE_WIDTH
            img.drawHeight = img.imageHeight * scale
        return img
    except Exception:  # noqa: BLE001 - malformed/unsupported image content must never break report generation
        return None


def markdown_to_flowables(markdown_text: str, images: dict[str, bytes] | None = None) -> list:
    """Converts a Markdown string into a list of ReportLab flowables.

    Covers headings, paragraphs, bullet lists and images on their own line —
    enough for introduction/appendix style sections without a full HTML
    rendering stack.

    Args:
        markdown_text: The Markdown source.
        images: Maps an image reference (as it appears in
            `![alt](ref)`, e.g. `"attachment:<uuid>"`) to already-resolved
            image bytes. A paragraph consisting of *only* an image (the
            normal "image on its own line" Markdown shape) is rendered as
            a `reportlab.platypus.Image`; a reference missing from `images`
            (not resolved, wrong org, not actually an image) is skipped
            silently rather than failing report generation. Images mixed
            inline with other paragraph text are not supported — the
            paragraph falls back to its literal escaped text.

    Returns:
        The flowables (empty for blank input).
    """
    flowables: list = []
    if not markdown_text.strip():
        return flowables
    images = images or {}

    tokens = _md.parse(markdown_text)
    i = 0
    heading_styles = {
        "h1": STYLES["Heading1"], "h2": STYLES["Heading2"], "h3": STYLES["Heading3"],
        "h4": STYLES["Heading4"], "h5": STYLES["Heading4"], "h6": STYLES["Heading4"],
    }
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            text = safe(tokens[i + 1].content)
            flowables.append(Paragraph(text, heading_styles.get(token.tag, STYLES["Heading3"])))
            i += 3
        elif token.type == "paragraph_open":
            inline = tokens[i + 1]
            image_children = [c for c in (inline.children or []) if c.type == "image"]
            if len(image_children) == 1 and len(inline.children) == 1:
                ref = image_children[0].attrs.get("src", "")
                image_bytes = images.get(ref)
                flowable = _image_flowable(image_bytes) if image_bytes else None
                if flowable is not None:
                    flowables.append(flowable)
                    flowables.append(Spacer(1, 0.2 * cm))
                # Missing/unresolvable reference: skip silently, no placeholder.
            else:
                text = safe(inline.content)
                flowables.append(Paragraph(text, STYLES["BodyText"]))
                flowables.append(Spacer(1, 0.2 * cm))
            i += 3
        elif token.type == "bullet_list_open":
            items = []
            j = i + 1
            while tokens[j].type != "bullet_list_close":
                if tokens[j].type == "inline":
                    items.append(ListItem(Paragraph(safe(tokens[j].content), STYLES["BodyText"])))
                j += 1
            flowables.append(ListFlowable(items, bulletType="bullet"))
            i = j + 1
        else:
            i += 1
    return flowables


def resolve_report_images(db: Session, organization_id: UUID, *markdown_texts: str) -> dict[str, bytes]:
    """Scans one or more Markdown strings for `attachment:<uuid>` image
    references (inserted via the report content editor's attachment panel,
    `RichTextEditor`'s "Insert image") and resolves each to its bytes.

    Every resolved reference is checked against `organization_id` *and*
    restricted to `is_org_resource=True` assets before its bytes are read.
    Org scoping alone isn't enough: within a multi-project org, a direct
    (non-shared) `FileAsset` — most importantly a requirement attachment —
    is gated by *project*-level access in its own right
    (`routers/files.py::download_file` requires `get_effective_project_roles`
    for exactly that reason), which report content is never itself scoped
    to check. Without this restriction, a user with report-edit rights on
    Project A could hand-type `attachment:<id>` for a requirement
    attachment belonging to Project B in the same org — one they may have
    no project-level access to at all — and have its bytes embedded into
    Project A's report. Org shared resources have no such finer-grained
    gate (any org member can already see them, `orgs.py::list_org_resources`),
    matching what the attachment picker UI actually offers (org shared
    resources only, never a raw requirement-attachment id) — so this isn't
    a functional restriction on the real feature, only on hand-crafted
    references that were never a legitimate use of it. A reference that
    doesn't resolve — wrong org, not a shared resource, not found, not
    actually an image content type — is simply left out of the returned
    mapping; `markdown_to_flowables` already treats a missing entry as
    "skip this image" rather than an error, so a bad reference never breaks
    report generation.

    Args:
        db: Database session.
        organization_id: The organisation the report belongs to.
        *markdown_texts: Markdown sources to scan.

    Returns:
        `{reference: image bytes}` for every reference that passed the checks.
    """
    resolved: dict[str, bytes] = {}
    for text in markdown_texts:
        for match in _ATTACHMENT_REF.finditer(text):
            ref = match.group(0)
            if ref in resolved:
                continue
            try:
                file_id = UUID(match.group(1))
            except ValueError:
                continue
            asset = db.get(FileAsset, file_id)
            if (
                asset is None
                or asset.organization_id != organization_id
                or not asset.is_org_resource
                or not asset.content_type.startswith("image/")
            ):
                continue
            resolved[ref] = read_file(asset)
    return resolved
