import fs from "node:fs";

import { expect, type Page, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";
import { chooseListAction, expectListAction } from "../listActions";

/**
 * Job to be done: take a list of actions out as a file, edit a cell in a spreadsheet and bring it back so the same
 * action changes; and take the change request list out as a file (a change request has no import: it is a proposal
 * authored in its form and decided by an approver).
 *
 * Each test works in its own disposable project, so nothing here depends on another test or an earlier run.
 */
test.describe("Export and import on the Actions and Change requests lists", () => {
  installCleanupHook();

  const API = "http://localhost:8000/api/v1";

  /** Downloads the open list's CSV through the shared Export menu and returns its text. */
  async function exportCsv(page: Page): Promise<string> {
    const downloadPromise = page.waitForEvent("download");
    await chooseListAction(page, "Export as CSV");
    return fs.readFileSync((await (await downloadPromise).path())!, "utf-8");
  }

  test("an action list exports, an edited title re-imports as an update of the same action", async ({ page }) => {
    const { projectId, headers } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Action Export");
    const types: { id: string }[] = await (await page.request.get(`${API}/projects/${projectId}/action-types`, { headers })).json();
    const title = `E2E Export Action ${Date.now()}`;
    const createResp = await page.request.post(`${API}/projects/${projectId}/actions`, {
      headers, data: { title, action_type_id: types[0].id },
    });
    expect(createResp.ok()).toBeTruthy();
    const created = await createResp.json();

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}`);
    await page.getByRole("link", { name: "Actions", exact: true }).click();
    await expect(page.getByText(title, { exact: true })).toBeVisible();
    await expectListAction(page, "Import from CSV");

    const csv = await exportCsv(page);
    expect(csv).toContain(title);
    expect(csv).toContain(created.unique_code);

    const modal = page.getByRole("dialog", { name: "Import Actions" });
    const edited = `${title} (edited)`;
    await page.locator('input[type="file"][accept*="csv"]').setInputFiles({
      name: "edited.csv", mimeType: "text/csv", buffer: Buffer.from(csv.replace(title, edited)),
    });
    await modal.getByRole("button", { name: "Preview" }).click();
    await expect(modal.getByText("0 to create, 1 to update, 0 unchanged, 0 with errors.")).toBeVisible();
    await modal.getByRole("button", { name: "Apply 1 change(s)" }).click();
    await expect(page.getByText("0 created, 1 updated, 0 failed.")).toBeVisible();
    await expect
      .poll(async () => (await (await page.request.get(`${API}/projects/${projectId}/actions/${created.id}`, { headers })).json()).title)
      .toBe(edited);
  });

  test("a change request list exports with the page's filter and offers no import", async ({ page }) => {
    const { projectId, headers } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E CR Export");
    const name = `E2E Export Change ${Date.now()}`;
    const createResp = await page.request.post(`${API}/projects/${projectId}/change-requests`, {
      headers, data: { kind: "new_requirement", proposed_name: name, reason: "Exported by the e2e suite" },
    });
    expect(createResp.ok()).toBeTruthy();
    const created = await createResp.json();
    const withdrawnName = `E2E Withdrawn Change ${Date.now()}`;
    const withdrawn = await (await page.request.post(`${API}/projects/${projectId}/change-requests`, {
      headers, data: { kind: "new_requirement", proposed_name: withdrawnName, reason: "Will be withdrawn" },
    })).json();
    expect((await page.request.post(`${API}/projects/${projectId}/change-requests/${withdrawn.id}/withdraw`, { headers })).ok()).toBeTruthy();

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}`);
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await expect(page.getByRole("link", { name })).toBeVisible();
    await expect(page.getByRole("button", { name: "List actions", exact: true })).toBeVisible();
    await expectListAction(page, "Import from CSV", false);

    // The default view is "Active", so the file holds what the page shows: the draft, not the withdrawn request.
    const csv = await exportCsv(page);
    expect(csv).toContain(created.unique_code);
    expect(csv).toContain("New requirement");
    expect(csv).toContain("Exported by the e2e suite");
    expect(csv).not.toContain(withdrawnName);
  });
});
