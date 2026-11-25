import { expect, test } from "@playwright/test";

import { installCleanupHook } from "./e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: empty an owner with one compact X after the value, in a form and on a record's page, without a
 * full-size button widening the row.
 *
 * Covers: the requirement create form's Owner (the open search box beside the value) setting and clearing with the X
 * and keeping its height; and a persona's Owner on its detail page (the compact form) set, cleared with the X, and
 * still empty after a reload.
 *
 * Disposable organisation, project and persona created through the API and removed afterwards.
 */
test("the owner clear control is a compact X in a form and on a record page", async ({ page }) => {
  test.setTimeout(120_000);
  const { suffix, project, adminHeaders } = await setUpOrg(page, "ClearCtl");
  const adminName = "E2E ClearCtl Admin";
  // A requirement belongs to a component and category, so the create form needs both to show its fields.
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  const component = await (await page.request.post(`${base}/components`, { headers: adminHeaders, data: { name: "Software", prefix: "SW" } })).json();
  await page.request.post(`${base}/categories`, { headers: adminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id } });

  await page.goto(`/projects/${project.id}/requirements`);
  await page.getByRole("button", { name: "New requirement" }).click();
  const dialog = page.getByRole("dialog", { name: "New requirement" });
  const owner = dialog.getByRole("combobox", { name: "Owner" });
  const emptyHeight = (await owner.boundingBox())!.height;
  await expect(owner).toHaveAttribute("placeholder", "Search users and groups…");
  await owner.fill("ClearCtl");
  await dialog.getByText(adminName).first().click();
  const clear = dialog.getByRole("button", { name: "Clear: Owner" });
  await expect(clear).toBeVisible();
  expect((await clear.boundingBox())!.height).toBeLessThan(24);
  expect(Math.abs((await owner.boundingBox())!.height - emptyHeight)).toBeLessThanOrEqual(1);
  await clear.click();
  await expect(clear).toHaveCount(0);
  await dialog.getByRole("button", { name: "Close", exact: true }).click();

  const persona = await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
    headers: adminHeaders, data: { name: `Owned persona ${suffix}` },
  })).json();
  await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
  await page.getByRole("button", { name: "Assign: Persona owner" }).click();
  const picker = page.getByRole("dialog", { name: "Assign: Persona owner" });
  await picker.getByRole("combobox", { name: "Persona owner" }).fill("ClearCtl");
  await picker.getByText(adminName).first().click();
  const personaClear = page.getByRole("button", { name: "Clear: Persona owner" });
  await expect(personaClear).toBeVisible();
  await personaClear.click();
  await expect(personaClear).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Assign: Persona owner" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Clear: Persona owner" })).toHaveCount(0);
});
