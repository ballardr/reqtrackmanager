import { expect, type Page, test } from "@playwright/test";

import { addDefinition, loginAs, PERSONAS, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: a project's requirement-action types (Review, Test, ...) support the same
 * add/rename/reorder/delete-with-reassignment contract as every other definition list, project-scoped like custom
 * fields. Covers: an unused type deletes immediately with no reassignment prompt; a type used by a real action
 * returns 409 and requires a reassignment target; and once only one type remains, its delete control is disabled
 * rather than offered and rejected.
 *
 * Creates its own per-run project through the UI: the test permanently deletes one of the two default action types
 * (Review, reassigning its use to Test) to reach "only one left", so a shared seeded project would lack "Review" on
 * the second run. Every new project is seeded with a fresh Review/Test pair (`definitions.py`'s
 * `DEFAULT_ACTION_TYPES`); the project is left behind, as in role-display-collapsing.spec.ts.
 */

/** Action type/status/link-type names render as editable `<input>` value
 * attributes (the rename form), not plain text nodes — matches
 * project-admin-structural.spec.ts's own convention. */
function inputWithValue(page: Page, value: string) {
  // `:not([placeholder])`: the "add a new action type" row's own input
  // shares the `input.input` class and can transiently hold the same text
  // the test just typed into it — only a *rename* input for an existing
  // row is ever placeholder-less.
  return page.locator(`input.input[value="${value}"]:not([placeholder])`);
}

test.describe("project admin: action types", () => {
  test("add, rename, delete-unused, delete-in-use-with-reassignment, and last-remaining-blocked", async ({ page }) => {
    const projectName = `E2E Action Types ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await test.step("create a dedicated project for this run — see the module docstring for why this test doesn't reuse a shared seeded project", async () => {
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.getByLabel("Name", { exact: true }).fill(projectName);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
    });
    await page.getByRole("link", { name: "Project admin", exact: true }).click();
    // Action types sit in the merged "Fields & actions" tab beside Custom Fields; the two-select ("Name"-exact)
    // locators below stay unambiguous since Custom Fields has no "Name"-exact field itself.
    await selectProjectAdminGroup(page, "Fields & actions");

    await test.step("Review and Test are seeded by default", async () => {
      await expect(inputWithValue(page, "Review")).toBeVisible();
      await expect(inputWithValue(page, "Test")).toBeVisible();
    });

    await test.step("add a new action type, then rename it", async () => {
      await addDefinition(page, "New action type", { Name: "E2E Inspection" });
      await expect(inputWithValue(page, "E2E Inspection")).toBeVisible();

      await inputWithValue(page, "E2E Inspection").fill("E2E Inspection v2");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(inputWithValue(page, "E2E Inspection v2")).toBeVisible();
      await expect(inputWithValue(page, "E2E Inspection")).toHaveCount(0);
    });

    await test.step("delete the unused new type immediately, no reassignment prompt", async () => {
      const row = inputWithValue(page, "E2E Inspection v2").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await row.getByTitle("Delete this action type").click();
      await expect(inputWithValue(page, "E2E Inspection v2")).toHaveCount(0);
      // A plain, unused delete never opens the in-use dialog.
      await expect(page.getByRole("dialog")).toHaveCount(0);
    });

    await test.step("create an action of type Review, making it 'in use'", async () => {
      await page.getByRole("link", { name: "Actions", exact: true }).click();
      await page.getByRole("button", { name: /New action/ }).click();
      await page.getByLabel("Title").fill("E2E Action Type Test");
      await page.getByRole("dialog", { name: "New action" }).getByLabel("Type", { exact: true }).selectOption({ label: "Review" });
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByText("E2E Action Type Test")).toBeVisible();
    });

    await test.step("deleting Review now 409s and opens the in-use dialog", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Fields & actions");
      const reviewRow = inputWithValue(page, "Review").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await reviewRow.getByTitle("Delete this action type").click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByText(/used by 1 action\(s\)/)).toBeVisible();
      await dialog.getByRole("combobox", { name: "Reassign existing items to" }).selectOption({ label: "Test" });
      await dialog.getByRole("button", { name: "Confirm delete" }).click();
      await expect(inputWithValue(page, "Review")).toHaveCount(0);
    });

    await test.step("the reassigned action now shows type Test", async () => {
      await page.getByRole("link", { name: "Actions", exact: true }).click();
      await page.getByText("E2E Action Type Test").click();
      await expect(page.getByRole("region", { name: "Details" }).getByLabel("Type", { exact: true }).locator("option:checked")).toHaveText("Test");
    });

    await test.step("with only Test remaining, its delete control is disabled", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Fields & actions");
      await expect(inputWithValue(page, "Test")).toBeVisible();
      await expect(page.getByTitle("This is the only one — create another first so there is something to reassign to.")).toBeDisabled();
    });
  });
});
