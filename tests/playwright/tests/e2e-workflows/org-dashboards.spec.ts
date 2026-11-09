import { expect, type APIRequestContext, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, logout, PASSWORD } from "./helpers";

// Deletes this file's disposable organisation after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an organisation's overview is a dashboard of widgets, and its administrators add further pages to
 * organise them, each optionally limited to chosen people.
 *
 * Covers: the built-in Overview page showing the headline figures; an administrator creating a page from the Manage
 * dashboards dialog and customising it; a page limited to one member being listed for that member and for nobody else,
 * and its address returning anyone else to the Overview. The organisation is created for the test, so no other spec's
 * data is involved.
 */

const apiBaseUrl = "http://localhost:8000/api/v1";

async function createOrganisation(request: APIRequestContext) {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (await request.post(`${apiBaseUrl}/orgs`, { headers: serverHeaders, data: { name: `Dashboards ${suffix}` } })).json();
  deleteOrgOnCleanup({ id: org.id });
  const people: Record<string, { email: string; id: string }> = {};
  for (const [key, role] of [["admin", "org_admin"], ["first", "member"], ["second", "member"]] as const) {
    const email = `e2e-dash-${key}-${suffix}@example.com`;
    const created = await request.post(`${apiBaseUrl}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email, display_name: `E2E Dashboard ${key}`, password: PASSWORD, role },
    });
    expect(created.ok()).toBeTruthy();
    people[key] = { email, id: (await created.json()).user_id };
  }
  const adminToken = (await (await request.post(`${apiBaseUrl}/auth/login`, { data: { email: people.admin.email, password: PASSWORD } })).json()).access_token;
  return { orgId: org.id as string, people, adminHeaders: { Authorization: `Bearer ${adminToken}` } };
}

test.describe("organisation dashboards", () => {
  test("an administrator adds a page, limits it to one member, and only that member sees it", async ({ page }) => {
    const world = await createOrganisation(page.request);
    const overview = `/orgs/${world.orgId}/overview`;

    await test.step("the built-in Overview page shows the headline figures", async () => {
      await loginAs(page, world.people.admin.email);
      await page.goto(overview);
      await expect(page.locator("[data-stat-entry]").filter({ hasText: "Members" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Customise" })).toBeVisible();
    });

    await test.step("the administrator creates a page from Manage dashboards", async () => {
      await page.getByRole("button", { name: "Manage dashboards" }).click();
      const manage = page.getByRole("dialog", { name: "Dashboards" });
      await manage.getByRole("button", { name: "New dashboard" }).click();
      const form = page.getByRole("dialog", { name: "New dashboard" });
      await form.getByLabel(/Name/).fill("Delivery");
      await form.getByRole("button", { name: "Save" }).click();
      await expect(manage.getByText("Delivery", { exact: true })).toBeVisible();
    });

    const pages: { id: string; name: string }[] = await (await page.request.get(`${apiBaseUrl}/orgs/${world.orgId}/dashboards`, { headers: world.adminHeaders })).json();
    const delivery = pages.find((p) => p.name === "Delivery");
    expect(delivery).toBeTruthy();

    await test.step("the page is limited to one member", async () => {
      const limited = await page.request.put(`${apiBaseUrl}/orgs/${world.orgId}/dashboards/${delivery!.id}`, {
        headers: world.adminHeaders, data: { viewers: [{ type: "user", id: world.people.first.id }] },
      });
      expect(limited.ok()).toBeTruthy();
      await page.goto(`${overview}/dashboard-${delivery!.id}`);
      await expect(page.getByRole("button", { name: "Customise" })).toBeVisible();
      await expect(page.getByText("This dashboard has no widgets yet.")).toBeVisible();
    });

    await test.step("the named member sees it in the menu", async () => {
      await logout(page);
      await loginAs(page, world.people.first.email);
      await page.goto(overview);
      await expect(page.locator(".resource-menu-nav").getByRole("link", { name: "Delivery", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Customise" })).toHaveCount(0);
    });

    await test.step("another member does not, and its address returns them to the Overview", async () => {
      await logout(page);
      await loginAs(page, world.people.second.email);
      await page.goto(overview);
      await expect(page.getByRole("link", { name: "Delivery", exact: true })).toHaveCount(0);
      await page.goto(`${overview}/dashboard-${delivery!.id}`);
      await expect(page).toHaveURL(new RegExp(`${overview}$`));
    });
  });

  test("the removed Compliance dashboard address returns to the Overview", async ({ page }) => {
    const world = await createOrganisation(page.request);
    await loginAs(page, world.people.admin.email);
    await page.goto(`/orgs/${world.orgId}/overview/compliance-dashboard`);
    await expect(page).toHaveURL(new RegExp(`/orgs/${world.orgId}/overview$`));
  });
});
