import fs from "node:fs";

import { expect, type Page, test } from "@playwright/test";

import { installCleanupHook } from "./helpers";
import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: take a Risk, Decision or Compliance Evidence list out as a file, change a cell in a spreadsheet and
 * bring it back so the same record changes; and see that a read-only compliance list exports but offers no import.
 *
 * Each test builds its own disposable organisation through the API, so nothing here depends on seeded state or on
 * another test, and it can be repeated against the same database.
 */

/** Downloads the open list's CSV through the shared Export menu and returns its text. `name` is the button's accessible name. */
async function exportCsv(page: Page, name = "Export"): Promise<string> {
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name, exact: true }).click();
  await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Download CSV report" }).click();
  return fs.readFileSync((await (await downloadPromise).path())!, "utf-8");
}

/** Enables a module for the organisation through the API. */
async function enableModule(page: Page, orgId: string, key: string, headers: Record<string, string>) {
  const enabled = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${orgId}/modules/${key}`, { headers, data: { enabled: true } });
  expect(enabled.ok()).toBeTruthy();
}

/** Applies an edited copy of the CSV through the Import wizard: preview, then apply. */
async function importEdited(page: Page, label: string, csv: string, previewText: string, appliedText: string) {
  const modal = page.getByRole("dialog", { name: `Import ${label}` });
  await page.locator('input[type="file"][accept*="csv"]').setInputFiles({ name: "edited.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await modal.getByRole("button", { name: "Preview" }).click();
  await expect(modal.getByText(previewText)).toBeVisible();
  await modal.getByRole("button", { name: "Apply 1 change(s)" }).click();
  await expect(page.getByText(appliedText)).toBeVisible();
}

test("a Risk register exports, an edited cause re-imports as an update of the same Risk", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "RiskExport");
  await enableModule(page, org.id, "risk_management", adminHeaders);
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/risk_management`;
  const title = `E2E Export Risk ${suffix}`;
  const created = await (await page.request.post(`${base}/risks`, { headers: adminHeaders, data: { title, cause: "Single supplier" } })).json();

  await page.goto(`/projects/${project.id}/modules/risk_management/risks`);
  await expect(page.getByRole("link", { name: created.unique_code })).toBeVisible();
  await expect(page.getByText("Import", { exact: true })).toBeVisible();

  const csv = await exportCsv(page);
  expect(csv).toContain(title);
  expect(csv).toContain(created.unique_code);
  expect(csv).toContain("Identified");

  await importEdited(page, "Risks", csv.replace("Single supplier", "Supplier went bankrupt"), "0 to create, 1 to update, 0 unchanged, 0 with errors.", "0 created, 1 updated, 0 failed.");
  await expect
    .poll(async () => (await (await page.request.get(`${base}/risks/${created.id}`, { headers: adminHeaders })).json()).cause)
    .toBe("Supplier went bankrupt");
});

test("a Decisions list exports, an edited rationale re-imports as an update and the status stays with the workflow", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "DecisionExport");
  await enableModule(page, org.id, "decisions", adminHeaders);
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/decisions`;
  const types = await (await page.request.get(`${base}/decision-types`, { headers: adminHeaders })).json();
  const title = `E2E Export Decision ${suffix}`;
  const created = await (
    await page.request.post(base, {
      headers: adminHeaders, data: { title, decision_statement: "We will use Postgres.", decision_type_id: types[0].id, rationale: "Familiar" },
    })
  ).json();

  await page.goto(`/projects/${project.id}/modules/decisions`);
  await expect(page.getByRole("link", { name: created.unique_code })).toBeVisible();
  await expect(page.getByText("Import", { exact: true })).toBeVisible();

  const csv = await exportCsv(page);
  expect(csv).toContain(title);
  expect(csv).toContain("Draft");

  await importEdited(page, "Decisions", csv.replace("Familiar", "Cheaper to run"), "0 to create, 1 to update, 0 unchanged, 0 with errors.", "0 created, 1 updated, 0 failed.");
  await expect
    .poll(async () => (await (await page.request.get(`${base}/${created.id}`, { headers: adminHeaders })).json()).rationale)
    .toBe("Cheaper to run");
  const decision = await (await page.request.get(`${base}/${created.id}`, { headers: adminHeaders })).json();
  expect(decision.status).toBe("draft");
});

test("Compliance evidence exports and re-imports, while the outstanding required actions export with no import", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "EvidenceExport");
  await enableModule(page, org.id, "compliance", adminHeaders);
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/compliance`;
  const title = `E2E Export Evidence ${suffix}`;
  const created = await (await page.request.post(`${base}/evidence`, { headers: adminHeaders, data: { title, notes: "Lab report" } })).json();

  await page.goto(`/projects/${project.id}/modules/compliance?tab=evidence`);
  await expect(page.getByRole("link", { name: title })).toBeVisible();
  await expect(page.getByText("Import", { exact: true })).toBeVisible();

  const csv = await exportCsv(page);
  expect(csv).toContain(title);
  expect(csv).toContain(created.unique_code);
  expect(csv).toContain("No expiry");

  await importEdited(page, "Evidence", csv.replace("Lab report", "Lab report v2"), "0 to create, 1 to update, 0 unchanged, 0 with errors.", "0 created, 1 updated, 0 failed.");
  await expect
    .poll(async () => (await (await page.request.get(`${base}/evidence/${created.id}`, { headers: adminHeaders })).json()).notes)
    .toBe("Lab report v2");

  await page.goto(`/projects/${project.id}/modules/compliance?tab=outstanding`);
  await expect(page.getByRole("button", { name: "Export outstanding required actions", exact: true })).toBeVisible();
  await expect(page.getByText("Import outstanding required actions", { exact: true })).toHaveCount(0);
});
