import fs from "node:fs";

import { expect, type Page, test } from "@playwright/test";

import { installCleanupHook, selectOrgOverviewGroup } from "./helpers";
import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: take the organisation's own Personas out of the organisation overview as a file, change a cell in a
 * spreadsheet and bring it back so the same organisation Persona changes, while a project's Persona with the same
 * name stays out of the file; and get the same list as a Word document.
 *
 * Each test builds its own disposable organisation through the API, so nothing here depends on seeded state or on
 * another test, and it can be repeated against the same database.
 */

async function openOrgPersonas(page: Page): Promise<void> {
  await page.goto("/org-overview");
  await selectOrgOverviewGroup(page, "Personas");
}

test("the organisation's Personas export, an edited goal re-imports as an update, and a project's Persona stays out", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "OrgPersonaExport");
  const orgPersona = `Org Persona ${suffix}`;
  const projectPersona = `Project Persona ${suffix}`;
  const created = await (await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/personas`, {
    headers: adminHeaders, data: { name: orgPersona, goals: "Original goal" },
  })).json();
  expect((await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
    headers: adminHeaders, data: { name: projectPersona },
  })).ok()).toBeTruthy();

  await openOrgPersonas(page);
  await expect(page.getByText(orgPersona)).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Download CSV report" }).click();
  const csv = fs.readFileSync((await (await downloadPromise).path())!, "utf-8");
  expect(csv).toContain(orgPersona);
  expect(csv).toContain(created.unique_code);
  expect(csv).not.toContain(projectPersona);

  const modal = page.getByRole("dialog", { name: "Import Personas" });
  await page.locator('input[type="file"][accept*="csv"]').setInputFiles({
    name: "edited.csv", mimeType: "text/csv", buffer: Buffer.from(csv.replace("Original goal", "Edited goal")),
  });
  await modal.getByRole("button", { name: "Preview" }).click();
  await expect(modal.getByText("0 to create, 1 to update, 0 unchanged, 0 with errors.")).toBeVisible();
  await modal.getByRole("button", { name: "Apply 1 change(s)" }).click();
  await expect(page.getByText("0 created, 1 updated, 0 failed.")).toBeVisible();
  await expect
    .poll(async () => (await (await page.request.get(
      `${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/personas/${created.id}`, { headers: adminHeaders },
    )).json()).goals)
    .toBe("Edited goal");
});

test("the organisation's Personas also download as a Word document", async ({ page }) => {
  const { suffix, org, adminHeaders } = await setUpOrg(page, "OrgPersonaWord");
  const name = `Word Persona ${suffix}`;
  expect((await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/personas`, {
    headers: adminHeaders, data: { name },
  })).ok()).toBeTruthy();

  await openOrgPersonas(page);
  await expect(page.getByText(name)).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Download Word report" }).click();
  const file = await downloadPromise;
  expect(file.suggestedFilename()).toMatch(/\.docx$/);
  expect(fs.readFileSync((await file.path())!).subarray(0, 2).toString()).toBe("PK");
});
