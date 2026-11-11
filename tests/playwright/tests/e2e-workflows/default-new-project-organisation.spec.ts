import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: a person who belongs to several organisations chooses, on the Preferences page, the organisation the
 * New project dialog starts on. Without a choice (or with "None") the dialog starts on the first organisation, and a
 * choice that no longer applies degrades to that.
 *
 * Two disposable organisations, joined by the server administrator persona as `project-list-org-scoping.spec.ts` does,
 * and deleted after the test.
 */
test.describe("default organisation for new projects", () => {
  installCleanupHook();

  test("the Preferences choice is where New project starts, and clearing it restores the first organisation", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const headers = { Authorization: `Bearer ${token}` };
    const api = "http://localhost:8000/api/v1";

    const suffix = Date.now();
    const orgs: { id: string; name: string }[] = [];
    for (const letter of ["A", "B"]) {
      const name = `E2E Default Org ${letter} (${suffix})`;
      const created = await (await page.request.post(`${api}/orgs`, { headers, data: { name } })).json();
      deleteOrgOnCleanup({ id: created.id });
      expect((await page.request.post(`${api}/orgs/${created.id}/join-as-admin`, { headers })).status()).toBe(204);
      orgs.push({ id: created.id, name });
    }
    const [first, second] = orgs;
    const startingOrganisation = async () => {
      await page.goto("/projects");
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      return dialog.locator("select").first();
    };
    const preference = page.getByLabel("Default organisation for new projects");

    await test.step("with no choice the dialog starts on the first organisation", async () => {
      const picker = await startingOrganisation();
      await expect(picker).toHaveValue(first.id);
    });

    await test.step("choosing the second organisation in Preferences makes New project start there", async () => {
      await page.goto("/preferences");
      await preference.selectOption(second.id);
      await expect(preference).toHaveValue(second.id);
      const picker = await startingOrganisation();
      await expect(picker).toHaveValue(second.id);
      // Changing the picker in the dialog does not change the stored default.
      await picker.selectOption(first.id);
      await page.goto("/preferences");
      await expect(preference).toHaveValue(second.id);
    });

    await test.step("None restores the first organisation", async () => {
      await preference.selectOption("");
      const picker = await startingOrganisation();
      await expect(picker).toHaveValue(first.id);
    });

    await test.step("a default that is no longer an offered organisation falls back to the first", async () => {
      const stale = await page.request.patch(`${api}/auth/me/preferences`, {
        headers, data: { ui_preferences: { default_new_project_organization_id: "00000000-0000-0000-0000-000000000000" } },
      });
      expect(stale.ok()).toBeTruthy();
      const picker = await startingOrganisation();
      await expect(picker).toHaveValue(first.id);
      await page.goto("/preferences");
      await expect(preference).toHaveValue("");
    });
  });
});
