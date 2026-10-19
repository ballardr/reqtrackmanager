import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a record is rarely meaningful alone, so a create form's "Link to" field links the
 * new record in the same trip. Creating a Pain Point with a Persona chosen in that field leaves the
 * link visible in the Links panel of both records, with the Persona offered first.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded
 * state and can be repeated against the same database.
 */
test("creating a pain point with a persona chosen in 'Link to' links them, visible from both records", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "QuickLink");
  const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const personaName = `Field Technician ${suffix}`;
  const persona = await (
    await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
      headers: adminHeaders, data: { name: personaName },
    })
  ).json();
  const painPointTitle = `Reports arrive late ${suffix}`;

  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  await page.getByRole("button", { name: "New Pain Point" }).click();
  const dialog = page.getByRole("dialog", { name: "New Pain Point" });
  // A new organisation seeds Market, User and Operator pain point types; a type is required to save.
  await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Operator" });
  await dialog.getByLabel("Pain Point title").fill(painPointTitle);

  await test.step("the Persona is offered as soon as the field is focused", async () => {
    await dialog.getByRole("combobox", { name: "Link to" }).click();
    await dialog.getByRole("option", { name: new RegExp(personaName) }).click();
    const chosen = dialog.getByRole("list", { name: "Records to link" });
    await expect(chosen.getByText(new RegExp(personaName))).toBeVisible();
    // Several link types reach a persona, so the relationship is a select with "Related to" preselected.
    await expect(chosen.locator("option:checked")).toHaveText("Related to");
  });

  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByText("Linked to 1 record.")).toBeVisible();

  await test.step("the Pain Point's Links panel shows the Persona", async () => {
    await page.getByText(painPointTitle).first().click();
    const links = page.getByRole("region", { name: "Links", exact: true });
    await expect(links.getByRole("link", { name: new RegExp(personaName) })).toBeVisible();
  });

  await test.step("the Persona's Links panel shows the Pain Point", async () => {
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
    const links = page.getByRole("region", { name: "Links", exact: true });
    await expect(links.getByRole("link", { name: new RegExp(painPointTitle) })).toBeVisible();
  });
});
