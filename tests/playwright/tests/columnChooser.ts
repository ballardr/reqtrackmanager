/**
 * Module: columnChooser
 *
 * Playwright helpers for the shared column chooser (`ColumnChooser`): the "Choose columns" button beside a list's
 * actions menu opens a dialog of checkboxes, one per optional column, and a reset to the list's default columns.
 */
import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Opens the chooser and returns its dialog.
 *
 * @param page The page showing the list.
 */
export async function openColumnChooser(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Choose columns" }).click();
  return page.getByRole("dialog", { name: "Columns" });
}

/** Closes the chooser with its own button (the reset disables itself, so focus may not be in the dialog for Escape). */
async function closeColumnChooser(page: Page, dialog: Locator): Promise<void> {
  await page.getByRole("button", { name: "Choose columns" }).click();
  await expect(dialog).toBeHidden();
}

/**
 * Shows or hides one optional column, then closes the chooser.
 *
 * @param page The page showing the list.
 * @param column The column's name in the chooser.
 * @param shown True to show it (default), false to hide it.
 */
export async function chooseColumn(page: Page, column: string, shown = true): Promise<void> {
  const dialog = await openColumnChooser(page);
  const box = dialog.getByRole("checkbox", { name: column, exact: true });
  if (shown) await box.check();
  else await box.uncheck();
  await closeColumnChooser(page, dialog);
}

/**
 * Returns the list's default columns through the chooser's reset, then closes it.
 *
 * @param page The page showing the list.
 */
export async function resetColumns(page: Page): Promise<void> {
  const dialog = await openColumnChooser(page);
  await dialog.getByRole("button", { name: "Show the default columns" }).click();
  await closeColumnChooser(page, dialog);
}
