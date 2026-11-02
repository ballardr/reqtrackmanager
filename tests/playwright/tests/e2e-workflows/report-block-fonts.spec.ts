import { expect, test } from "@playwright/test";

import { createDocumentLayoutWorld, installCleanupHook, loginAs, PASSWORD, saveNewVersion } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: give one text block and one heading their own font and size, put italics in a heading with `*word*`,
 * and have the saved layout's PDF and Word file print exactly that, while the rest of the document keeps its fonts.
 *
 * Works in its own disposable organisation, so it passes alone, in any order and repeated. It uses only the four standard fonts.
 */
test.describe("Report block fonts", () => {
  installCleanupHook();

  test("a text block set to Serif 12 and a heading with an italic word print in the PDF and Word file", async ({ page, request }) => {
    const { adminEmail, headers, project, layout } = await createDocumentLayoutWorld(request, "block-fonts");
    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("the text view writes a block's font and size and a heading's marks", async () => {
      await editor.fill(
        "@layout document\n\n@heading level=1 font=mono size=24 A *plan* for **review**\n\n"
        + "@text font=serif size=12\nSerif block text\n@end\n\nLayout body text\n",
      );
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("the block editor offers the font, size and colour of the heading, empty meaning the document's", async () => {
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.locator(".blocklyText.rl-summary", { hasText: "A *plan* for **review**" }).click();
      const inspector = page.getByLabel("Block details");
      await expect(inspector.getByRole("combobox", { name: "Font" })).toHaveValue("mono");
      await expect(inspector.getByRole("spinbutton", { name: "Size" })).toHaveValue("24");
      await inspector.getByRole("spinbutton", { name: "Size" }).fill("20");
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("saving keeps them, and the text view reads them back", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@heading level=1 font=mono size=20 A \*plan\* for \*\*review\*\*/);
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@text font=serif size=12/);
    });

    await test.step("the PDF uses the block fonts and the Word file writes them on those blocks only", async () => {
      const run = `${API}/projects/${project.id}/custom-reports/${layout.id}/run`;
      const pdf = await request.get(run, { headers, params: { format: "pdf" } });
      expect(pdf.status()).toBe(200);
      const bytes = (await pdf.body()).toString("latin1");
      expect(bytes).toContain("LiberationSerif"); // the text block
      expect(bytes).toContain("LiberationMono"); // the heading
      expect(bytes).toContain("Helvetica"); // the layout's own body text keeps the default
      const docx = await request.get(run, { headers, params: { format: "docx" } });
      expect(docx.status()).toBe(200);
      const html = await (await request.get(run, { headers, params: { format: "html" } })).text();
      expect(html).toContain("font-size: 20pt");
      expect(html).toContain("<em>plan</em>");
      expect(html).toContain("<strong>review</strong>");
      expect(html).not.toContain("*plan*");
    });
  });

  test("a size outside 6 to 72 points, or a bad font, is refused with the block's path", async ({ request }) => {
    const { headers, project } = await createDocumentLayoutWorld(request, "block-fonts");
    const tree = (node: unknown) => ({ schema_version: 1, family: "document", nodes: [node] });
    const check = async (node: unknown) =>
      (await request.post(`${API}/projects/${project.id}/report-layouts/validate`, { headers, data: { tree: tree(node) } })).json();
    const size = await check({ type: "text", text: "x", size: 5 });
    expect(size.ok).toBe(false);
    expect(size.errors[0]).toMatchObject({ path: "nodes[0].size" });
    const font = await check({ type: "heading", text: "x", font: "Times New Roman" });
    expect(font.errors[0]).toMatchObject({ path: "nodes[0].font" });
    const missing = await check({ type: "heading", text: "x", font: "x-no-such-font" });
    expect(missing.ok).toBe(true);
    expect(missing.warnings[0]).toContain("x-no-such-font");
  });
});
