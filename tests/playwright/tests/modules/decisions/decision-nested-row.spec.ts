import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: a Decision row on a widened list opens the Decision page in the project the Decision belongs
 * to, not in the project being viewed.
 *
 * Builds its own organisation with a parent and a child project and one Decision in the parent, so it depends on
 * no shared fixture.
 */
test("a Decision row from the parent project opens its page in the parent project", async ({ page }) => {
  const suffix = Date.now();
  const adminEmail = `e2e-decision-nested-${suffix}@example.com`;

  const serverLogin = await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, {
    data: { email: "admin@example.com", password: "ChangeMe123!" },
  });
  const serverHeaders = { Authorization: `Bearer ${(await serverLogin.json()).access_token}` };
  const org = await (
    await page.request.post(`${API_BASE_URL}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Decision Nested ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Nested Admin", password: PASSWORD, role: "org_admin" },
  });

  await loginAs(page, adminEmail, PASSWORD);
  const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const headers = { Authorization: `Bearer ${token}` };

  await page.goto("/orgs");
  await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
  await selectOrgAdminGroup(page, "Modules");
  await setOrgModuleAvailability(page, "Decision Management", "default_on");

  const parent = await (
    await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
      headers, data: { organization_id: org.id, name: `E2E Decision Parent ${suffix}`, summary: "", can_be_parent: true },
    })
  ).json();
  const child = await (
    await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
      headers, data: { organization_id: org.id, name: `E2E Decision Child ${suffix}`, summary: "", parent_project_id: parent.id },
    })
  ).json();

  const base = `${API_BASE_URL}/api/v1/projects/${parent.id}/modules/decisions`;
  let types: { id: string }[] = await (await page.request.get(`${base}/decision-types`, { headers })).json();
  if (types.length === 0) {
    const made = await page.request.post(`${base}/decision-types`, { headers, data: { name: "Architecture" } });
    expect(made.ok()).toBeTruthy();
    types = [await made.json()];
  }
  const created = await page.request.post(base, {
    headers,
    data: { title: "Parent-level decision", decision_statement: "Decided in the parent.", decision_type_id: types[0].id },
  });
  expect(created.ok()).toBeTruthy();
  const decision = await created.json();

  await page.goto(`/projects/${child.id}/modules/decisions?open=0`);
  await page.getByRole("combobox", { name: "Show records from" }).selectOption({ label: "This + parent projects" });
  const row = page.getByRole("link", { name: /DEC-001$/ });
  await expect(row).toBeVisible();

  await row.click();
  await expect(page).toHaveURL(new RegExp(`/projects/${parent.id}/modules/decisions/${decision.id}$`));
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Parent-level decision/ })).toBeVisible();
});
