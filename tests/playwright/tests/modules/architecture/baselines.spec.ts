import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/**
 * Job to be done: record what the architecture looked like when it was agreed, and see later what has moved. An architect takes a
 * baseline from the Baselines tab, opens it to read the records as they stood, and compares it with the live model after the
 * model changes.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the elements are created through the API as setup,
 * the baseline and the comparison through the UI.
 */
test.describe("System Architecture: baselines", () => {
  test("an architect takes a baseline, reads it and compares it with the live model after a change", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchBase", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${base}/element-types`, { headers: adminHeaders })).json();
    const gateway = `Gateway ${suffix}`;
    const cloud = `Cloud ${suffix}`;
    const made = [];
    for (const name of [gateway, cloud]) {
      const created = await page.request.post(`${base}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, activate: true } });
      expect(created.ok(), await created.text()).toBeTruthy();
      made.push(await created.json());
    }
    const baselineName = `Agreed ${suffix}`;

    await test.step("the Baselines tab starts empty and takes a baseline", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture?tab=baselines`);
      await expect(page.getByText("No baselines hold architecture records yet.")).toBeVisible();
      await page.getByRole("button", { name: "Take baseline", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Take baseline" });
      await dialog.getByRole("textbox", { name: /Name/ }).fill(baselineName);
      const stored = page.waitForResponse((r) => r.url().endsWith(`/projects/${project.id}/baselines`) && r.request().method() === "POST");
      await dialog.getByRole("button", { name: "Take baseline", exact: true }).click();
      expect((await stored).ok()).toBeTruthy();
      const row = page.getByRole("table", { name: "Baselines" }).getByRole("row", { name: new RegExp(baselineName) });
      await expect(row).toContainText("Manual");
      await expect(row).toContainText("2");
    });

    await test.step("the baseline lists its records and opens one as it stood", async () => {
      await page.getByRole("link", { name: baselineName }).click();
      const elements = page.getByRole("table", { name: "Elements" });
      await expect(elements.getByText(gateway)).toBeVisible();
      await expect(elements.getByText(cloud)).toBeVisible();
      await elements.getByRole("button", { name: /ELM-001/ }).click();
      const record = page.getByRole("dialog");
      await expect(record.getByText(gateway)).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("a rename and a new element show in the comparison with the live model", async () => {
      const renamed = await page.request.put(`${base}/elements/${made[0].id}`, { headers: adminHeaders, data: { version: made[0].version, name: `Edge ${gateway}` } });
      expect(renamed.ok(), await renamed.text()).toBeTruthy();
      const added = await page.request.post(`${base}/elements`, { headers: adminHeaders, data: { name: `Cache ${suffix}`, element_type_id: types[0].id } });
      expect(added.ok(), await added.text()).toBeTruthy();

      await page.reload();
      const compared = page.waitForResponse((r) => r.url().includes("/compare?against=live"));
      await page.getByRole("combobox", { name: "Compare with" }).selectOption("live");
      expect((await compared).ok()).toBeTruthy();
      const result = page.getByLabel("Comparison result");
      await expect(result.getByText(/compared with Live model/)).toBeVisible();
      await expect(result.getByText(`Cache ${suffix}`, { exact: false })).toBeVisible();
      await expect(result.getByText(`Edge ${gateway}`, { exact: false }).first()).toBeVisible();
    });
  });
});
