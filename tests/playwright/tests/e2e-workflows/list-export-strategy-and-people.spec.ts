import fs from "node:fs";

import { expect, type Page, test } from "@playwright/test";

import { installCleanupHook } from "./helpers";
import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";
import { expectListAction, chooseExport } from "../listActions";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: take a Context & Strategy list (Pain Points) out as a file, change a cell in a spreadsheet and bring it
 * back so the same record changes; and see that a Stakeholder's personal data stays out of the file until the
 * organisation allows it, then appears.
 *
 * Each test builds its own disposable organisation through the API, so nothing here depends on seeded state or on
 * another test, and it can be repeated against the same database.
 */

/** Downloads the open list's CSV through the shared List actions menu and returns its text. `kind` is the heading of the record kind when the list shows several. */
async function exportCsv(page: Page, kind?: string): Promise<string> {
  const downloadPromise = page.waitForEvent("download");
  await chooseExport(page, "CSV", kind);
  return fs.readFileSync((await (await downloadPromise).path())!, "utf-8");
}

test("a Pain Point list exports, an edited title re-imports as an update of the same Pain Point", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "PainExport");
  const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const cs = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy`;
  const types = await (await page.request.get(`${cs}/pain-point-types`, { headers: adminHeaders })).json();
  const title = `E2E Export Pain Point ${suffix}`;
  const created = await (await page.request.post(`${cs}/pain-points`, {
    headers: adminHeaders, data: { pain_point_type_id: types[0].id, title, description: "Reports are late." },
  })).json();

  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  await expect(page.getByRole("button", { name: title })).toBeVisible();
  await expectListAction(page, "Import from CSV");

  const csv = await exportCsv(page);
  expect(csv).toContain(title);
  expect(csv).toContain(created.unique_code);
  expect(csv).toContain("Submitted");

  const edited = `${title} (edited)`;
  const modal = page.getByRole("dialog", { name: "Import Pain points" });
  await page.locator('input[type="file"][accept*="csv"]').setInputFiles({
    name: "edited.csv", mimeType: "text/csv", buffer: Buffer.from(csv.replace(title, edited)),
  });
  await modal.getByRole("button", { name: "Preview" }).click();
  await expect(modal.getByText("0 to create, 1 to update, 0 unchanged, 0 with errors.")).toBeVisible();
  await modal.getByRole("button", { name: "Apply 1 change(s)" }).click();
  await expect(page.getByText("0 created, 1 updated, 0 failed.")).toBeVisible();
  await expect
    .poll(async () => (await (await page.request.get(`${cs}/pain-points/${created.id}`, { headers: adminHeaders })).json()).title)
    .toBe(edited);
});

test("a Stakeholder's personal data is left out of the export until the organisation allows it", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "PeopleExport");
  const name = `Pat Regulator ${suffix}`;
  const persona = `Field Technician ${suffix}`;
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;
  expect((await page.request.post(`${base}/stakeholders`, { headers: adminHeaders, data: { name, role: "Auditor", contact_info: "pat@example.com" } })).ok()).toBeTruthy();
  expect((await page.request.post(`${base}/personas`, { headers: adminHeaders, data: { name: persona } })).ok()).toBeTruthy();

  await page.goto(`/projects/${project.id}/modules/stakeholders/people?kind=stakeholder`);
  await expect(page.getByRole("button", { name })).toBeVisible();

  const withheld = await exportCsv(page);
  expect(withheld).toContain("STK-001");
  expect(withheld).not.toContain(name);
  expect(withheld).not.toContain("pat@example.com");

  for (const tag of ["personal", "contact"]) {
    const allowed = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/record-sensitivity-policy/${tag}`, {
      headers: adminHeaders, data: { allowed: true },
    });
    expect(allowed.ok()).toBeTruthy();
  }
  await page.reload();
  await expect(page.getByRole("button", { name })).toBeVisible();
  const full = await exportCsv(page);
  expect(full).toContain(name);
  expect(full).toContain("pat@example.com");

  // Both kinds listed together: each kind has its own named Export, and a kind's file holds only that kind.
  await page.goto(`/projects/${project.id}/modules/stakeholders/people`);
  await expect(page.getByRole("button", { name: "List actions", exact: true })).toBeVisible();
  const personas = await exportCsv(page, "Personas");
  expect(personas).toContain(persona);
  expect(personas).not.toContain(name);
});
