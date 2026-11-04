/**
 * Module: tests/reportDownload
 *
 * Playwright helpers for the report download step (`ReportFormatDownload`): the report's formats are a radio list
 * with one Download button, so a spec chooses a format and presses Download instead of opening an Export menu.
 *
 * Responsibilities: choose a format by the name a person reads (`PDF`, `Word`, `CSV` ...); a report offering one
 * format has no list, so choosing is skipped; locate the Download button.
 */
import type { Locator, Page } from "@playwright/test";

/**
 * Chooses a format in the download list.
 *
 * @param scope The page (or a dialog) holding the list.
 * @param format The format's name as shown (`REPORT_FORMAT` label: PDF, Word, ODT, HTML, CSV, Excel, ODS).
 */
export async function pickReportFormat(scope: Page | Locator, format: string): Promise<void> {
  const radio = scope.getByRole("radio", { name: format, exact: true });
  if (await radio.count()) await radio.check();
}

/**
 * The report's Download button.
 *
 * @param scope The page (or a dialog) holding it.
 */
export function reportDownloadButton(scope: Page | Locator): Locator {
  return scope.getByRole("button", { name: "Download", exact: true });
}
