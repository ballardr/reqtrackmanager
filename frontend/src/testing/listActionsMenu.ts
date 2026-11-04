/**
 * Module: testing/listActionsMenu
 *
 * Story helper for the shared list actions: opens a list's "List actions" kebab menu and chooses an item,
 * so a story names what it does (`chooseExport(canvas, "CSV")`) and not how the menu is built.
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

/** The submenu parent that lists the download formats. */
const DOWNLOAD_SHOWN = "Download shown items";

/**
 * Finds a first-level item, under a record kind's heading when the list shows several kinds.
 *
 * @param menu The open menu.
 * @param item The item's accessible name.
 * @param kind The heading the item sits under, if any.
 */
function findItem(menu: ReturnType<typeof within>, item: string, kind?: string): HTMLElement {
  if (!kind) return menu.getByRole("menuitem", { name: item });
  let sibling: Element | null = menu.getByText(kind, { selector: ".menu-group-label" }).nextElementSibling;
  while (sibling && !sibling.classList.contains("menu-group-label")) {
    const button: Element | null = sibling.classList.contains("menu-submenu-host") ? sibling.querySelector(':scope > [role="menuitem"]') : sibling;
    if (button?.getAttribute("role") === "menuitem" && button.textContent?.trim() === item) return button as HTMLElement;
    sibling = sibling.nextElementSibling;
  }
  throw new Error(`No "${item}" item under "${kind}" in the ${MENU_NAME} menu.`);
}

/**
 * Opens the menu, then Download shown items, and clicks one format.
 *
 * @param canvas The story's canvas (the menu's trigger is inside it).
 * @param format The format's name as the submenu shows it: "CSV", "PDF", "Word", "ODT" or "ODS".
 * @param kind For a list showing several record kinds, the heading the item sits under (e.g. "Stakeholders").
 */
export async function chooseExport(canvas: ReturnType<typeof within>, format: string, kind?: string): Promise<void> {
  const menu = await openListMenu(canvas);
  await userEvent.click(findItem(menu, DOWNLOAD_SHOWN, kind));
  const submenu = within(await within(document.body).findByRole("menu", { name: DOWNLOAD_SHOWN }));
  await userEvent.click(submenu.getByRole("menuitem", { name: new RegExp(`^${format}( |$)`) }));
}

/**
 * Opens the menu and clicks one item.
 *
 * @param canvas The story's canvas (the menu's trigger is inside it).
 * @param item The item's accessible name, e.g. "Download report" or "Import from CSV".
 * @param kind For a list showing several record kinds, the heading the item sits under (e.g. "Stakeholders").
 */
export async function chooseListAction(canvas: ReturnType<typeof within>, item: string, kind?: string): Promise<void> {
  const menu = await openListMenu(canvas);
  await userEvent.click(findItem(menu, item, kind));
}
