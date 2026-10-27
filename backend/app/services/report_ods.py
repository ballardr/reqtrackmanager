"""
Module: services.report_ods

Renders the `Sheet`s of a table-family report to an OpenDocument Spreadsheet (ODS) file: the ODS counterpart of
the XLSX renderer in `report_render`, with the same content and safety.

Each sheet is a tab with a bold header row (repeated when printed, frozen on screen) and sized columns.

Design decisions:
- **Cells are text.** Every cell is a `string` value (`office:value-type="string"`) with no `table:formula`
  attribute, so a spreadsheet never evaluates it whatever it looks like; the caller has already put a value that
  starts with `=`, `+`, `-`, `@`, tab or CR through `csv_safe` and cut it at the cell limit.
- **Streamed.** The rows are written to the zip a few hundred at a time, so a background run of several hundred
  thousand rows is proportional to the size of the file, not to a tree of cell objects (`report_odf`).
- Sheet names arrive already cleaned and unique (`report_render.unique_names`); they are escaped here as
  attributes in any case.
- The frozen header is a view setting in `settings.xml`; a reader that ignores it still shows every row.

Dependencies: `services.report_odf` (package, escaping), `services.csv_safety`, `services.report_model`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from app.services.csv_safety import csv_safe
from app.services.report_model import Sheet
from app.services.report_odf import (
    FONT_FACES,
    MIME_ODS,
    ODF_VERSION,
    XML_DECLARATION,
    OdfPackage,
    length_cm,
    namespace_attrs,
    xml_attr,
    xml_text,
)

_ROWS_PER_CHUNK = 500
_CM_PER_CHARACTER = 0.19
_SIZED_ROWS = 200


def _cell(value: str, max_chars: int, style: str = "") -> str:
    """One text cell: guarded against formulas and cut at `max_chars`; an empty value is an empty cell."""
    text = csv_safe(value)[:max_chars]
    attr = f' table:style-name="{style}"' if style else ""
    if not text:
        return f"<table:table-cell{attr}/>"
    return f'<table:table-cell office:value-type="string"{attr}><text:p>{xml_text(text)}</text:p></table:table-cell>'


def _column_width_cm(sheet: Sheet, index: int) -> float:
    widest = max([len(sheet.columns[index]), *(len(row[index]) for row in sheet.rows[:_SIZED_ROWS] if index < len(row))])
    return min(max(widest + 2, 8), 60) * _CM_PER_CHARACTER


def _content(sheets: Sequence[Sheet], names: Sequence[str], max_chars: int) -> Iterator[str]:
    """`content.xml` as text chunks."""
    column_styles = [
        f'<style:style style:name="co{s}_{c}" style:family="table-column">'
        f'<style:table-column-properties style:column-width="{length_cm(_column_width_cm(sheet, c))}"/></style:style>'
        for s, sheet in enumerate(sheets) for c in range(len(sheet.columns))
    ]
    yield (
        f'{XML_DECLARATION}<office:document-content {namespace_attrs("office", "style", "text", "table", "fo", "svg")} '
        f'office:version="{ODF_VERSION}">{FONT_FACES}<office:automatic-styles>{"".join(column_styles)}'
        '<style:style style:name="ce_hdr" style:family="table-cell"><style:text-properties fo:font-weight="bold"/></style:style>'
        "</office:automatic-styles><office:body><office:spreadsheet>"
    )
    for s, (sheet, name) in enumerate(zip(sheets, names, strict=True)):
        columns = "".join(f'<table:table-column table:style-name="co{s}_{c}"/>' for c in range(len(sheet.columns)))
        header = "".join(_cell(column, max_chars, "ce_hdr") for column in sheet.columns)
        yield (
            f"<table:table table:name={xml_attr(name)}>{columns}"
            f"<table:table-header-rows><table:table-row>{header}</table:table-row></table:table-header-rows>"
        )
        for start in range(0, len(sheet.rows), _ROWS_PER_CHUNK):
            yield "".join(
                f"<table:table-row>{''.join(_cell(value, max_chars) for value in row)}</table:table-row>"
                for row in sheet.rows[start:start + _ROWS_PER_CHUNK]
            )
        yield "</table:table>"
    yield "</office:spreadsheet></office:body></office:document-content>"


def _settings(names: Sequence[str]) -> str:
    """`settings.xml`: freeze the header row of every sheet."""
    def item(name: str, kind: str, value: int) -> str:
        return f'<config:config-item config:name="{name}" config:type="{kind}">{value}</config:config-item>'

    entries = "".join(
        f"<config:config-item-map-entry config:name={xml_attr(name)}>"
        + item("HorizontalSplitMode", "short", 0) + item("VerticalSplitMode", "short", 2)
        + item("HorizontalSplitPosition", "int", 0) + item("VerticalSplitPosition", "int", 1)
        + item("ActiveSplitRange", "short", 2) + item("PositionLeft", "int", 0) + item("PositionRight", "int", 0)
        + item("PositionTop", "int", 0) + item("PositionBottom", "int", 1)
        + "</config:config-item-map-entry>"
        for name in names
    )
    return (
        f'{XML_DECLARATION}<office:document-settings {namespace_attrs("office", "config")} office:version="{ODF_VERSION}">'
        '<office:settings><config:config-item-set config:name="ooo:view-settings">'
        '<config:config-item-map-indexed config:name="Views"><config:config-item-map-entry>'
        '<config:config-item config:name="ViewId" config:type="string">view1</config:config-item>'
        f'<config:config-item-map-named config:name="Tables">{entries}</config:config-item-map-named>'
        "</config:config-item-map-entry></config:config-item-map-indexed></config:config-item-set></office:settings>"
        "</office:document-settings>"
    )


def render_ods_workbook(title: str, sheets: Sequence[Sheet], names: Sequence[str], *, max_cell_chars: int) -> bytes:
    """Renders `sheets` as an ODS workbook.

    Args:
        title: The report title (file metadata).
        sheets: The sheets, in tab order.
        names: Each sheet's tab name: cleaned, unique and one per sheet.
        max_cell_chars: Longest text kept in a cell.

    Returns:
        ODS bytes; a report with no sheet gets one empty sheet.
    """
    if not sheets:
        sheets, names = [Sheet("Sheet", [], [])], ["Sheet"]
    package = OdfPackage(MIME_ODS, title)
    package.add("content.xml", "text/xml", _content(sheets, names, max_cell_chars))
    package.add("settings.xml", "text/xml", _settings(names))
    return package.finish()


__all__ = ["render_ods_workbook"]
