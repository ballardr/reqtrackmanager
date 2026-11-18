import { expect, test } from "@playwright/test";

import { installCleanupHook, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an organisation administrator records a part every product depends on (a sign-in service) as an element the
 * organisation owns, and groups it in a collection so projects can be given it. The element is created and listed on the
 * organisation's Elements tab, and the Collections tab holds a collection that contains it.
 *
 * Disposable org and admin via `setUpOrg` with System Architecture on; everything else through the UI.
 */
test.describe("System Architecture: organisation elements", () => {
  test("an organisation administrator creates an element and a collection that holds it", async ({ page }) => {
    const { suffix, org } = await setUpOrg(page, "ArchOrgEl", false, "System Architecture");
    const element = `Sign-in ${suffix}`;

    await test.step("the Elements tab lists an element the organisation owns", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Elements and Collections", "System Architecture");
      await expect(page.getByText("The organisation has no elements of its own yet.")).toBeVisible();
      await page.getByRole("button", { name: "New element" }).click();
      const dialog = page.getByRole("dialog", { name: "New element" });
      await dialog.getByLabel("Name", { exact: true }).fill(element);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      const table = page.getByRole("table", { name: "Organisation elements" });
      await expect(table.getByText(element)).toBeVisible();
    });

    await test.step("the Collections tab holds a collection containing it", async () => {
      await page.getByRole("tab", { name: "Collections" }).click();
      await page.getByRole("button", { name: "New collection" }).click();
      const dialog = page.getByRole("dialog", { name: "New collection" });
      await dialog.getByLabel("Name", { exact: true }).fill("Corporate services");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      const card = page.getByRole("region", { name: "Corporate services" });
      await card.getByLabel("Add an element to Corporate services").selectOption({ index: 1 });
      await expect(card.getByText(new RegExp(element))).toBeVisible();
    });
  });
});
