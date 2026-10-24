import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: every control in the Project Admin Structure rows and the CSV column mapping has an
 * accessible name, so it can be found by label (and by a screen reader) rather than by placeholder.
 * Uses its own disposable project, so it mutates nothing shared and passes alone, first, last or repeated.
 */
test.describe("inline admin controls are labelled", () => {
  installCleanupHook();

  test("structure rows and add rows are found by label", async ({ page }) => {
    const { projectId } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "Inline labels");
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}/admin`);
    await selectProjectAdminGroup(page, "Structure");

    await test.step("an existing component's name and prefix inputs are named after it", async () => {
      await expect(page.getByLabel("Name: Hardware")).toBeVisible();
      await expect(page.getByLabel("Prefix: Hardware")).toBeVisible();
    });

    await test.step("the add-component row has a visible Name and Prefix label", async () => {
      const section = page.locator(".card", { has: page.getByRole("button", { name: "Components & categories section" }) });
      await expect(section.getByLabel("Name", { exact: true }).last()).toBeVisible();
      await expect(section.getByLabel("Prefix", { exact: true }).last()).toBeVisible();
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
