import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: bulk-importing requirements from a CSV whose headers
 * don't already match the backend's canonical field names — column
 * mapping, a preview, and per-row error reporting for rows that reference
 * a component/category prefix that doesn't exist.
 */
test.describe("CSV import wizard", () => {
  test("upload, auto-mapped columns, preview, import with one deliberately bad row", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.beta1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
    const [componentsResp, categoriesResp] = await Promise.all([
      page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/components`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
      page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/categories`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    ]);
    const components: { id: string; prefix: string }[] = await componentsResp.json();
    const categories: { id: string; prefix: string; component_id: string }[] = await categoriesResp.json();
    const component = components[0];
    const category = categories.find((c) => c.component_id === component.id)!;

    const csv =
      "Title,Comp,Cat,Why\n" +
      `E2E CSV Import Row One (${Date.now()}),${component.prefix},${category.prefix},Because it must.\n` +
      `E2E CSV Import Row Two Bad Component (${Date.now()}),ZZZ-NO-SUCH,${category.prefix},Should error.\n`;

    await test.step("upload a CSV with non-canonical headers and confirm auto-mapping", async () => {
      const fileInput = page.locator('input[type="file"][accept*="csv"]');
      await fileInput.setInputFiles({ name: "my-requirements.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
      await expect(page.getByText("Map your CSV columns")).toBeVisible();
      // Non-standard headers ("Title"/"Comp"/"Cat"/"Why") don't auto-match
      // any canonical field, so every mapping must be picked manually.
      const fieldRow = (label: string) => page.locator("tr", { hasText: label }).first();
      await fieldRow("Name").getByRole("combobox").selectOption("Title");
      await fieldRow("Component").getByRole("combobox").selectOption("Comp");
      await fieldRow("Category").getByRole("combobox").selectOption("Cat");
      await fieldRow("Reasoning").getByRole("combobox").selectOption("Why");
    });

    await test.step("the preview reflects the mapped columns", async () => {
      await expect(page.getByText("Preview (first 2 of 2 rows)")).toBeVisible();
      await expect(page.getByText("Because it must.")).toBeVisible();
    });

    await test.step("importing reports one created row and one error", async () => {
      await page.getByRole("button", { name: /^Import 2 row/ }).click();
      await expect(page.getByText("Import complete: 1 created, 1 error(s)")).toBeVisible();
      await expect(page.getByText(/ZZZ-NO-SUCH/)).toBeVisible();
      await expect(page.getByText(new RegExp(`E2E CSV Import Row One`))).toBeVisible();
    });
  });

  /**
   * Job to be done: a full-fidelity export (custom field values, target
   * stage) that's directly re-importable elsewhere without hand-editing —
   * exercised end-to-end rather than just at the API level, since the
   * export's column set/labels are UI-owned (CsvImportWizard's FIELDS list
   * must stay in sync with the backend's column contract).
   */
  test("export includes a custom field value and re-imports unchanged", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.beta2).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
    const authHeaders = { Authorization: `Bearer ${token}` };
    const fieldName = `E2E Priority ${Date.now()}`;
    const fieldResp = await page.request.post(
      `http://localhost:8000/api/v1/projects/${projectId}/custom-fields`,
      { headers: authHeaders, data: { entity_kind: "requirement", name: fieldName, field_type: "short_text" } }
    );
    expect(fieldResp.ok()).toBeTruthy();
    const field = await fieldResp.json();

    const components: { id: string; prefix: string }[] = await (
      await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/components`, { headers: authHeaders })
    ).json();
    const categories: { id: string; prefix: string; component_id: string }[] = await (
      await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/categories`, { headers: authHeaders })
    ).json();
    const component = components[0];
    const category = categories.find((c) => c.component_id === component.id)!;
    const reqName = `E2E Export Round Trip (${Date.now()})`;
    const createResp = await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/requirements`, {
      headers: authHeaders,
      data: {
        name: reqName, component_id: component.id, category_id: category.id,
        custom_fields: { [field.id]: "Urgent" },
      },
    });
    expect(createResp.ok()).toBeTruthy();

    await page.reload();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Export CSV" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/-requirements-export\.csv$/);
    const exportedPath = await download.path();
    const exportedCsv = fs.readFileSync(exportedPath!, "utf-8");
    expect(exportedCsv).toContain(`cf_${fieldName}`);
    expect(exportedCsv).toContain(reqName);
    expect(exportedCsv).toContain("Urgent");

    await test.step("the exported file re-imports into the same project without errors", async () => {
      const fileInput = page.locator('input[type="file"][accept*="csv"]');
      await fileInput.setInputFiles({ name: "reexport.csv", mimeType: "text/csv", buffer: fs.readFileSync(exportedPath!) });
      await expect(page.getByText("Map your CSV columns")).toBeVisible();
      // The exported file is already canonically headed, so every field
      // auto-maps — including the dynamic `cf_<name>` column.
      const importButton = page.getByRole("button", { name: /^Import \d+ row/ });
      await expect(importButton).toBeEnabled();
      await importButton.click();
      await expect(page.getByText(/Import complete: \d+ created, 0 error\(s\)/)).toBeVisible();
    });
  });
});
