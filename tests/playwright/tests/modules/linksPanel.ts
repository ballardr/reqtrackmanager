/**
 * Shared Playwright helper for the Links panel's "Add link" control.
 *
 * "Add link" is a menu (Link an existing record, Create a new record) once a record type can be created from the
 * page's record, and a plain button before that or where none can; a spec that only wants the "Add a link" dialog
 * goes through `openAddLinkDialog` so it passes in both shapes.
 */
import type { Locator, Page } from "@playwright/test";

/**
 * Opens the "Add a link" dialog from the panel's "Add link" control.
 *
 * @param page The page the panel is on.
 * @param panel The locator that contains the panel (the Links region, or a card holding a compact panel).
 */
export async function openAddLinkDialog(page: Page, panel: Locator): Promise<void> {
  await panel.getByRole("button", { name: "Add link" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a link" });
  const existing = page.getByRole("menuitem", { name: "Link an existing record" });
  await dialog.or(existing).first().waitFor();
  if (await existing.isVisible()) await existing.click();
}
