/**
 * Module: testing/menuTree
 *
 * Story helper for the shared action menu (`ActionMenu`), whose multi-level menus are trees: only the first parent
 * starts open, and a row inside a closed parent is not in the document. A story names the row it wants and this
 * opens closed parents until it appears, so it does not depend on which group is open first.
 */
import { screen, userEvent } from "storybook/test";

/**
 * Finds a menu row by name, opening closed parent rows until it is present.
 *
 * @param name The row's accessible name (exact text) or a pattern.
 * @returns The row's element.
 * @throws Error when no amount of opening makes the row appear.
 */
export async function findMenuRow(name: string | RegExp): Promise<HTMLElement> {
  for (let guard = 0; guard < 12; guard += 1) {
    const found = screen.queryAllByRole("menuitem", { name });
    if (found.length > 0) return found[0];
    const closed = screen.queryAllByRole("menuitem", { expanded: false });
    if (closed.length === 0) break;
    await userEvent.click(closed[0]);
  }
  throw new Error(`No menu row named ${String(name)}, even with every parent opened.`);
}

/**
 * Clicks a menu row by name, opening closed parents first.
 *
 * @param name The row's accessible name or a pattern.
 */
export async function chooseMenuRow(name: string | RegExp): Promise<void> {
  await userEvent.click(await findMenuRow(name));
}
