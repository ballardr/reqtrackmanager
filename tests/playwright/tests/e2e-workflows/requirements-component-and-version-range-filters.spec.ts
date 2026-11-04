import { expect, test } from "@playwright/test";

import { chooseExport } from "../listActions";
import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: narrow the requirements list by component and by a range of target versions, so the list's
 * Export and Download report carry exactly those rows (the requirement report's old filter section is gone).
 *
 * Works in its own disposable project: three stages in order, one requirement per stage in Hardware and one in
 * Software, so the spec never depends on or alters seeded data. A link with the older single `stage` parameter
 * still opens as a range of one version.
 */
test.describe("requirements list: component and target version range", () => {
  installCleanupHook();
  const API = "http://localhost:8000/api/v1";

  test("component and version range narrow the list, the export and the old stage link", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Version Range");
    const { headers, projectId } = project;
    const [hw, sw] = project.components;
    const [fn, perf] = project.categories;
    const stamp = Date.now();

    for (const name of ["Second", "Third"]) {
      const made = await page.request.post(`${API}/projects/${projectId}/stages`, { headers, data: { name: `${name} ${stamp}` } });
      expect(made.ok(), await made.text()).toBeTruthy();
    }
    const stages: { id: string; name: string; sort_order: number }[] = await (
      await page.request.get(`${API}/projects/${projectId}/stages`, { headers })
    ).json();
    stages.sort((a, b) => a.sort_order - b.sort_order);
    expect(stages).toHaveLength(3);

    const names = stages.map((_, i) => `E2E Range Hardware ${i} ${stamp}`);
    const softwareName = `E2E Range Software 0 ${stamp}`;
    for (const [i, stage] of stages.entries()) {
      const made = await page.request.post(`${API}/projects/${projectId}/requirements`, {
        headers, data: { name: names[i], component_id: hw.id, category_id: fn.id, target_stage_id: stage.id },
      });
      expect(made.ok(), await made.text()).toBeTruthy();
    }
    const soft = await page.request.post(`${API}/projects/${projectId}/requirements`, {
      headers, data: { name: softwareName, component_id: sw.id, category_id: perf.id, target_stage_id: stages[0].id },
    });
    expect(soft.ok(), await soft.text()).toBeTruthy();

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}/requirements`);
    await expect(page.getByText(names[0])).toBeVisible();

    await test.step("the component filter keeps only that component", async () => {
      await page.getByRole("combobox", { name: "Component" }).selectOption(sw.id);
      await expect(page.getByText(softwareName)).toBeVisible();
      await expect(page.getByText(names[0])).toHaveCount(0);
      await page.getByRole("combobox", { name: "Component" }).selectOption("");
      await expect(page.getByText(names[0])).toBeVisible();
    });

    await test.step("a version range keeps the versions between its ends, by their order", async () => {
      await page.getByLabel("Target version from").selectOption(stages[1].id);
      await expect(page.getByText(names[1])).toBeVisible();
      await expect(page.getByText(names[2])).toBeVisible();
      await expect(page.getByText(names[0])).toHaveCount(0);

      await page.getByLabel("Target version to").selectOption(stages[1].id);
      await expect(page.getByText(names[1])).toBeVisible();
      await expect(page.getByText(names[2])).toHaveCount(0);
      await expect(page).toHaveURL(/stage_from=/);
      await expect(page).toHaveURL(/stage_to=/);
    });

    await test.step("Export asks for the same range", async () => {
      const exported = page.waitForResponse(
        (r) => r.url().includes("/records/requirement/export") && r.url().includes(`target_stage_from_id=${stages[1].id}`),
      );
      await chooseExport(page, "CSV");
      const response = await exported;
      expect(response.url()).toContain(`target_stage_to_id=${stages[1].id}`);
      // The rows the server keeps for these parameters are pinned by the backend tests.
      expect(response.status()).toBe(200);
    });

    await test.step("a link with the older single version parameter reads as a range of one", async () => {
      await page.goto(`/projects/${projectId}/requirements?stage=${stages[2].id}`);
      await expect(page.getByText(names[2])).toBeVisible();
      await expect(page.getByText(names[1])).toHaveCount(0);
      await expect(page.getByLabel("Target version from")).toHaveValue(stages[2].id);
      await expect(page.getByLabel("Target version to")).toHaveValue(stages[2].id);
    });
  });
});
