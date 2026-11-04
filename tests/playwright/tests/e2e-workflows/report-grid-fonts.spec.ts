
import { expect, test } from "@playwright/test";

import { createDocumentLayoutWorld, ensureExpanded, installCleanupHook, loginAs, PASSWORD, saveNewVersion, openDesignerTextView } from "./helpers";
import { wordXml } from "./wordXml";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: set a custom table's code column in a monospaced font and the whole table a size smaller, from the table
 * editor, and have the saved layout's Word file, PDF and web page print exactly that, with the other column unchanged.
 *
 * Works in its own disposable organisation, so it passes alone, in any order and repeated. It uses only the four standard fonts.
 */
test.describe("Report custom table fonts", () => {
  installCleanupHook();

  test("a Mono column and an 8 pt table print in Word, PDF and HTML", async ({ page, request }) => {
    const { adminEmail, headers, project, layout } = await createDocumentLayoutWorld(request, "grid-fonts");
    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);
    await openDesignerTextView(page);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("the text view writes a grid's and a column's font and size", async () => {
      await editor.fill("@layout document\n\n@grid columns=2 size=8\n  @col 1 font=serif\n  | refcode | meaning words |\n@end\n");
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("the table editor offers a font and size for the selected column, empty meaning the table's", async () => {
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.locator(".blocklyText", { hasText: "Table (custom)" }).first().click();
      const inspector = page.getByLabel("Block details");
      // The table's size is set, so the closed Look group says so; the field is behind it.
      await expect(inspector.getByRole("button", { name: "Look section" })).toHaveAccessibleDescription("1 changed");
      await ensureExpanded(page, "Look");
      await expect(inspector.getByRole("spinbutton", { name: "Size" })).toHaveValue("8");
      await inspector.getByRole("button", { name: "Edit table" }).click();
      const dialog = page.getByRole("dialog", { name: "Edit custom table" });
      await dialog.getByLabel(/^Row 1, column 1(:|$)/).click();
      await expect(dialog.getByRole("combobox", { name: "Font of column 1" })).toHaveValue("serif");
      await dialog.getByRole("combobox", { name: "Font of column 1" }).selectOption("mono");
      await dialog.getByLabel(/^Row 1, column 2(:|$)/).click();
      await expect(dialog.getByRole("combobox", { name: "Font of column 2" })).toHaveValue("");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("saving keeps them, and the text view reads them back", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      const text = page.getByRole("textbox", { name: "Layout text" });
      await expect(text).toHaveValue(/@grid columns=2 size=8/);
      await expect(text).toHaveValue(/@col 1 font=mono/);
    });

    await test.step("Word, the PDF and the web page print the column in the monospaced font at 8 pt", async () => {
      const run = `${API}/projects/${project.id}/custom-reports/${layout.id}/run`;
      const docx = await request.get(run, { headers, params: { format: "docx" } });
      expect(docx.status()).toBe(200);
      const xml = wordXml(await docx.body());
      const mono = /<w:p>(?:(?!<\/w:p>).)*refcode.*?<\/w:p>/s.exec(xml)?.[0] ?? "";
      expect(mono).toContain('w:ascii="Courier New"');
      expect(mono).toContain('w:val="16"');
      const plain = /<w:p>(?:(?!<\/w:p>).)*meaning words.*?<\/w:p>/s.exec(xml)?.[0] ?? "";
      expect(plain).not.toContain("Courier New");
      const pdf = await request.get(run, { headers, params: { format: "pdf" } });
      expect(pdf.status()).toBe(200);
      expect((await pdf.body()).toString("latin1")).toContain("LiberationMono");
      const html = await (await request.get(run, { headers, params: { format: "html" } })).text();
      expect(html).toContain("font-size:8pt");
      expect(html).toContain("Courier New");
    });
  });

  test("a bad grid or column font or size, and a font on a row, are refused with their path", async ({ request }) => {
    const { headers, project } = await createDocumentLayoutWorld(request, "grid-fonts");
    const check = async (grid: Record<string, unknown>) =>
      (await request.post(`${API}/projects/${project.id}/report-layouts/validate`, {
        headers, data: { tree: { schema_version: 1, family: "document", nodes: [{ type: "grid", columns: [{}], rows: [{ cells: [{ text: "x" }] }], ...grid }] } },
      })).json();
    expect((await check({ size: 5 })).errors[0]).toMatchObject({ path: "nodes[0].size" });
    expect((await check({ columns: [{ font: "Times New Roman" }] })).errors[0]).toMatchObject({ path: "nodes[0].columns[0].font" });
    expect((await check({ rows: [{ font: "mono", cells: [{ text: "x" }] }] })).errors[0]).toMatchObject({ path: "nodes[0].rows[0].font" });
    expect((await check({ font: "serif", size: 9, columns: [{ font: "mono", size: 10.5 }] })).ok).toBe(true);
  });
});
