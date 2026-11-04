/**
 * Module: utils/reportFormatChoice
 *
 * Which report format a download starts on: the one the person last downloaded, else PDF, else the report's first.
 * Kept apart from the component so the rule is testable and the component file exports only a component.
 */

/** The `ui_preferences` key holding the format a person last downloaded a report in. */
export const REPORT_FORMAT_PREFERENCE = "report_download_format";

/**
 * The format to start on.
 *
 * @param kinds The formats the report offers, in order (at least one).
 * @param remembered The format last downloaded, or `""` for none.
 * @returns The remembered format, else PDF (no history), when offered; otherwise the report's first format.
 */
export function defaultReportFormat<K extends string>(kinds: readonly K[], remembered: string): K {
  const wanted = remembered || "pdf";
  return kinds.find((kind) => kind === wanted) ?? kinds[0];
}
