/**
 * Module: testing/menuRows
 *
 * Story assertion for the shared menu row style (docs/ux-style-guide.md, "Pattern: action menu"): a menu row, a link
 * in a list of destinations and an option of a listbox are plain text rows, never standard buttons. A story passes the
 * element holding the rows (the menu, the popover, the listbox) and this fails if any row is drawn as a `btn` or has a
 * border or a fill at rest.
 */
import { expect } from "storybook/test";

/**
 * Asserts that every `.menu-item` under `root` is a text row.
 *
 * @param root The element holding the rows.
 * @param minimum The fewest rows expected, so an empty list cannot pass by finding nothing.
 */
export async function expectTextRows(root: HTMLElement, minimum = 1): Promise<void> {
  const rows = Array.from(root.querySelectorAll<HTMLElement>(".menu-item"));
  await expect(rows.length).toBeGreaterThanOrEqual(minimum);
  await expect(root.querySelectorAll('[role="menuitem"].btn, [role="option"].btn, .menu-item.btn')).toHaveLength(0);
  for (const row of rows) {
    const style = getComputedStyle(row);
    await expect(style.borderTopWidth === "0px" || style.borderTopStyle === "none").toBe(true);
  }
}
