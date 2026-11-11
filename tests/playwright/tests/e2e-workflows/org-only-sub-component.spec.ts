import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";
const INBOX = "Organisation-level request inbox";

/**
 * Job to be done: a sub-component owned by the organisation (Product Feedback's request inbox) is switched in
 * organisation administration only. Project administration does not offer it, the project API rejects a write for it,
 * and the organisation switch still works.
 *
 * Uses a disposable organisation created via the API, per the repo's test-idempotency rule.
 */
test.describe("organisation-only sub-component", () => {
  test("the request inbox is offered to the organisation and not to a project", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-orgonly-admin-${suffix}@example.com`;
    const serverAdminToken = (
      await (await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
    ).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverAdminHeaders, data: { name: `E2E OrgOnly Org ${suffix}` } })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E OrgOnly Admin", password: PASSWORD, role: "org_admin" },
    });
    const adminHeaders = {
      Authorization: `Bearer ${(
        await (await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
      ).access_token}`,
    };
    await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/modules/product_feedback`, {
      headers: adminHeaders, data: { enabled: true, default_project_enabled: true },
    });
    const project = await (
      await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
        headers: adminHeaders, data: { organization_id: org.id, name: `E2E OrgOnly Project ${suffix}`, summary: "" },
      })
    ).json();

    // The project API lists the other sub-components and neither lists nor accepts the inbox.
    const projectSubs = await (
      await page.request.get(`${apiBaseUrl}/api/v1/projects/${project.id}/modules/product_feedback/subcomponents`, { headers: adminHeaders })
    ).json();
    expect(projectSubs.map((s: { name: string }) => s.name)).toEqual(["Enhancement requests", "External references"]);
    const rejected = await page.request.put(
      `${apiBaseUrl}/api/v1/projects/${project.id}/modules/product_feedback/subcomponents/organization_requests`,
      { headers: adminHeaders, data: { enabled: false } },
    );
    expect(rejected.status()).toBe(404);

    await loginAs(page, adminEmail, PASSWORD);

    // Project administration: the module's components do not include the inbox.
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Modules");
    const projectRow = page.locator(".module-settings-row", { has: page.getByText("Product Feedback", { exact: true }) });
    await projectRow.getByRole("button", { name: /components? ·/ }).click();
    await expect(page.getByRole("switch", { name: "Enable Enhancement requests (Product Feedback) for this project" })).toBeVisible();
    await expect(page.getByText(INBOX)).toHaveCount(0);

    // Organisation administration: the inbox is still a switch of its own.
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    const orgRow = page.locator(".module-settings-row", { has: page.getByText("Product Feedback", { exact: true }) });
    await orgRow.getByRole("button", { name: /components?/ }).click();
    const inbox = page.getByRole("combobox", { name: `${INBOX} (Product Feedback) availability`, exact: true });
    await expect(inbox).toBeVisible();
    await inbox.selectOption("off");
    await expect(inbox).toHaveValue("off");
    await inbox.selectOption("default_on");
    await expect(inbox).toHaveValue("default_on");
  });
});
