import { expect, test } from "@playwright/test";

import {
  closeDesignerPreview, createDocumentLayoutWorld, designerPreviewPanel, ensureExpanded, installCleanupHook, loginAs, openDesignerPreview, PASSWORD,
  saveNewVersion,
} from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: colour every table's heading row once, in the layout, instead of on each table. The Look group's Table
 * heading fill and text colour set it, a sample row shows the result, the preview draws a custom table's heading cells in
 * it unless a cell has a colour of its own, and the text view states it on one line.
 *
 * Works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout table heading colours", () => {
  installCleanupHook();

  test("the layout's heading fill colours a custom table's heading row, a cell's own fill wins, and reset restores the default", async ({ page, request }) => {
    const { adminEmail, headers, project, layout } = await createDocumentLayoutWorld(request, "heading-colours");
    // A custom table with a heading row of two cells; the second sets its own fill.
    const tree = {
      schema_version: 1, family: "document",
      nodes: [{
        type: "grid", header_rows: 1, columns: [{}, {}],
        rows: [
          { cells: [{ text: "Plain heading" }, { text: "Own fill heading", fill: "white" }] },
          { cells: [{ text: "Body one" }, { text: "Body two" }] },
        ],
      }],
    };
    const saved = await request.put(`${API}/projects/${project.id}/report-layouts/${layout.id}/tree`, { headers, data: { tree, base_version: 1 } });
    expect(saved.ok(), await saved.text()).toBeTruthy();

    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);
    await page.getByRole("tab", { name: "Blocks" }).click();

    await test.step("the Look group sets the fill and the sample row shows it", async () => {
      await page.locator(".blocklyText", { hasText: /^Layout$/ }).click();
      const inspector = page.getByLabel("Block details");
      await ensureExpanded(page, "Look");
      await inspector.getByRole("button", { name: /^Table heading fill: / }).click();
      await page.getByRole("button", { name: /^Black/ }).click();
      const sample = inspector.getByRole("table", { name: "Sample table heading" });
      await expect(sample.getByRole("columnheader", { name: "Code" })).toHaveCSS("background-color", "rgb(0, 0, 0)");
      await expect(sample.getByRole("columnheader", { name: "Code" })).toHaveCSS("color", "rgb(255, 255, 255)");
    });

    await test.step("the preview draws the plain heading cell in it and keeps the cell's own fill", async () => {
      await openDesignerPreview(page);
      const preview = designerPreviewPanel(page);
      await preview.getByRole("button", { name: "Run preview" }).click();
      const frame = preview.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("th, td", { hasText: "Plain heading" }).first()).toHaveCSS("background-color", "rgb(0, 0, 0)");
      await expect(frame.locator("th, td", { hasText: "Own fill heading" }).first()).toHaveCSS("background-color", "rgb(255, 255, 255)");
      await expect(frame.locator("th, td", { hasText: "Body one" }).first()).not.toHaveCSS("background-color", "rgb(0, 0, 0)");
      await closeDesignerPreview(page);
    });

    await test.step("saving writes one @tableheadings line to the text view", async () => {
      await saveNewVersion(page);
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@tableheadings fill=black/);
    });

    await test.step("Page setup shows the same colour, and resetting it removes the line", async () => {
      await page.getByRole("button", { name: /^Page setup: / }).click();
      const dialog = page.getByRole("dialog", { name: "Page setup" });
      await ensureExpanded(page, "Look");
      await dialog.getByRole("button", { name: /^Table heading fill: Black/ }).click();
      await page.getByRole("button", { name: "Default (the organisation's accent)" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).not.toHaveValue(/@tableheadings/);
    });
  });
});
