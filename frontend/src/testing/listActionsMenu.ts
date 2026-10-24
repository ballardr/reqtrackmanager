/**
 * Module: testing/listActionsMenu
 *
 * Story helper for the shared list actions: opens a list's "List actions" kebab menu and chooses an item,
 * so a story names what it does ("Export as CSV") and not how the menu is built.
 */
import { userEvent, within } from "storybook/test";

const MENU_NAME = "List actions";

/**
 * Opens the menu and returns it for queries.
 *
 * @param canvas The story's canvas (the menu's trigger is inside it).
 */
export async function openListMenu(canvas: ReturnType<typeof within>): Promise<ReturnType<typeof within>> {
  await userEvent.click(await canvas.findByRole("button", { name: MENU_NAME }));
  return within(await within(document.body).findByRole("dialog", { name: MENU_NAME }));
}

/**
 * Opens the menu and clicks one item.
 *
 * @param canvas The story's canvas (the menu's trigger is inside it).
 * @param item The item's accessible name, e.g. "Export as CSV" or "Import from CSV".
 * @param kind For a list showing several record kinds, the heading the item sits under (e.g. "Stakeholders").
 */
export async function chooseListAction(canvas: ReturnType<typeof within>, item: string, kind?: string): Promise<void> {
  const menu = await openListMenu(canvas);
  if (!kind) {
    await userEvent.click(menu.getByRole("menuitem", { name: item }));
    return;
  }
  let sibling = menu.getByText(kind, { selector: ".menu-group-label" }).nextElementSibling;
  while (sibling && !sibling.classList.contains("menu-group-label")) {
    if (sibling.getAttribute("role") === "menuitem" && sibling.textContent?.trim() === item) {
      await userEvent.click(sibling);
      return;
    }
    sibling = sibling.nextElementSibling;
  }
  throw new Error(`No "${item}" item under "${kind}" in the ${MENU_NAME} menu.`);
}
