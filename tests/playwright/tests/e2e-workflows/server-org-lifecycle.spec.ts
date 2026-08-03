import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: as a server administrator, I need to be able to disable
 * an organisation reversibly (e.g. a hosting customer stopped paying) and,
 * separately, permanently delete one once it's genuinely no longer needed
 * — both from the Server Management console, without touching any other
 * organisation. See docs/decisions.md's "Organisation disable and hard
 * delete" section for the full design.
 *
 * Persona: ServerAdminOnly (zero org memberships).
 */
test.describe("server admin manages an organisation's lifecycle", () => {
  test("create, disable, re-enable, then permanently delete an organisation", async ({ page }) => {
    const orgName = `Lifecycle Test Org ${Date.now()}`;

    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.getByRole("link", { name: "Organisations", exact: true }).last().click();
    await expect(page).toHaveURL(/\/server\/organisations$/);

    await test.step("create the organisation", async () => {
      await page.getByRole("button", { name: "New organisation" }).click();
      await page.getByPlaceholder("Organisation name").fill(orgName);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("row", { name: new RegExp(orgName) })).toContainText("Active");
    });

    const row = page.getByRole("row", { name: new RegExp(orgName) });

    await test.step("disable it", async () => {
      page.once("dialog", (dialog) => dialog.accept());
      await row.getByRole("button", { name: "Disable" }).click();
      await expect(row).toContainText("Disabled");
    });

    await test.step("re-enable it", async () => {
      await row.getByRole("button", { name: "Enable" }).click();
      await expect(row).toContainText("Active");
    });

    await test.step("delete requires typing the exact name", async () => {
      await row.getByRole("button", { name: "Delete", exact: true }).click();
      const confirmButton = page.getByRole("button", { name: "Permanently delete" });
      await expect(confirmButton).toBeDisabled();
      await page.getByPlaceholder(orgName).fill("the wrong name");
      await expect(confirmButton).toBeDisabled();
      await page.getByPlaceholder(orgName).fill(orgName);
      await expect(confirmButton).toBeEnabled();
      await confirmButton.click();
    });

    await test.step("the organisation is gone", async () => {
      await expect(page.getByRole("row", { name: new RegExp(orgName) })).toHaveCount(0);
    });
  });
});
