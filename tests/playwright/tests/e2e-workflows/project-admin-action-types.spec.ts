import { expect, type Page, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: a project's requirement-action types (Review, Test, ...)
 * support the same add/rename/reorder/delete-with-reassignment contract as
 * every other definition list in this codebase (§4.0 of the traceability
 * plan) — project-scoped rather than org-scoped, matching custom fields.
 * Covers: a brand-new, unused type deletes immediately with no reassignment
 * prompt; a type currently used by a real action 409s and requires an
 * explicit reassignment target; and once only one type remains, its delete
 * control is disabled outright rather than offered and rejected.
 *
 * Uses Beta-1 (not touched by any other admin-list spec in this suite), and
 * creates its own action there to exercise the "in use" path, rather than
 * touching Alpha-1's fixed Review/Test action fixtures that
 * requirement-actions.spec.ts and requirement-links.spec.ts depend on.
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
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.beta1).click();
    await page.getByRole("link", { name: "Project admin", exact: true }).click();
    // Action types now lives inside the merged "Fields & actions" tab
    // (2026-08 UX audit roadmap: Project Admin's 8 tabs -> 5), alongside
    // Custom Fields — the two-select ("Name"-exact) locators below stay
    // unambiguous since Custom Fields has no "Name"-exact field itself.
    await page.getByRole("tab", { name: "Fields & actions" }).click();

    await test.step("Review and Test are seeded by default", async () => {
      await expect(inputWithValue(page, "Review")).toBeVisible();
      await expect(inputWithValue(page, "Test")).toBeVisible();
    });

    await test.step("add a new action type, then rename it", async () => {
      await page.getByPlaceholder("Name", { exact: true }).fill("E2E Inspection");
      await page.getByRole("button", { name: /New action type/ }).click();
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
      // A plain, unused delete never shows the reassignment picker.
      await expect(page.getByText("Reassign existing items to")).toHaveCount(0);
    });

    await test.step("create an action of type Review, making it 'in use'", async () => {
      await page.getByRole("link", { name: "Actions", exact: true }).click();
      await page.getByRole("button", { name: /New action/ }).click();
      await page.getByPlaceholder("Title").fill("E2E Action Type Test");
      await page.getByLabel("Type", { exact: true }).selectOption({ label: "Review" });
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByText("E2E Action Type Test")).toBeVisible();
    });

    await test.step("deleting Review now 409s and opens the reassignment picker", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Fields & actions" }).click();
      const reviewRow = inputWithValue(page, "Review").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await reviewRow.getByTitle("Delete this action type").click();
      await expect(page.getByText(/used by 1 action\(s\)/)).toBeVisible();
      await page.getByText("Reassign existing items to").locator("xpath=..").getByRole("combobox").selectOption({ label: "Test" });
      await page.getByRole("button", { name: "Confirm delete" }).click();
      await expect(inputWithValue(page, "Review")).toHaveCount(0);
    });

    await test.step("the reassigned action now shows type Test", async () => {
      await page.getByRole("link", { name: "Actions", exact: true }).click();
      await page.getByText("E2E Action Type Test").click();
      await expect(page.getByLabel("Type", { exact: true }).locator("option:checked")).toHaveText("Test");
    });

    await test.step("with only Test remaining, its delete control is disabled", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Fields & actions" }).click();
      await expect(inputWithValue(page, "Test")).toBeVisible();
      await expect(page.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
    });
  });
});
