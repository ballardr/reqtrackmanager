import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an architect organises a long list of elements into folders (Software, with Modules inside it),
 * files an element when creating it, narrows the list to a folder, moves several elements at once and deletes a folder
 * without losing anything. Folders only organise the list; they change nothing about the model.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture switched on; everything else through the UI.
 */
test.describe("System Architecture: folders", () => {
  test("an architect files, filters, moves and deletes folders of elements", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "Folders", false, "System Architecture");
    const auth = `Auth ${suffix}`;
    const loose = `Loose ${suffix}`;

    await test.step("open the Elements tab, which starts with no folders", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture?tab=elements`);
      await expect(page.getByRole("button", { name: "New folder" })).toBeVisible();
      await expect(page.getByRole("button", { name: /^Folder / })).toHaveCount(0);
    });

    await test.step("make a folder and a folder inside the chosen one", async () => {
      await page.getByRole("button", { name: "New folder" }).click();
      const dialog = page.getByRole("dialog", { name: "New folder" });
      await dialog.getByLabel("Name", { exact: true }).fill("Software");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Folder created.")).toBeVisible();
      await page.getByRole("button", { name: "Folder Software" }).click();

      await page.getByRole("button", { name: "New folder" }).click();
      const inner = page.getByRole("dialog", { name: "New folder" });
      await expect(inner.getByRole("button", { name: "Parent folder", exact: true })).toContainText("Software");
      await inner.getByLabel("Name", { exact: true }).fill("Modules");
      await inner.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByRole("button", { name: "Folder Modules" })).toBeVisible();
    });

    await test.step("file a new element in the inner folder from the create form", async () => {
      await page.getByRole("button", { name: "New element" }).click();
      const dialog = page.getByRole("dialog", { name: "New element" });
      await dialog.getByLabel("Name", { exact: true }).fill(auth);
      await dialog.getByRole("button", { name: "Folder", exact: true }).click();
      await page.getByRole("radio", { name: "Modules" }).click();
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Element created.")).toBeVisible();
    });

    await test.step("add an element with no folder, then narrow the list by folder", async () => {
      // Software is still the chosen folder, which would hide a new element filed nowhere: clear the choice first.
      await page.getByRole("button", { name: "Folder Software" }).click();
      await page.getByRole("button", { name: "New element" }).click();
      const dialog = page.getByRole("dialog", { name: "New element" });
      await dialog.getByLabel("Name", { exact: true }).fill(loose);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.locator("tr", { hasText: loose })).toBeVisible();
      await expect(page.locator("tr", { hasText: auth }).getByText("Software/Modules")).toBeVisible();

      await page.getByRole("button", { name: "Folder Software" }).click();
      await expect(page.locator("tr", { hasText: loose })).toHaveCount(0);
      await expect(page.locator("tr", { hasText: auth })).toBeVisible();
      await page.getByRole("checkbox", { name: "Include sub-folders" }).uncheck();
      await expect(page.locator("tr", { hasText: auth })).toHaveCount(0);
      await page.getByRole("checkbox", { name: "Include sub-folders" }).check();
      await page.getByRole("button", { name: "Folder Software" }).click(); // choosing it again clears the filter
      await expect(page.locator("tr", { hasText: loose })).toBeVisible();
    });

    await test.step("move the loose element into a folder from the selection", async () => {
      await page.locator("tr", { hasText: loose }).getByRole("checkbox").check();
      await expect(page.getByText("1 selected")).toBeVisible();
      await page.getByRole("button", { name: "Move to folder" }).click();
      const dialog = page.getByRole("dialog", { name: /Move 1 element to a folder/ });
      await dialog.getByRole("button", { name: "Folder", exact: true }).click();
      await page.getByRole("radio", { name: "Software", exact: true }).click();
      const moved = page.waitForResponse((r) => r.url().includes("/element-folders/move-records") && r.ok());
      await dialog.getByRole("button", { name: "Move", exact: true }).click();
      await moved;
      await expect(page.getByText("1 element moved.")).toBeVisible();
      await expect(page.locator("tr", { hasText: loose }).getByText("Software", { exact: true })).toBeVisible();
    });

    await test.step("deleting the inner folder moves its element up and survives a reload", async () => {
      await page.getByRole("button", { name: "Folder Modules" }).click();
      await page.getByRole("button", { name: "Delete folder" }).click();
      const confirm = page.getByRole("dialog", { name: "Delete folder Modules?" });
      await expect(confirm.getByText(/Nothing else is deleted/)).toBeVisible();
      await confirm.getByRole("button", { name: "Delete", exact: true }).click();
      await expect(page.getByText("Folder deleted.")).toBeVisible();
      await page.reload();
      await expect(page.getByRole("button", { name: "Folder Modules" })).toHaveCount(0);
      await expect(page.locator("tr", { hasText: auth }).getByText("Software", { exact: true })).toBeVisible();
    });
  });
});
