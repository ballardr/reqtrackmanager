import { expect, test } from "@playwright/test";

import {
  apiHeaders,
  deleteOrgOnCleanup,
  installCleanupHook,
  loginAs,
  PASSWORD,
  SERVER_ADMIN_LOGIN,
} from "./helpers";

// Deletes this file's disposable organisation after each test.
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: an organisation administrator opens the organisation settings and sees, at the top, how many users
 * and projects the organisation has and how much file storage it uses, as a plain table.
 *
 * Uses a disposable organisation with one administrator, one active project and one archived project, so the figures
 * are known exactly.
 */
test("the organisation settings overview opens with a usage table", async ({ page }) => {
  const suffix = Date.now();
  const serverHeaders = await apiHeaders(page.request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Usage Org ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  const adminEmail = `e2e-usage-admin-${suffix}@example.com`;
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Usage Admin", password: PASSWORD, role: "org_admin" },
  });
  const adminHeaders = await apiHeaders(page.request, adminEmail);
  await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
    headers: adminHeaders, data: { organization_id: org.id, name: `Usage Active ${suffix}`, summary: "" },
  });
  const archived = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: adminHeaders, data: { organization_id: org.id, name: `Usage Archived ${suffix}`, summary: "" },
    })
  ).json();
  expect((await page.request.post(`${apiBaseUrl}/api/v1/projects/${archived.id}/archive`, { headers: adminHeaders })).status()).toBe(200);

  await loginAs(page, adminEmail, PASSWORD);
  await page.goto(`/orgs/${org.id}/admin/overview`);

  const table = page.getByRole("table", { name: "Usage" });
  await expect(table).toBeVisible();
  await expect(table.getByRole("row", { name: /^Users\s+1$/ })).toBeVisible();
  await expect(table.getByRole("row", { name: /^Active .*\s+1$/ })).toBeVisible();
  await expect(table.getByRole("row", { name: /^Archived .*\s+1$/ })).toBeVisible();
  await expect(table.getByRole("row", { name: /^File storage\s+0 B$/ })).toBeVisible();
});
