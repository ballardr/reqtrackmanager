import fs from "node:fs";

import { expect, type Page, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";
import { chooseExport } from "../listActions";

/**
 * Job to be done: bulk-importing requirements from a CSV whose headers don't match the server's column names
 * (column mapping, a preview of what would change, per-row error reporting), and exporting the list as the
 * file that re-imports, so an edited export updates the same records.
 *
 * Each test works in its own disposable project (2026-10-04): the round-trip test once exported *every*
 * requirement in a shared project and re-imported them all, doubling it on each run.
 */
test.describe("CSV import wizard", () => {
  installCleanupHook();

  /** Creates the test's disposable project and opens its requirements list (Export and Import loaded). */
  async function openImportProject(page: Page, label: string) {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, label);
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}`);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await expect(page.getByRole("button", { name: "List actions", exact: true })).toBeVisible();
    return project;
  }

  test("upload, mapped columns, preview, apply with one deliberately bad row", async ({ page }) => {
    const { components, categories } = await openImportProject(page, "E2E CSV Import");
    const component = components[0];
    const category = categories.find((c) => c.component_id === component.id)!;

    const rowOneTitle = `E2E CSV Import Row One (${Date.now()})`;
    const csv =
      "Title,Comp,Cat,Why\n" +
      `${rowOneTitle},${component.prefix},${category.prefix},Because it must.\n` +
      `E2E CSV Import Row Two Bad Component (${Date.now()}),ZZZ-NO-SUCH,${category.prefix},Should error.\n`;

    const modal = page.getByRole("dialog", { name: "Import Requirements" });
    await test.step("upload a CSV with non-canonical headers and map each column", async () => {
      await page.locator('input[type="file"][accept*="csv"]').setInputFiles({
        name: "my-requirements.csv", mimeType: "text/csv", buffer: Buffer.from(csv),
      });
      await expect(modal).toBeVisible();
      await expect(modal.getByRole("button", { name: "Preview" })).toBeDisabled();
      await modal.getByLabel("Map Name").selectOption("Title");
      await modal.getByLabel("Map Component").selectOption("Comp");
      await modal.getByLabel("Map Category").selectOption("Cat");
      await modal.getByLabel("Map Reasoning").selectOption("Why");
      await expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled();
    });

    await test.step("the preview says what would happen and writes nothing", async () => {
      await modal.getByRole("button", { name: "Preview" }).click();
      await expect(modal.getByText("1 to create, 0 to update, 0 unchanged, 1 with errors.")).toBeVisible();
      await expect(modal.getByText(/Row 3: .*ZZZ-NO-SUCH/)).toBeVisible();
    });

    await test.step("applying creates the good row, reports the bad one and offers an error file", async () => {
      await modal.getByRole("button", { name: "Apply 1 change(s)" }).click();
      // The toast and the wizard's own summary both say it: the toast fades, the summary stays beside the failed rows.
      await expect(modal.getByText("1 created, 0 updated, 1 failed.")).toBeVisible();
      await expect(page.getByText("1 created, 0 updated, 1 failed.")).toHaveCount(2);
      await expect(modal.getByText(/ZZZ-NO-SUCH/)).toBeVisible();
      const downloadPromise = page.waitForEvent("download");
      await modal.getByRole("button", { name: "Download error file" }).click();
      const errorFile = fs.readFileSync((await (await downloadPromise).path())!, "utf-8");
      expect(errorFile).toContain("ZZZ-NO-SUCH");
      await modal.getByRole("button", { name: "Close", exact: true }).filter({ hasText: "Close" }).click();
      await expect(modal).toHaveCount(0);
      await expect(page.getByText(rowOneTitle, { exact: true })).toBeVisible();
    });
  });

  /**
   * Job to be done: a full-fidelity export (custom field values, target stage) that comes back unchanged, and
   * that updates the same records when a cell is edited in a spreadsheet.
   */
  test("export includes a custom field value, re-imports unchanged, and an edited cell updates the record", async ({ page }) => {
    const { projectId, headers: authHeaders, components, categories } = await openImportProject(page, "E2E CSV Round Trip");
    const fieldName = `E2E Priority ${Date.now()}`;
    const fieldResp = await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/custom-fields`, {
      headers: authHeaders, data: { entity_kind: "requirement", name: fieldName, field_type: "short_text" },
    });
    expect(fieldResp.ok()).toBeTruthy();
    const field = await fieldResp.json();

    const component = components[0];
    const category = categories.find((c) => c.component_id === component.id)!;
    const reqName = `E2E Export Round Trip (${Date.now()})`;
    const createResp = await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/requirements`, {
      headers: authHeaders,
      data: { name: reqName, component_id: component.id, category_id: category.id, custom_fields: { [field.id]: "Urgent" } },
    });
    expect(createResp.ok()).toBeTruthy();
    const created = await createResp.json();

    await page.reload();
    await expect(page.getByText(reqName, { exact: true })).toBeVisible();
    const downloadPromise = page.waitForEvent("download");
    await chooseExport(page, "CSV");
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("requirements-export.csv");
    const exportedCsv = fs.readFileSync((await download.path())!, "utf-8");
    expect(exportedCsv).toContain(`cf_${fieldName}`);
    expect(exportedCsv).toContain(reqName);
    expect(exportedCsv).toContain("Urgent");

    const modal = page.getByRole("dialog", { name: "Import Requirements" });
    const fileInput = page.locator('input[type="file"][accept*="csv"]');

    await test.step("the exported file re-imports with nothing to change", async () => {
      await fileInput.setInputFiles({ name: "reexport.csv", mimeType: "text/csv", buffer: Buffer.from(exportedCsv) });
      await expect(modal.getByLabel("Map Code")).toHaveValue("code");
      await modal.getByRole("button", { name: "Preview" }).click();
      await expect(modal.getByText("0 to create, 0 to update, 1 unchanged, 0 with errors.")).toBeVisible();
      await expect(modal.getByRole("button", { name: "Apply 0 change(s)" })).toBeDisabled();
      await modal.getByRole("button", { name: "Cancel" }).click();
      await expect(modal).toHaveCount(0);
    });

    await test.step("an edited cell previews as an update with before and after, and applying changes the record", async () => {
      await fileInput.setInputFiles({
        name: "edited.csv", mimeType: "text/csv", buffer: Buffer.from(exportedCsv.replace("Urgent", "Critical")),
      });
      await modal.getByRole("button", { name: "Preview" }).click();
      await expect(modal.getByText("0 to create, 1 to update, 0 unchanged, 0 with errors.")).toBeVisible();
      const change = modal.getByRole("row", { name: new RegExp(fieldName) });
      await expect(change).toContainText("Urgent");
      await expect(change).toContainText("Critical");
      await modal.getByRole("button", { name: "Apply 1 change(s)" }).click();
      await expect(page.getByText("0 created, 1 updated, 0 failed.")).toBeVisible();
      await expect(modal).toHaveCount(0);
      await expect
        .poll(async () => {
          const resp = await page.request.get(
            `http://localhost:8000/api/v1/projects/${projectId}/requirements/${created.id}`, { headers: authHeaders },
          );
          return (await resp.json()).custom_fields[field.id];
        })
        .toBe("Critical");
    });
  });
});
