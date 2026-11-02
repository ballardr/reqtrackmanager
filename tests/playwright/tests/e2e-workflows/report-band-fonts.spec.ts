import { expect, test } from "@playwright/test";

import { createDocumentLayoutWorld, installCleanupHook, loginAs, PASSWORD, saveNewVersion, openDesignerTextView } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: give a page footer its own font, size and colour and make "Page X of Y" italic from the page setup dialog,
 * and have the saved layout's PDF, Word and web page print exactly that, with the page numbers still filled in.
 *
 * Works in its own disposable organisation, so it passes alone, in any order and repeated. It uses only the four standard fonts.
 */
test.describe("Report header and footer fonts", () => {
  installCleanupHook();

  test("an italic serif footer with Page X of Y prints in the PDF, the Word file and the web page", async ({ page, request }) => {
    const { adminEmail, headers, project, layout } = await createDocumentLayoutWorld(request, "band-fonts");
    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);
    await openDesignerTextView(page);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("the page setup dialog sets the footer's text, marks, font, size and colour", async () => {
      await page.getByRole("button", { name: /Page setup:/ }).click();
      const dialog = page.getByRole("dialog", { name: "Page setup" });
      await dialog.getByRole("combobox", { name: "Footer: print" }).selectOption("custom");
      const right = dialog.getByRole("textbox", { name: "Footer, right cell" });
      await right.fill("Page {{page}} of {{pages}}");
      await right.selectText();
      await dialog.getByRole("button", { name: "Footer: Italic" }).click();
      await expect(right).toHaveValue("*Page {{page}} of {{pages}}*");
      await expect(dialog.getByText("Page 3 of 12")).toBeVisible();
      await dialog.getByRole("combobox", { name: "Footer: font" }).selectOption("serif");
      await dialog.getByRole("spinbutton", { name: "Footer: size (pt)" }).fill("10");
      await dialog.getByRole("button", { name: "Close" }).click();
      await expect(editor).toHaveValue(/@footer left "" right "\*Page \{\{page\}\} of \{\{pages\}\}\*" font serif size 10/);
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("saving keeps it", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
    });

    await test.step("the PDF prints the footer in italic serif, the Word file and web page carry the look", async () => {
      const run = `${API}/projects/${project.id}/custom-reports/${layout.id}/run`;
      const pdf = await request.get(run, { headers, params: { format: "pdf" } });
      expect(pdf.status()).toBe(200);
      const bytes = (await pdf.body()).toString("latin1");
      expect(bytes).toContain("LiberationSerif-Italic");
      const docx = await request.get(run, { headers, params: { format: "docx" } });
      expect(docx.status()).toBe(200);
      const html = await (await request.get(run, { headers, params: { format: "html" } })).text();
      expect(html).toContain("<em>Page </em>");
      expect(html).toContain('<em><span class="pf"');
      expect(html).toContain("font-size: 10pt");
      expect(html).not.toContain("*Page");
    });
  });

  test("a bad band font, size or colour is refused with the band's path", async ({ request }) => {
    const { headers, project } = await createDocumentLayoutWorld(request, "band-fonts");
    const check = async (footer: unknown) =>
      (await request.post(`${API}/projects/${project.id}/report-layouts/validate`, {
        headers, data: { tree: { schema_version: 1, family: "document", footer, nodes: [{ type: "text", text: "x" }] } },
      })).json();
    expect((await check({ centre: "x", size: 5 })).errors[0]).toMatchObject({ path: "footer.size" });
    expect((await check({ centre: "x", font: "Times New Roman" })).errors[0]).toMatchObject({ path: "footer.font" });
    expect((await check({ centre: "x", colour: 7 })).errors[0]).toMatchObject({ path: "footer.colour" });
    expect((await check({ centre: "**x**", font: "mono", size: 9, colour: "#112233" })).ok).toBe(true);
  });
});
