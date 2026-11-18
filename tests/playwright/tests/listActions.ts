import { expect, type Locator, type Page } from "@playwright/test";

import { clickMenuRow, openMenuParent } from "./menuTree";

/**
 * Opens a list's "List actions" kebab menu and returns it.
 *
 * @param page The page showing the list.
 */
export async function openListMenu(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "List actions", exact: true }).click();
  return page.getByRole("dialog", { name: "List actions" });
}

/**
 * Opens the menu, then Download shown items, and clicks one format.
 *
 * @param page The page showing the list.
 * @param format The format's name as the list shows it: "CSV", "PDF", "Word", "ODT" or "ODS".
 * @param kind For a list showing several record kinds, the group the item sits under (e.g. "Stakeholders").
 */
export async function chooseExport(page: Page, format: string, kind?: string): Promise<void> {
  const menu = await openListMenu(page);
  const scope = kind ? await openMenuParent(page, kind, menu) : menu;
  const formats = await openMenuParent(page, "Download shown items", scope);
  await formats.getByRole("menuitem", { name: new RegExp(`^${format}( |$)`) }).click();
}

/**
 * Opens the menu and clicks one item.
 *
 * @param page The page showing the list.
 * @param item The item's accessible name, e.g. "Download report" or "Import from CSV".
 * @param kind For a list showing several record kinds, the group the item sits under (e.g. "Stakeholders").
 */
export async function chooseListAction(page: Page, item: string, kind?: string): Promise<void> {
  const menu = await openListMenu(page);
  const scope = kind ? await openMenuParent(page, kind, menu) : menu;
  await clickMenuRow(page, item, scope);
}

/**
 * Asserts the menu does (or does not) offer an item, then closes it.
 *
 * @param page The page showing the list.
 * @param item The item's accessible name, e.g. "Import from CSV".
 * @param present False to assert the item is not offered.
 */
export async function expectListAction(page: Page, item: string, present = true): Promise<void> {
  const menu = await openListMenu(page);
  await expect(menu.getByRole("menuitem", { name: item, exact: true })).toHaveCount(present ? 1 : 0);
  await page.keyboard.press("Escape");
}
