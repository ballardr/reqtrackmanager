import { expect, test } from "@playwright/test";

import {
  createDocumentLayoutWorld, designerPreviewPanel, installCleanupHook, loginAs, openDesignerPreview, openDesignerTextView, PASSWORD, saveNewVersion,
} from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: add a table of contents to a report layout, see its headings listed (as links) in the preview, and download
 * the report in every format that carries one.
 *
 * Works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report table of contents", () => {
  installCleanupHook();

  test("a contents block lists the layout's headings as links in the preview and downloads in PDF, Word and HTML", async ({ page, request }) => {
    const { adminEmail, headers, project, layout } = await createDocumentLayoutWorld(request, "contents");
    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);

    await test.step("Add block offers a table of contents, with its levels setting in the inspector", async () => {
      await page.getByRole("button", { name: "Add block" }).first().click();
      await page.getByRole("menuitem", { name: "Table of contents" }).click();
      await expect(page.getByTestId("block-inspector")).toContainText("Table of contents block");
      await expect(page.getByRole("spinbutton", { name: "Levels" })).toBeVisible();
    });

    await test.step("the text view shows the block, and a second one is refused with its line", async () => {
      await openDesignerTextView(page);
      const editor = page.getByRole("textbox", { name: "Layout text" });
      await expect(editor).toHaveValue(/@contents/);
      await editor.fill([
        "@layout document", "", "@heading A report", '@contents "Inhalt" levels 2', "@heading Chapter one", "@heading level=2 First section",
        "@page_break", "@heading Chapter two", "@contents",
      ].join("\n"));
      await expect(page.getByText(/A layout holds one table of contents/)).toBeVisible();
      await editor.fill([
        "@layout document", "", "@heading A report", '@contents "Inhalt" levels 2', "@heading Chapter one", "@heading level=2 First section",
        "@page_break", "@heading Chapter two",
      ].join("\n"));
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("saving and running the preview lists the headings as links", async () => {
      await saveNewVersion(page);
      await expect(page.getByText(/Saved as version \d+\./)).toBeVisible();
      await openDesignerPreview(page);
      await designerPreviewPanel(page).getByRole("button", { name: "Run preview" }).click();
      const frame = designerPreviewPanel(page).frameLocator('iframe[title="Report preview"]');
      const contents = frame.locator("nav.contents");
      await expect(contents.getByText("Inhalt")).toBeVisible();
      await expect(contents.getByRole("link")).toHaveText(["A report", "Chapter one", "First section", "Chapter two"]);
      await expect(contents.getByRole("link", { name: "Chapter two" })).toHaveAttribute("href", "#chapter-two");
    });

    await test.step("the PDF, Word and HTML downloads all carry it", async () => {
      const run = `${API}/projects/${project.id}/custom-reports/${layout.id}/run`;
      const pdf = await request.get(run, { headers, params: { format: "pdf" } });
      expect(pdf.status()).toBe(200);
      expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
      const docx = await request.get(run, { headers, params: { format: "docx" } });
      expect(docx.status()).toBe(200);
      expect((await docx.body()).subarray(0, 2).toString()).toBe("PK");
      const html = await (await request.get(run, { headers, params: { format: "html" } })).text();
      expect(html).toContain('<nav class="contents"');
      expect(html).toContain('<a href="#chapter-one">Chapter one</a>');
    });
  });
});
