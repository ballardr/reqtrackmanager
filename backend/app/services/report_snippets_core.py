"""
Module: services.report_snippets_core

The platform's built-in report snippets: fragments of a document layout that the designer inserts by copying their
blocks (`modules.registry.ReportSnippet`). A module adds snippets about its own records through
`ModuleDefinition.report_snippets`; this file holds only what needs no module.

Responsibilities:
- Declare the built-in set (`CORE_REPORT_SNIPPETS`): a cover page, a logo at the top right of the first page, record
  images, document control, approvals and a landscape table section.
- `_place_logo`: size and place the logo for the page it goes on (the one layout-aware snippet).

Design decisions:
- **Every snippet is true in the formats it lists.** The logo is an image in front of the text anchored to the page
  corner, which PDF, Word and OpenDocument text print where it is set; the browser preview has no pages and measures
  from where the block sits, so HTML is not listed for it.
- **Document control and approvals are lists of lines, not tables**: a table block needs a record source, and there is
  no block for a table of fixed words. A list with fill-in lines prints the same in every format.
- **A cover page is a section in its own page style with an empty header and footer**, so the document's running
  text does not print on it, and the report returns to its own style on a new page after it.
- **No placeholder picture.** The logo asks for an image; an empty value is refused when applied.

Dependencies: `services.report_starter_blocks` (block builders), `modules.registry` (the snippet types).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.modules.registry import ReportSnippet, ReportSnippetParameter
from app.services.report_page_styles import resolve_page_styles
from app.services.report_starter_blocks import heading, text

CATEGORY_FRONT = "Cover and front matter"
CATEGORY_IMAGES = "Images"
CATEGORY_TABLES = "Tables"
CATEGORY_APPROVALS = "Approvals"

#: The box the logo is fitted into, in cm: at most this wide, and this tall less what the top margin leaves.
LOGO_MAX_WIDTH_CM = 4.0
LOGO_MAX_HEIGHT_CM = 1.6
#: How far below the top edge of the sheet the logo starts, and the least height it keeps, in cm.
LOGO_TOP_CM = 0.5
LOGO_MIN_HEIGHT_CM = 0.6
#: The picture's shape assumed when the image has no pixel size (an SVG).
LOGO_FALLBACK_ASPECT = 2.5


def _place_logo(
    fragment: dict[str, Any], values: Mapping[str, str], tree: dict[str, Any], image_aspect: Callable[[str], float | None],
) -> None:
    """Sizes the logo to fit above the text and puts it at the top right of the layout's own first page.

    The size keeps the picture's shape inside a `LOGO_MAX_WIDTH_CM` wide box that ends above the top margin; the offsets
    are measured from the corner of the sheet, so the right edge lines up with the right margin. The position is fixed
    here, so a later change of paper size or margins needs the offsets edited.

    Args:
        fragment: The fragment being built (its first block is the image).
        values: The parameter values by key.
        tree: The layout the snippet goes into (its page size, orientation and margins).
        image_aspect: Width divided by height of a library image by file id, or `None` when unknown.
    """
    style, _named = resolve_page_styles(tree)
    page_width = style.dimensions_cm[0]
    box_height = max(LOGO_MIN_HEIGHT_CM, min(LOGO_MAX_HEIGHT_CM, style.margins.top - LOGO_TOP_CM - 0.1))
    aspect = image_aspect(values.get("image", "")) or LOGO_FALLBACK_ASPECT
    width = min(LOGO_MAX_WIDTH_CM, box_height * aspect)
    image = fragment["nodes"][0]
    image["width"], image["width_unit"] = round(width, 2), "cm"
    image["offset_x"] = round(page_width - style.edges_cm()[1] - width, 2)
    image["offset_y"] = LOGO_TOP_CM
    image.pop("height", None)


COVER_PAGE = ReportSnippet(
    key="cover-page",
    name="Cover page",
    description=(
        "A title page: the report title, project, organisation, version and date, with no header or footer, "
        "then the report starts on a new page."
    ),
    category=CATEGORY_FRONT,
    blocks=(
        {
            "type": "section", "page_style": "Cover",
            "children": [
                heading("{{report_title}}", 1),
                text("{{project_name}} ({{project_code}})"),
                text("{{organisation}}"),
                text("Version {{layout_version}}, {{generated_on}}"),
            ],
        },
    ),
    root={"page_styles": [{"name": "Cover", "header": {}, "footer": {}}]},
)

LOGO_TOP_RIGHT = ReportSnippet(
    key="logo-top-right",
    name="Logo, top right of the first page",
    description=(
        "A picture in front of the text at the top right corner of the page it is placed on. Insert it at the start of the layout "
        "so it prints on the first page; its position is set for the layout's current paper size and margins."
    ),
    category=CATEGORY_FRONT,
    blocks=(
        {"type": "image", "file": "", "alt": "Logo", "placement": "front", "anchor": "page"},
    ),
    parameters=(
        ReportSnippetParameter(
            "image", "Logo", "image", ("nodes[0].file",),
            "The picture to print, from the image library. An organisation layout can use organisation images only.",
        ),
        ReportSnippetParameter(
            "alt", "Description of the logo", "text", ("nodes[0].alt",),
            "What the picture shows, read aloud to people who cannot see it, for example the organisation's name.",
            default="Logo",
        ),
    ),
    formats=("pdf", "docx", "odt"),
    layout_aware=_place_logo,
)

RECORD_IMAGES = ReportSnippet(
    key="record-images",
    name="Record images",
    description=(
        "One heading per record of a chosen type, with the pictures attached to that record printed under it "
        "(up to five, captioned with the file name)."
    ),
    category=CATEGORY_IMAGES,
    blocks=(
        {
            "type": "each", "source": {"record_type": "", "sort": [{"field": "code"}]}, "as": "rec",
            "empty_text": "None recorded.",
            "children": [
                heading("{{rec.code}} {{rec.title}}", 3),
                {
                    "type": "record_images", "max_count": 5, "caption_source": "file_name", "width": 10, "width_unit": "cm",
                    "empty_text": "No pictures attached.",
                },
            ],
        },
    ),
    parameters=(
        ReportSnippetParameter(
            "record_type", "Records", "record_type", ("nodes[0].source.record_type",),
            "The kind of record whose attached pictures print. Only kinds whose attachments a report can print are offered.",
            record_types="attachments",
        ),
    ),
)

DOCUMENT_CONTROL = ReportSnippet(
    key="document-control",
    name="Document control",
    description="A short list of the document's title, project, version and date, with lines to fill in the owner and status.",
    category=CATEGORY_FRONT,
    blocks=(
        heading("Document control", 2),
        text(
            "- **Document:** {{report_title}}\n"
            "- **Project:** {{project_name}} ({{project_code}})\n"
            "- **Organisation:** {{organisation}}\n"
            "- **Version:** {{layout_version}}\n"
            "- **Date:** {{generated_on}}\n"
            "- **Owner:** \\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\n"
            "- **Status:** \\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_"
        ),
    ),
)

APPROVALS = ReportSnippet(
    key="approvals",
    name="Approvals",
    description="A signature block: who prepared, reviewed and approved the document, with lines for a name, role and date to be completed by hand.",
    category=CATEGORY_APPROVALS,
    blocks=(
        heading("Approvals", 2),
        text("The people below have prepared, reviewed and approved this document."),
        text(
            "- **Prepared by** (name, role, date): \\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\n"
            "- **Reviewed by** (name, role, date): \\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\n"
            "- **Approved by** (name, role, date): \\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_"
        ),
    ),
)

LANDSCAPE_TABLE = ReportSnippet(
    key="landscape-table-section",
    name="Landscape table section",
    description="A table of one kind of record on landscape pages of its own, then the report returns to its own page style on a new page.",
    category=CATEGORY_TABLES,
    blocks=(
        {
            "type": "section", "page_style": "Landscape",
            "children": [
                heading("Records", 2),
                {
                    "type": "table", "source": {"record_type": "", "sort": [{"field": "code"}]},
                    "columns": [
                        {"field": "code", "label": "Code"}, {"field": "title", "label": "Title"}, {"field": "status", "label": "Status"},
                    ],
                    "empty_text": "None recorded.",
                },
            ],
        },
    ),
    root={"page_styles": [{"name": "Landscape", "orientation": "landscape"}]},
    parameters=(
        ReportSnippetParameter(
            "record_type", "Records", "record_type", ("nodes[0].children[1].source.record_type",),
            "The kind of record listed in the table. Add or remove columns afterwards in the table block.",
        ),
        ReportSnippetParameter(
            "heading", "Heading", "text", ("nodes[0].children[0].text",), "The heading printed above the table.",
            default="Records", max_length=200,
        ),
    ),
)

CORE_REPORT_SNIPPETS: tuple[ReportSnippet, ...] = (
    COVER_PAGE, LOGO_TOP_RIGHT, DOCUMENT_CONTROL, RECORD_IMAGES, LANDSCAPE_TABLE, APPROVALS,
)
"""Every built-in snippet, in the order the picker lists them within a category."""

__all__ = ["CORE_REPORT_SNIPPETS"]
