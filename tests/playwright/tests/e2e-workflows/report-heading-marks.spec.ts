import crypto from "node:crypto";

import { expect, type APIRequestContext, test } from "@playwright/test";

import {
  closeDesignerPreview, deleteOrgOnCleanup, designerPreviewPanel, installCleanupHook, loginAs, openDesignerPreview, openSetupReport, PASSWORD,
  selectProjectAdminGroup,
} from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: make a few words of a heading bold or italic without typing the mark characters. The heading's text field
 * has Bold and Italic buttons that wrap the selected words, and the preview prints them marked.
 *
 * The test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout heading mark buttons", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  test("Bold and Italic wrap the selected words of a heading and the preview prints them marked", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-block-marks-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Block marks ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Block Marks Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Block marks ${suffix}`, summary: "" } })).json();
    const name = `E2E block marks ${suffix}`;
    const created = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: { name, description: "", family: "document", tree: { schema_version: 1, family: "document", nodes: [] } },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, name);
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.getByRole("button", { name: "Add block" }).click();
    await page.getByRole("menuitem", { name: "Heading 1" }).click();
    const inspector = page.getByLabel("Block details");
    const words = inspector.getByRole("textbox", { name: "Heading", exact: true });

    await test.step("with nothing selected Bold marks the whole heading", async () => {
      await words.fill("Whole");
      await words.evaluate((el: HTMLInputElement) => { el.focus(); el.setSelectionRange(2, 2); });
      await inspector.getByRole("button", { name: "Heading: Bold" }).click();
      await expect(words).toHaveValue("**Whole**");
    });

    await test.step("Bold wraps the selected word and Italic the next", async () => {
      await words.fill("Draft copy");
      await words.evaluate((el: HTMLInputElement) => { el.focus(); el.setSelectionRange(0, 5); });
      await inspector.getByRole("button", { name: "Heading: Bold" }).click();
      await expect(words).toHaveValue("**Draft** copy");
      await words.evaluate((el: HTMLInputElement) => { el.focus(); el.setSelectionRange(10, 14); });
      await inspector.getByRole("button", { name: "Heading: Italic" }).click();
      await expect(words).toHaveValue("**Draft** *copy*");
    });

    await test.step("the preview prints the marked words", async () => {
      await openDesignerPreview(page);
      const preview = designerPreviewPanel(page);
      await preview.getByRole("button", { name: "Run preview" }).click();
      const frame = preview.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("h1 strong, h2 strong").filter({ hasText: "Draft" }).first()).toBeVisible();
      await expect(frame.locator("h1 em, h2 em").filter({ hasText: "copy" }).first()).toBeVisible();
      await closeDesignerPreview(page);
    });
  });
});
