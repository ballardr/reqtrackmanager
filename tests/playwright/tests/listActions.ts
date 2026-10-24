import { expect, type Locator, type Page } from "@playwright/test";

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
 * Opens the menu and clicks one item.
 *
 * @param page The page showing the list.
 * @param item The item's accessible name, e.g. "Export as CSV" or "Import from CSV".
 * @param kind For a list showing several record kinds, the heading the item sits under (e.g. "Stakeholders").
 */
export async function chooseListAction(page: Page, item: string, kind?: string): Promise<void> {
  const menu = await openListMenu(page);
  if (!kind) {
    await menu.getByRole("menuitem", { name: item, exact: true }).click();
    return;
  }
  await menu
    .getByText(kind, { exact: true })
    .locator(`xpath=following-sibling::button[@role='menuitem' and normalize-space(.)='${item}'][1]`)
    .click();
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
