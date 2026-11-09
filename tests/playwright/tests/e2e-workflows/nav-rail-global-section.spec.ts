import { expect, test } from "@playwright/test";

import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";
import { installCleanupHook } from "./helpers";

// Deletes this file's disposable org after the test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: the Global section of the navigation rail lists Projects, Files, any module entries, Organisation
 * overview and Organisation settings in that order; the Notifications page has no entry there (the header bell opens it);
 * and "My reviews due" appears only once a review is due for the person.
 *
 * Disposable organisation and administrator via `setUpOrg`, so no review is due at the start; the due review is created
 * through the API and the rail is read through the UI.
 */
test.describe("navigation rail: Global section", () => {
  test("the order is fixed, Notifications is the bell's, and reviews due appears only when something is due", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "NavRail");
    const rail = page.getByRole("navigation");
    const railNames = async () => (await rail.getByRole("link").evaluateAll((links) => links.map((link) => link.getAttribute("aria-label"))));

    await test.step("with nothing due the rail has no reviews entry and no Notifications entry", async () => {
      await page.goto("/projects");
      await expect(rail.getByRole("link", { name: "Organisation settings" })).toBeVisible();
      await expect(rail.getByRole("link", { name: "My reviews due" })).toHaveCount(0);
      await expect(rail.getByRole("link", { name: "Notifications" })).toHaveCount(0);
      const names = await railNames();
      expect(names.slice(names.indexOf("Projects"), names.indexOf("Projects") + 2)).toEqual(["Projects", "Files"]);
      expect(names.slice(-2)).toEqual(["Organisation overview", "Organisation settings"]);
    });

    await test.step("the header bell still reaches the full Notifications page", async () => {
      await page.getByRole("button", { name: "Notifications" }).click();
      await page.getByRole("link", { name: "View all" }).click();
      await expect(page).toHaveURL(/\/notifications$/);
      await expect(page.getByRole("heading", { name: "Notifications", exact: true })).toBeVisible();
    });

    await test.step("a review that falls due adds the entry, between Files and Organisation overview", async () => {
      const api = `${API_BASE_URL}/api/v1`;
      const me = await (await page.request.get(`${api}/auth/me`, { headers: adminHeaders })).json();
      const post = async (path: string, data: unknown) => {
        const resp = await page.request.post(`${api}${path}`, { headers: adminHeaders, data });
        expect(resp.ok(), await resp.text()).toBeTruthy();
        return resp.json();
      };
      const component = await post(`/projects/${project.id}/components`, { name: "Nav", prefix: "NV" });
      const category = await post(`/projects/${project.id}/categories`, { name: "Rail", prefix: "RL", component_id: component.id });
      await post(`/projects/${project.id}/requirements`, {
        name: `Due for the rail ${suffix}`, component_id: component.id, category_id: category.id,
        reviewer: { type: "user", id: me.id }, review_date: "2024-01-01",
      });
      await page.goto("/projects");
      await expect(rail.getByRole("link", { name: "My reviews due" })).toBeVisible();
      const names = await railNames();
      expect(names.slice(names.indexOf("Files"))).toEqual(["Files", "My reviews due", "Organisation overview", "Organisation settings"]);
    });
  });
});
