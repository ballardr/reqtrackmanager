import { expect, type APIRequestContext, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

// Deletes this file's disposable organisation after the test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: pressing Additional components in the new requirement form opens its list directly under that field.
 *
 * Builds its own organisation and project (two components, so the field is offered), opens the form, presses the
 * field and expects the panel's left edge on the field's, its top just below the field (or its bottom just above it when there is no room below), and no part of it outside the
 * field's horizontal span. Passes alone, first, last or repeated.
 */
const apiBaseUrl = "http://localhost:8000";

async function post(request: APIRequestContext, headers: { Authorization: string }, path: string, data: unknown) {
  const response = await request.post(`${apiBaseUrl}/api/v1${path}`, { headers, data });
  expect(response.status(), await response.text()).toBeLessThan(300);
  return response.json();
}

test("the Additional components panel opens under its field", async ({ page }) => {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-treepos-${suffix}@example.com`;
  const serverLogin = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } });
  const serverHeaders = { Authorization: `Bearer ${(await serverLogin.json()).access_token}` };
  const org = await post(page.request, serverHeaders, "/orgs", { name: `TreePos ${suffix}` });
  deleteOrgOnCleanup({ id: org.id });
  await post(page.request, serverHeaders, `/orgs/${org.id}/users`, {
    email: adminEmail, display_name: "E2E Tree Position Admin", password: PASSWORD, role: "org_admin",
  });
  const login = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const project = await post(page.request, headers, "/projects", { organization_id: org.id, name: "Tree Position", summary: "" });
  for (const [name, prefix, categoryName, categoryPrefix] of [["Software", "SW", "Performance", "PERF"], ["Hardware", "HW", "Interfaces", "IF"]]) {
    const component = await post(page.request, headers, `/projects/${project.id}/components`, { name, prefix });
    await post(page.request, headers, `/projects/${project.id}/categories`, { name: categoryName, prefix: categoryPrefix, component_id: component.id });
  }

  await loginAs(page, adminEmail);
  await page.goto(`/projects/${project.id}/requirements`);
  await page.getByRole("button", { name: "New requirement" }).click();
  const dialog = page.getByRole("dialog", { name: "New requirement" });
  const field = dialog.getByRole("button", { name: "Components and categories" });
  await expect(field).toBeVisible();
  await field.click();
  const panel = page.getByRole("dialog", { name: "Components and categories" });
  await expect(panel).toBeVisible();

  const fieldBox = (await field.boundingBox())!;
  const panelBox = (await panel.boundingBox())!;
  expect(Math.abs(panelBox.x - fieldBox.x)).toBeLessThan(2);
  // Directly under the field, or directly over it when the window leaves no usable room below.
  const gapBelow = Math.abs(panelBox.y - (fieldBox.y + fieldBox.height));
  const gapAbove = Math.abs(panelBox.y + panelBox.height - fieldBox.y);
  expect(Math.min(gapBelow, gapAbove)).toBeLessThan(12);
  expect(panelBox.x + panelBox.width).toBeLessThanOrEqual(fieldBox.x + fieldBox.width + 1);
});
