import { expect, test } from "@playwright/test";

import { closeDesignerPreview, openDesignerPreview, createDocumentLayoutWorld, installCleanupHook, loginAs, PASSWORD, saveNewVersion, designerPreviewPanel } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: set a document's fonts once (body font and size, heading font, weight and colour) and have the
 * preview, the text view and the downloaded PDF and web page all use them.
 *
 * Works in its own disposable organisation, so it passes alone, in any order and repeated. It uses only the four standard
 * fonts, so it does not depend on the provided font the report fonts spec hides and shows.
 */
test.describe("Report document fonts", () => {
  installCleanupHook();

  test("body and heading fonts are set once and used by the preview, the text view, the PDF and the web page", async ({ page, request }) => {
    const { adminEmail, headers, project, layout } = await createDocumentLayoutWorld(request, "fonts");
    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);
    await page.getByRole("tab", { name: "Blocks" }).click();

    await test.step("the Layout block's Fonts group sets the body and heading fonts", async () => {
      await page.locator(".blocklyText", { hasText: /^Layout$/ }).click();
      const inspector = page.getByLabel("Block details");
      await inspector.getByRole("combobox", { name: "Body font" }).selectOption("serif");
      await inspector.getByRole("spinbutton", { name: "Body size (pt)" }).fill("12");
      await inspector.getByRole("combobox", { name: "Heading font" }).selectOption("mono");
      await inspector.getByRole("checkbox", { name: "Italic headings" }).check();
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("the preview prints them", async () => {
      await openDesignerPreview(page);
      const preview = designerPreviewPanel(page);
      await preview.getByRole("button", { name: "Run preview" }).click();
      const frame = preview.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("body")).toHaveCSS("font-family", /Times New Roman/);
      await expect(frame.locator("h2").first()).toHaveCSS("font-family", /Courier New/);
      await expect(frame.locator("h2").first()).toHaveCSS("font-style", "italic");
      await closeDesignerPreview(page);
    });

    await test.step("saving writes the styles, and the text view shows them", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      const text = page.getByRole("textbox", { name: "Layout text" });
      await expect(text).toHaveValue(/@style body font=serif size=12/);
      await expect(text).toHaveValue(/@style headings font=mono italic/);
    });

    await test.step("the downloaded PDF is set in the chosen fonts and the web page names them", async () => {
      const run = `${API}/projects/${project.id}/custom-reports/${layout.id}/run`;
      const pdf = await request.get(run, { headers, params: { format: "pdf" } });
      expect(pdf.status()).toBe(200);
      const bytes = (await pdf.body()).toString("latin1");
      expect(bytes).toContain("LiberationSerif");
      expect(bytes).toContain("LiberationMono-BoldItalic");
      const html = await (await request.get(run, { headers, params: { format: "html" } })).text();
      expect(html).toContain('font-family: "Times New Roman", serif; font-size: 12pt');
    });
  });

  test("a size outside 6 to 72 points is refused with its path, and a font the server lacks saves with a warning", async ({ request }) => {
    const { headers, project } = await createDocumentLayoutWorld(request, "fonts");
    const tree = (styles: unknown) => ({ schema_version: 1, family: "document", nodes: [], styles });
    const refused = await request.post(`${API}/projects/${project.id}/report-layouts/validate`, { headers, data: { tree: tree({ body: { size: 5 } }) } });
    const check = await refused.json();
    expect(check.ok).toBe(false);
    expect(check.errors[0]).toMatchObject({ path: "styles.body.size" });
    const missing = await request.post(`${API}/projects/${project.id}/report-layouts/validate`, { headers, data: { tree: tree({ body: { font: "x-no-such-font" } }) } });
    const warned = await missing.json();
    expect(warned.ok).toBe(true);
    expect(warned.warnings[0]).toContain("x-no-such-font");
  });
});
