/**
 * Module: api/reportFormats
 *
 * The one place a report file format is given a name a person reads. Every format control (the Export menu, the
 * download toast, the pack entry editor and the pack run table) goes through {@link REPORT_FORMAT}, so a label
 * cannot drift from one screen to the next. `label` is the short name shown on buttons and in lists (an acronym
 * where people use one: PDF, ODT, ODS, HTML, CSV; Word and Excel keep the name people call them by); `title` is
 * the full name, offered as a tooltip and read after the label by a screen reader.
 *
 * `scripts/check_report_format_labels.py` fails a hand-written "OpenDocument …" label outside this file.
 */
import type { ReportFileKind } from "./reports";

/** How one report file format is named. */
export interface ReportFormatName {
  /** Short name for buttons, list cells and options. */
  label: string;
  /** Full name, for a tooltip and the accessible description. */
  title: string;
}

/** The name of each report file format. */
export const REPORT_FORMAT: Record<ReportFileKind, ReportFormatName> = {
  pdf: { label: "PDF", title: "Portable Document Format" },
  docx: { label: "Word", title: "Word document" },
  odt: { label: "ODT", title: "OpenDocument text" },
  html: { label: "HTML", title: "HTML page" },
  csv: { label: "CSV", title: "Comma-separated values" },
  xlsx: { label: "Excel", title: "Excel workbook" },
  ods: { label: "ODS", title: "OpenDocument spreadsheet" },
};

/**
 * The short name of a format by its key; an unknown key is shown as it came.
 *
 * @param kind The format key (`odt`, `pdf`, …) as the server sends it.
 * @returns The label, or `kind` itself when the format is not one this map knows.
 */
export function reportFormatLabel(kind: string): string {
  return (REPORT_FORMAT as Record<string, ReportFormatName | undefined>)[kind]?.label ?? kind;
}

/**
 * The full name of a format for a tooltip, or `undefined` for an unknown key.
 *
 * @param kind The format key.
 */
export function reportFormatTitle(kind: string): string | undefined {
  return (REPORT_FORMAT as Record<string, ReportFormatName | undefined>)[kind]?.title;
}
