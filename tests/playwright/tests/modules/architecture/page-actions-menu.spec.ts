import { expect, test } from "@playwright/test";

import { installCleanupHook, selectOrgResourcesGroup } from "../../e2e-workflows/helpers";
import { clickMenuRow, menuRow } from "../../menuTree";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an architect finds every secondary action of a System Architecture page in one place. A page shows one
 * primary button (New element, New collection) and one actions menu (folders, a related page, an interchange file,
 * Export and Import), and each row or collection card has its own actions menu, never a row of buttons.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; everything else through the UI.
 */
test.describe("System Architecture: one actions menu per page", () => {
  test("the project Elements page offers New element and one menu holding Sharing, Interchange and folders", async ({ page }) => {
    const { project } = await setUpOrg(page, "ArchMenu", false, "System Architecture");

    await page.goto(`/projects/${project.id}/modules/architecture?tab=elements`);
    await expect(page.getByRole("button", { name: "New element" })).toBeVisible();
    for (const name of ["Sharing", "Interchange", "New folder"]) {
      await expect(page.getByRole("button", { name }), `${name} is a menu row, not a button`).toHaveCount(0);
      await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0);
    }

    await page.getByRole("button", { name: "List actions" }).click();
    for (const name of ["New folder", "Sharing", "Export JSON file"]) {
      await expect(await menuRow(page, name)).toBeVisible();
    }
    // The Export and Import rows arrive once the type's columns have loaded.
    await expect(page.getByRole("menuitem", { name: "Download shown items" })).toBeVisible();
    await clickMenuRow(page, "Sharing");
    await expect(page).toHaveURL(/\/modules\/architecture\/sharing$/);
  });

  test("the organisation Elements tab and Collections tab use one menu for the page and one per row or card", async ({ page }) => {
    const { suffix, org } = await setUpOrg(page, "ArchOrgMenu", false, "System Architecture");
    const element = `Gateway ${suffix}`;

    await page.goto(`/orgs/${org.id}/resources`);
    await selectOrgResourcesGroup(page, "Architecture Elements and Collections");

    await test.step("the page menu holds the folder action and Export and Import", async () => {
      await page.getByRole("button", { name: "New element" }).click();
      const dialog = page.getByRole("dialog", { name: "New element" });
      await dialog.getByLabel("Name", { exact: true }).fill(element);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByRole("table", { name: "Organisation elements" }).getByText(element)).toBeVisible();

      await expect(page.getByRole("button", { name: "New folder" })).toHaveCount(0);
      await page.getByRole("button", { name: "List actions" }).click();
      await expect(page.getByRole("menuitem", { name: "New folder" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Download shown items" })).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("a row has one actions menu: Edit, Change status and Archive", async () => {
      const row = page.getByRole("row", { name: new RegExp(element) });
      await expect(row.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
      await row.getByRole("button", { name: `Actions for ${element}` }).click();
      await expect(page.getByRole("menuitem", { name: "Edit", exact: true })).toBeVisible();
      await clickMenuRow(page, "Archive");
      await expect(page.getByText("Element archived.")).toBeVisible();
    });

    await test.step("a collection card has one actions menu holding Edit and Delete", async () => {
      await page.getByRole("tab", { name: "Collections" }).click();
      await page.getByRole("button", { name: "New collection" }).click();
      const dialog = page.getByRole("dialog", { name: "New collection" });
      await dialog.getByLabel("Name", { exact: true }).fill("Corporate services");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      const card = page.getByRole("region", { name: "Corporate services" });
      await expect(card.getByRole("button", { name: "Delete", exact: true })).toHaveCount(0);
      await card.getByRole("button", { name: "Actions for Corporate services" }).click();
      await clickMenuRow(page, "Delete");
      await page.getByRole("dialog", { name: "Delete Corporate services?" }).getByRole("button", { name: "Delete", exact: true }).click();
      await expect(page.getByText("Collection deleted.")).toBeVisible();
    });
  });
});
