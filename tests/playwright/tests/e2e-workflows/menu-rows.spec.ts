import { expect, type Locator, test } from "@playwright/test";

import { loginAs, openProject, PERSONAS, PROJECT_NAMES } from "./helpers";
import { openListMenu } from "../listActions";

/**
 * Job to be done: every menu in the product reads as a list of plain text rows (no bordered button boxes), a
 * multi-level menu is a tree, and every menu closes on a click outside it, on Escape and on Tab, returning focus to
 * its trigger. One representative of each family is checked: the split-button alternatives list on the Projects page
 * and the List actions menu (a tree) on the Requirements list.
 */

/** Asserts a row has no border at rest, so it is a text row and not a standard button. */
async function expectTextRow(row: Locator): Promise<void> {
  await expect(row).toBeVisible();
  const border = await row.evaluate((el) => getComputedStyle(el).borderTopWidth);
  expect(border).toBe("0px");
  await expect(row).not.toHaveClass(/\bbtn\b/);
}

test.describe("menu rows across the app", () => {
  test("the split button's alternatives are text rows and the list closes by every route", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    const chevron = page.getByRole("button", { name: "More options" });

    await test.step("the alternative is a text row", async () => {
      await chevron.click();
      await expectTextRow(page.getByRole("menuitem", { name: "Import project" }));
    });

    await test.step("Escape closes it and returns focus to the chevron", async () => {
      await page.keyboard.press("Escape");
      await expect(page.getByRole("menuitem", { name: "Import project" })).toHaveCount(0);
      await expect(chevron).toBeFocused();
    });

    await test.step("a click outside closes it", async () => {
      await chevron.click();
      await expect(page.getByRole("menuitem", { name: "Import project" })).toBeVisible();
      await page.getByRole("heading", { level: 1 }).click();
      await expect(page.getByRole("menuitem", { name: "Import project" })).toHaveCount(0);
    });

    await test.step("Tab closes it", async () => {
      await chevron.click();
      await page.getByRole("menuitem", { name: "Import project" }).focus();
      await page.keyboard.press("Tab");
      await expect(page.getByRole("menuitem", { name: "Import project" })).toHaveCount(0);
    });
  });

  test("the List actions menu is a tree of text rows that opens and closes by keyboard and click", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    const trigger = page.getByRole("button", { name: "List actions", exact: true });
    const menu = await openListMenu(page);

    await test.step("every row is a text row, and a parent row expands in place", async () => {
      const rows = menu.getByRole("menuitem");
      await expect(rows.first()).toBeVisible();
      for (const row of await rows.all()) await expectTextRow(row);
      const parent = menu.getByRole("menuitem", { name: "Download shown items", exact: true });
      await parent.focus();
      await page.keyboard.press("ArrowRight");
      await expect(parent).toHaveAttribute("aria-expanded", "true");
      await expect(menu.getByRole("group", { name: "Download shown items" })).toBeVisible();
    });

    await test.step("Escape closes the open level first, then the menu, and focus returns to the trigger", async () => {
      await page.keyboard.press("Escape");
      await expect(menu.getByRole("menuitem", { name: "Download shown items", exact: true })).toHaveAttribute("aria-expanded", "false");
      await page.keyboard.press("Escape");
      await expect(menu).toHaveCount(0);
      await expect(trigger).toBeFocused();
    });

    await test.step("a click outside closes the menu", async () => {
      await openListMenu(page);
      await page.getByRole("heading", { level: 1 }).click();
      await expect(page.getByRole("dialog", { name: "List actions" })).toHaveCount(0);
    });
  });
});
