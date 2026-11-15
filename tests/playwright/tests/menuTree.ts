/**
 * Module: menuTree
 *
 * Playwright helper for the shared action menu (`ActionMenu`), whose multi-level menus are trees: an item with
 * children, or a run of items sharing a group, is a parent row that opens in place, and only the first parent
 * starts open. A row inside a closed parent is not in the page, so a spec names the row it wants and this opens
 * parents until it appears, never assuming which group is open.
 */
import type { Locator, Page } from "@playwright/test";

/**
 * Finds a menu row by name, opening closed parent rows until it is present.
 *
 * @param page The page with the menu open.
 * @param name The row's accessible name (string, exact) or a pattern.
 * @param within Limits the search to part of the menu, e.g. one parent's group; the whole page by default.
 * @returns The row's locator (not yet clicked).
 * @throws Error when no amount of opening makes the row appear.
 */
export async function menuRow(page: Page, name: string | RegExp, within?: Locator): Promise<Locator> {
  const scope = within ?? page;
  const row = scope.getByRole("menuitem", typeof name === "string" ? { name, exact: true } : { name });
  for (let guard = 0; guard < 12; guard += 1) {
    if ((await row.count()) > 0) return row.first();
    const closed = scope.getByRole("menuitem", { expanded: false });
    if ((await closed.count()) === 0) break;
    await closed.first().click();
  }
  throw new Error(`No menu row named ${String(name)} in the open menu, even with every parent opened.`);
}

/**
 * Clicks a menu row by name, opening closed parents first.
 *
 * @param page The page with the menu open.
 * @param name The row's accessible name or a pattern.
 * @param within Limits the search to part of the menu.
 */
export async function clickMenuRow(page: Page, name: string | RegExp, within?: Locator): Promise<void> {
  await (await menuRow(page, name, within)).click();
}

/**
 * Opens a parent row if it is closed and returns the group of rows under it.
 *
 * @param page The page with the menu open.
 * @param name The parent row's accessible name.
 * @param within Limits the search to part of the menu.
 */
export async function openMenuParent(page: Page, name: string, within?: Locator): Promise<Locator> {
  const parent = await menuRow(page, name, within);
  if ((await parent.getAttribute("aria-expanded")) !== "true") await parent.click();
  return (within ?? page).getByRole("group", { name, exact: true });
}
