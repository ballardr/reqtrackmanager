import { expect, test } from "@playwright/test";

import { installCleanupHook, selectOptionContaining } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/**
 * Job to be done: an infrastructure team shares an element it owns with another project, and later withdraws it. The collection is
 * granted to a project (with its nested projects) from the Sharing page, the element's own page counts the grant, and removing the
 * grant returns it to none.
 *
 * Disposable org, admin and a project with a child via `setUpOrg` with System Architecture on; the element is created through the
 * API as setup, the collection and the grant through the UI.
 */
test.describe("System Architecture: sharing grants", () => {
  test("a collection is shared with a project and the grant is withdrawn", async ({ page }) => {
    const { suffix, project, child, adminHeaders } = await setUpOrg(page, "ArchGrant", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${base}/element-types`, { headers: adminHeaders })).json();
    const element = `Identity ${suffix}`;
    const created = await page.request.post(`${base}/elements`, { headers: adminHeaders, data: { name: element, element_type_id: types[0].id, activate: true } });
    expect(created.ok(), await created.text()).toBeTruthy();

    await test.step("a collection holds the element", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/sharing`);
      await page.getByRole("button", { name: "New collection" }).click();
      const dialog = page.getByRole("dialog", { name: "New collection" });
      await dialog.getByLabel("Name", { exact: true }).fill("Shared infrastructure");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      const card = page.getByRole("region", { name: "Shared infrastructure" });
      await selectOptionContaining(card.getByLabel("Add an element to Shared infrastructure"), element);
      await expect(card.getByText(new RegExp(element))).toBeVisible();
    });

    await test.step("the collection is shared with the child project and its nested projects", async () => {
      const card = page.getByRole("region", { name: "Shared infrastructure" });
      await selectOptionContaining(card.getByLabel("Project", { exact: true }), child.name);
      await card.getByRole("checkbox", { name: /Include nested projects/ }).check();
      const granted = page.waitForResponse((r) => r.url().includes("/grants") && r.request().method() === "POST");
      await card.getByRole("button", { name: "Share", exact: true }).click();
      expect((await granted).ok()).toBeTruthy();
      await expect(card.getByText(new RegExp(`${child.name}.* and nested projects`))).toBeVisible();
      await expect(card.getByText("Not shared with anyone yet.")).toHaveCount(0);
    });

    await test.step("the element's page counts the grant", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture?tab=elements`);
      await page.getByRole("link", { name: /ELM-001/ }).click();
      await expect(page.getByRole("region", { name: "Sharing" }).getByText("Shared infrastructure · 1 grant")).toBeVisible();
    });

    await test.step("withdrawing the grant returns the count to none", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/sharing`);
      const card = page.getByRole("region", { name: "Shared infrastructure" });
      const removed = page.waitForResponse((r) => r.url().includes("/grants/") && r.request().method() === "DELETE");
      await card.getByRole("button", { name: /^Stop sharing Shared infrastructure with/ }).click();
      expect((await removed).ok()).toBeTruthy();
      await expect(card.getByText("Not shared with anyone yet.")).toBeVisible();
    });
  });
});
