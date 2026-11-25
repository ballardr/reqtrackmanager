import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: every control in the Project Admin Structure tree and the CSV column mapping has an
 * accessible name, so it can be found by label (and by a screen reader) rather than by placeholder.
 * Uses its own disposable project, so it mutates nothing shared and passes alone, first, last or repeated.
 */
test.describe("inline admin controls are labelled", () => {
  installCleanupHook();

  test("structure rows and the add panel are found by label", async ({ page }) => {
    const { projectId } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "Inline labels");
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}/admin`);
    await selectProjectAdminGroup(page, "Structure");

    await test.step("an existing component's expand control and actions are named after it", async () => {
      await expect(page.getByRole("button", { name: "Expand Hardware", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Actions for Hardware", exact: true })).toBeVisible();
    });

    await test.step("the add-component panel has a visible Name and Prefix label", async () => {
      await page.getByRole("button", { name: "Add component" }).click();
      const panel = page.getByRole("dialog", { name: "Add component" });
      await expect(panel.getByLabel("Name", { exact: true })).toBeVisible();
      await expect(panel.getByLabel("Prefix", { exact: true })).toBeVisible();
    });
  });

  test("CSV column mapping selects are found by label", async ({ page }) => {
    const { projectId } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "Inline labels CSV");
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}`);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.locator('input[type="file"][accept*="csv"]').setInputFiles({
      name: "labels.csv", mimeType: "text/csv", buffer: Buffer.from("Title,Why\nOne,Because\n"),
    });
    await expect(page.getByRole("dialog", { name: "Import Requirements" })).toBeVisible();
    await page.getByLabel("Map Name").selectOption("Title");
    await expect(page.getByLabel("Map Reasoning")).toBeVisible();
  });
});
