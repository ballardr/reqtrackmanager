import { expect, test } from "@playwright/test";

import { API_BASE_URL, setUpOrg } from "./modules/stakeholders/helpers";
import { installCleanupHook, openRequirementByName } from "./e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: the requirement create dialog takes every field the edit form does, so a
 * clarification, a review date, a reminder lead time and a reviewer do not have to wait for a
 * second trip to the detail page. Creating with them leaves them on the saved requirement.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded
 * state and can be repeated against the same database.
 */
test("creating a requirement with clarification and review fields keeps them", async ({ page }) => {
  const { suffix, project, adminHeaders } = await setUpOrg(page, "ReqCreate");
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  const component = await (await page.request.post(`${base}/components`, { headers: adminHeaders, data: { name: "Software", prefix: "SW" } })).json();
  const category = await (await page.request.post(`${base}/categories`, {
    headers: adminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id },
  })).json();
  expect(category.id).toBeTruthy();
  const name = `Boot in under five seconds ${suffix}`;

  await page.goto(`/projects/${project.id}/requirements`);
  await page.getByRole("button", { name: "New requirement" }).click();
  const dialog = page.getByRole("dialog", { name: "New requirement" });
  await dialog.getByPlaceholder("Name", { exact: true }).fill(name);
  await dialog.getByLabel("Clarification").fill("Applies to field devices only");
  await dialog.getByLabel("Review date").fill("2031-03-01");
  await dialog.getByLabel(/Reminder lead time/).fill("14");
  await dialog.getByRole("button", { name: "Create", exact: true }).click();
  await expect(dialog).not.toBeVisible();

  await openRequirementByName(page, name);
  await expect(page.getByLabel("Clarification")).toHaveValue("Applies to field devices only");
  await expect(page.getByLabel("Review date")).toHaveValue("2031-03-01");
  await expect(page.getByLabel(/Reminder lead time/)).toHaveValue("14");
});
