import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, type APIRequestContext, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, openSetupReport, PASSWORD, saveNewVersion, selectProjectAdminGroup, closeDialogWithoutSaving } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: build a document-details or sign-off table in the designer without writing text: select cells on a drawn
 * grid, merge them, colour whole columns, align one cell, and have the saved layout print the same in Word, PDF and HTML.
 *
 * The test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout custom table editor", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** The text of `word/document.xml` inside a Word file. */
  function wordXml(bytes: Buffer): string {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "grid-docx-"));
    const file = path.join(dir, "report.docx");
    fs.writeFileSync(file, bytes);
    return execFileSync("unzip", ["-p", file, "word/document.xml"], { encoding: "utf8" });
  }

  test("a 3 x 4 table is built, merged, coloured and aligned in the editor, then saved and printed in Word, PDF and HTML", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-grid-editor-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Grid editor ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Grid Editor Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Grid editor project ${suffix}`, summary: "" } })).json();
    const name = `E2E grid editor ${suffix}`;
    const created = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: { name, description: "", family: "document", tree: { schema_version: 1, family: "document", nodes: [] } },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const layoutId = (await created.json()).id as string;

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, name);
    await page.getByRole("tab", { name: "Blocks" }).click();

    await test.step("Table (custom) is added; the panel shows a summary and an Edit table button, not the cells", async () => {
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Table (custom)", exact: true }).click();
      const inspector = page.getByLabel("Block details");
      await expect(inspector.getByTestId("grid-summary")).toHaveText("2 columns · 1 row");
      await expect(inspector.getByRole("grid")).toHaveCount(0);
      await inspector.getByRole("button", { name: "Edit table" }).click();
    });

    const editor = page.getByRole("dialog", { name: "Edit custom table" });
    const cell = (row: number, column: number) => editor.getByLabel(new RegExp(`^Row ${row}, column ${column}(:|$)`));

    await test.step("add a column and three rows to make 3 columns x 4 rows", async () => {
      await cell(1, 2).click();
      await editor.getByRole("button", { name: "Add column right" }).click();
      for (let i = 0; i < 3; i += 1) await editor.getByRole("button", { name: "Add row below" }).click();
      await expect(editor.getByRole("gridcell")).toHaveCount(12);
    });

    await test.step("type the text of a few cells in the field under the grid", async () => {
      await cell(1, 1).click();
      await editor.getByRole("textbox", { name: "Text of row 1, column 1" }).fill("Document");
      await cell(2, 1).click();
      await editor.getByRole("textbox", { name: "Text of row 2, column 1" }).fill("Reviewed by");
      await cell(2, 3).click();
      await editor.getByRole("textbox", { name: "Text of row 2, column 3" }).fill("Signed");
      await expect(cell(1, 1)).toContainText("Document");
    });

    await test.step("select two cells with Shift+click and merge them", async () => {
      await cell(3, 2).click();
      await cell(4, 2).click({ modifiers: ["Shift"] });
      await expect(editor.locator('[role="gridcell"][aria-selected="true"]')).toHaveCount(2);
      await editor.getByRole("button", { name: "Merge cells", exact: true }).click();
      await expect(editor.getByRole("gridcell")).toHaveCount(11);
      await expect(cell(3, 2)).toHaveAttribute("aria-rowspan", "2");
      await expect(editor.getByText("Cells merged.")).toBeVisible();
    });

    await test.step("columns 1 and 3 are black with white bold text, in two clicks each", async () => {
      for (const column of [1, 3]) {
        await cell(1, column).click();
        await editor.getByRole("combobox", { name: "Apply to" }).selectOption({ label: "Whole columns of the selection" });
        await editor.getByRole("button", { name: /^Fill:/ }).click();
        await page.getByRole("button", { name: /^Black/ }).click();
        await editor.getByRole("button", { name: /^Text colour:/ }).click();
        await page.getByRole("button", { name: /^White/ }).click();
        await editor.getByRole("button", { name: "Bold", exact: true }).click();
      }
      await expect(cell(2, 1)).toHaveCSS("background-color", "rgb(0, 0, 0)");
      await expect(cell(4, 3)).toHaveCSS("background-color", "rgb(0, 0, 0)");
      await expect(cell(2, 2)).not.toHaveCSS("background-color", "rgb(0, 0, 0)");
    });

    await test.step("one cell is right-aligned", async () => {
      await editor.getByRole("combobox", { name: "Apply to" }).selectOption({ label: "Selected cells" });
      await cell(2, 2).click();
      await editor.getByRole("button", { name: "Align right" }).click();
      await expect(editor.getByRole("button", { name: "Align right", pressed: true })).toBeVisible();
    });

    await test.step("Cancel would discard; Save keeps the table and the panel summary counts the merge", async () => {
      await editor.getByRole("button", { name: "Save", exact: true }).click();
      await expect(editor).toHaveCount(0);
      await expect(page.getByLabel("Block details").getByTestId("grid-summary")).toHaveText("3 columns · 4 rows · 1 merged");
    });

    await test.step("the layout saves with no problems", async () => {
      await expect(page.getByText("No problems.")).toBeVisible();
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
    });

    const run = async (format: string) => {
      const response = await request.get(`${API}/projects/${project.id}/custom-reports/${layoutId}/run`, { headers, params: { format } });
      expect(response.ok(), await response.text()).toBeTruthy();
      return response.body();
    };

    await test.step("the Word file carries the merge, the black fill, the white bold text and the right alignment", async () => {
      const xml = wordXml(await run("docx"));
      expect(xml).toContain('<w:vMerge w:val="restart"/>');
      expect(xml).toMatch(/<w:shd [^>]*w:fill="000000"/);
      expect(xml).toMatch(/<w:color w:val="FFFFFF"\/>/);
      expect(xml).toMatch(/<w:jc w:val="right"\/>/);
      expect(xml).toContain("Reviewed by");
    });

    await test.step("the HTML carries the same merge, fills and alignment", async () => {
      const html = (await run("html")).toString("utf8");
      expect(html).toMatch(/rowspan="2"/);
      expect(html).toMatch(/background[^;"]*#000000/i);
      expect(html).toContain("Signed");
      expect(html).not.toContain("<script");
    });

    await test.step("the PDF is a real document", async () => {
      expect((await run("pdf")).subarray(0, 5).toString()).toBe("%PDF-");
    });

    await test.step("reopening the editor shows the saved table; a click outside does nothing and closing asks before discarding", async () => {
      await page.reload();
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.locator(".blocklyText.rl-block-title", { hasText: /^Table.\(custom\)/ }).first().click();
      const inspector = page.getByLabel("Block details");
      await expect(inspector.getByTestId("grid-summary")).toHaveText("3 columns · 4 rows · 1 merged");
      await inspector.getByRole("button", { name: "Edit table" }).click();
      await expect(editor.getByRole("gridcell")).toHaveCount(11);
      await cell(1, 1).click();
      await editor.getByRole("button", { name: "Remove row" }).click();
      await expect(editor.getByRole("gridcell")).toHaveCount(8);
      // A click outside the dialog does nothing: the edit is still there.
      await page.mouse.click(5, 5);
      await expect(editor).toBeVisible();
      await expect(editor.getByRole("gridcell")).toHaveCount(8);
      // Closing asks first; Keep editing returns to the unsaved edit.
      await editor.getByRole("button", { name: "Close", exact: true }).click();
      const prompt = page.getByRole("dialog", { name: "Discard unsaved changes?" });
      await expect(prompt).toBeVisible();
      await prompt.getByRole("button", { name: "Keep editing" }).click();
      await expect(prompt).toHaveCount(0);
      await expect(editor.getByRole("gridcell")).toHaveCount(8);
      // Undoing the edit makes the table match the saved one again, so Close leaves at once.
      await editor.getByRole("button", { name: "Undo" }).click();
      await expect(editor.getByRole("gridcell")).toHaveCount(11);
      await closeDialogWithoutSaving(editor, { unsaved: false });
      // Discard drops the edit.
      await inspector.getByRole("button", { name: "Edit table" }).click();
      await cell(1, 1).click();
      await editor.getByRole("button", { name: "Remove row" }).click();
      await closeDialogWithoutSaving(editor, { unsaved: true });
      await expect(inspector.getByTestId("grid-summary")).toHaveText("3 columns · 4 rows · 1 merged");
    });
  });
});
