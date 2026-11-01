import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { closeDesignerPreviewDialog, deleteOrgOnCleanup, installCleanupHook, loginAs, openDesignerPreviewDialog, PASSWORD, saveNewVersion, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: keep a sign-off table or a few lines at the foot of the page, however long the part above it is.
 *
 * The block is exact in PDF and floats at the foot of the page in Word and OpenDocument; the browser preview has no
 * pages, so it shows the contents in place.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout page bottom", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  test("an At page bottom block holds its contents, shows them in the preview and is written in the text view", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-pagebottom-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Page bottom ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Page Bottom Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Bottom project ${suffix}`, summary: "" } })).json();
    const name = `E2E bottom layout ${suffix}`;
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await page.getByRole("tab", { name: "Blocks" }).click();

    await test.step("the block is added from the menu and a text block goes inside it", async () => {
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "At page bottom", exact: true }).click();
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: /^Text/ }).click();
      await page.getByLabel("Block details").getByRole("textbox", { name: "Text" }).fill("Signed off by the project lead");
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("the preview shows the contents (it has no pages, so in place)", async () => {
      await openDesignerPreviewDialog(page);
      const preview = page.getByRole("dialog", { name: "Report preview" });
      await preview.getByRole("button", { name: "Run preview" }).click();
      await expect(preview.frameLocator('iframe[title="Report preview"]').getByText("Signed off by the project lead")).toBeVisible();
      await closeDesignerPreviewDialog(page);
    });

    await test.step("saving and reloading keep it, and the text view writes it with its contents", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@bottom\n\s+Signed off by the project lead\n@end/);
    });
  });

  test("a page break inside an At page bottom block is refused when saved", async ({ request }) => {
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-pagebottom-refuse-${suffix}@example.com`;
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Page bottom refuse ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Bottom Refuse", password: PASSWORD, role: "org_admin" },
    });
    const headers = await login(request, adminEmail, PASSWORD);
    const refused = await request.post(`${API}/orgs/${org.id}/report-layouts`, {
      headers, data: {
        name: `Bottom break ${suffix}`, description: "", family: "document",
        tree: { schema_version: 1, family: "document", nodes: [{ type: "bottom", children: [{ type: "page_break" }] }] },
      },
    });
    expect(refused.status()).toBe(422);
  });
});
