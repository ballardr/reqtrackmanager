import { type Locator, type Page, expect } from "@playwright/test";

/**
 * Drives the Reports page's picker (`ReportPicker`): a button naming the current report that opens a dialog with
 * search, a type filter, favourites and folders. Specs go through these helpers so a change to the picker's markup is
 * made once.
 */

/** The button that shows the current report and opens the dialog. */
export function reportPickerButton(page: Page): Locator {
  return page.getByRole("button", { name: /^Report:/ });
}

/** The open picker dialog. */
export function reportPickerDialog(page: Page): Locator {
  return page.getByRole("dialog", { name: "Choose a report" });
}

/** The title of the current report (the picker button's name, without its "Report: " prefix). */
export async function currentReportTitle(page: Page): Promise<string> {
  const name = (await reportPickerButton(page).getAttribute("aria-label")) ?? "";
  return name.replace(/^Report: /, "");
}

/** Opens the dialog and returns it. */
export async function openReportPicker(page: Page): Promise<Locator> {
  await reportPickerButton(page).click();
  const dialog = reportPickerDialog(page);
  await expect(dialog).toBeVisible();
  return dialog;
}

/** Opens every folder in the dialog, however deeply nested. */
async function expandAllFolders(dialog: Locator): Promise<void> {
  for (let guard = 0; guard < 50; guard += 1) {
    const closed = dialog.getByRole("button", { name: /^Expand / });
    if ((await closed.count()) === 0) return;
    await closed.first().click();
  }
}

/** The title of every report the picker offers (opens every folder, reads the titles and closes the dialog). */
export async function listReports(page: Page): Promise<string[]> {
  const dialog = await openReportPicker(page);
  await expandAllFolders(dialog);
  const titles = await dialog.locator("button[data-report-picker-item]").evaluateAll(
    (buttons) => buttons.map((b) => (b.querySelector("span > span") ?? b).textContent ?? ""),
  );
  await page.keyboard.press("Escape");
  const unique = [...new Set(titles.map((t) => t.trim()).filter((t) => t !== ""))];
  // An empty list means the helper missed the picker's markup, not that no report is offered: never let a "none of these" check pass on it.
  expect(unique.length, "the picker lists at least one report").toBeGreaterThan(0);
  return unique;
}

/** Chooses a report by its title, searching so the folder it is filed in does not matter. */
export async function chooseReport(page: Page, title: string): Promise<void> {
  const dialog = await openReportPicker(page);
  await dialog.getByRole("textbox", { name: "Search reports" }).fill(title);
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  await dialog.getByRole("button", { name: new RegExp(`^${escaped}( |$)`) }).first().click();
  await expect(reportPickerButton(page)).toHaveAttribute("aria-label", `Report: ${title}`);
}

/** Whether the picker offers a report with this title. */
export async function offersReport(page: Page, title: string): Promise<boolean> {
  return (await listReports(page)).includes(title);
}
