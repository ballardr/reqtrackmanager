import { expect, test } from "@playwright/test";

import { installCleanupHook, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an administrator adding a connection type sets its line style, direction and domain in the one dialog
 * the Add button opens, instead of creating a bare type and editing it afterwards.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; everything under test goes through the UI.
 */
test.describe("System Architecture: a type is added with every attribute in one step", () => {
  test("the one Add button opens the full form and the new connection type keeps every value", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "ArchTypeAdd", false, "System Architecture");
    const typeName = `Radio ${suffix}`;

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Connection Types", "System Architecture");

    await test.step("there is one Add button, and no second create beside the list", async () => {
      await expect(page.getByRole("button", { name: "Add connection type", exact: true })).toHaveCount(1);
      await expect(page.getByRole("button", { name: /with details/ })).toHaveCount(0);
    });

    await test.step("create with a line style, one-way off and a domain in one dialog", async () => {
      await page.getByRole("button", { name: "Add connection type", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Add connection type" });
      await expect(dialog.getByLabel("Name", { exact: true })).toBeFocused();
      await dialog.getByLabel("Name", { exact: true }).fill(typeName);
      await dialog.getByLabel("Line style").selectOption({ label: "Dashed" });
      await dialog.getByRole("button", { name: "Domains", exact: true }).click();
      await page.getByRole("checkbox", { name: "Hardware", exact: true }).check();
      await page.keyboard.press("Escape");
      await dialog.getByRole("switch", { name: "One-way" }).click();
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Connection type created.")).toBeVisible();
    });

    await test.step("the list shows the style, direction and domain, and a reload keeps them", async () => {
      await page.reload();
      await selectProjectAdminGroup(page, "Connection Types", "System Architecture");
      const row = page.locator(`input[value="${typeName}"]`).first().locator("xpath=ancestor::div[contains(@class,'definition-grid__row')][1]");
      await expect(row).toContainText("Hardware · Dashed, two-way");
    });
  });
});
