/**
 * Module: testing/listActionsMenu
 *
 * Story helper for the shared list actions: opens a list's "List actions" kebab menu and chooses an item,
 * so a story names what it does (`chooseExport(canvas, "CSV")`) and not how the menu is built.
 */
import { userEvent, within } from "storybook/test";

const MENU_NAME = "List actions";

/**
 * Opens the menu and returns it for queries; a menu that is already open is returned as it is.
 *
 * @param canvas The story's canvas (the menu's trigger is inside it).
 */
export async function openListMenu(canvas: ReturnType<typeof within>): Promise<ReturnType<typeof within>> {
  const open = within(document.body).queryByRole("dialog", { name: MENU_NAME });
  if (open) return within(open);
  await userEvent.click(await canvas.findByRole("button", { name: MENU_NAME }));
  return within(await within(document.body).findByRole("dialog", { name: MENU_NAME }));
}

/** The parent that lists the download formats. */
const DOWNLOAD_SHOWN = "Download shown items";

/**
 * Opens a parent row of the menu tree when it is closed (the first parent starts open), and returns the group of rows under it.
 *
 * @param scope The part of the menu to look in.
 * @param name The parent row's accessible name.
 */
async function expandParent(scope: ReturnType<typeof within>, name: string): Promise<ReturnType<typeof within>> {
  const parent = scope.getByRole("menuitem", { name });
  if (parent.getAttribute("aria-expanded") !== "true") await userEvent.click(parent);
  return within(await within(document.body).findByRole("group", { name }));
}

/**
 * Finds a first-level item, under a record kind's group when the list shows several kinds.
 *
 * @param menu The open menu.
 * @param item The item's accessible name.
 * @param kind The group the item sits under, if any.
 */
async function findItem(menu: ReturnType<typeof within>, item: string, kind?: string): Promise<HTMLElement> {
  if (!kind) return menu.getByRole("menuitem", { name: item });
  return (await expandParent(menu, kind)).getByRole("menuitem", { name: item });
}

/**
 * Opens the menu, then Download shown items, and clicks one format.
 *
 * @param canvas The story's canvas (the menu's trigger is inside it).
 * @param format The format's name as the list shows it: "CSV", "PDF", "Word", "ODT" or "ODS".
 * @param kind For a list showing several record kinds, the group the item sits under (e.g. "Stakeholders").
 */
export async function chooseExport(canvas: ReturnType<typeof within>, format: string, kind?: string): Promise<void> {
  const menu = await openListMenu(canvas);
  const scope = kind ? await expandParent(menu, kind) : menu;
  const formats = await expandParent(scope, DOWNLOAD_SHOWN);
  await userEvent.click(formats.getByRole("menuitem", { name: new RegExp(`^${format}( |$)`) }));
}

/**
 * Opens the menu and clicks one item.
 *
 * @param canvas The story's canvas (the menu's trigger is inside it).
 * @param item The item's accessible name, e.g. "Download report" or "Import from CSV".
 * @param kind For a list showing several record kinds, the group the item sits under (e.g. "Stakeholders").
 */
export async function chooseListAction(canvas: ReturnType<typeof within>, item: string, kind?: string): Promise<void> {
  const menu = await openListMenu(canvas);
  await userEvent.click(await findItem(menu, item, kind));
}
