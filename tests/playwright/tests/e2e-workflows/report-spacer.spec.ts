import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { closeDesignerPreview, deleteOrgOnCleanup, installCleanupHook, loginAs, openDesignerPreview, PASSWORD, saveNewVersion, selectProjectAdminGroup, designerPreviewPanel } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: leave an exact amount of vertical space in a report between two parts, instead of stacking empty
 * paragraphs that print differently in each format.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout spacer", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  test("a spacer is added from the menu, sized in millimetres, previewed, saved and written in the text view", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-spacer-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Spacer ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Spacer Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Spacer project ${suffix}`, summary: "" } })).json();
    const name = `E2E spacer layout ${suffix}`;
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await page.getByRole("tab", { name: "Blocks" }).click();

    await test.step("the Add block menu offers a Spacer that starts at 1 cm", async () => {
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Spacer", exact: true }).click();
      const inspector = page.getByLabel("Block details");
      await expect(inspector.getByRole("spinbutton", { name: "Height", exact: true })).toHaveValue("1");
      await expect(inspector.getByRole("combobox", { name: "Height unit" }).locator("option:checked")).toHaveText("Default (cm)");
    });

    await test.step("a height out of range is a problem, and 15 mm is accepted", async () => {
      const inspector = page.getByLabel("Block details");
      await inspector.getByRole("spinbutton", { name: "Height", exact: true }).fill("500");
      await expect(page.getByText(/The height must be a number from 0\.1 to 20 cm/)).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" }).first()).toBeDisabled();
      await inspector.getByRole("combobox", { name: "Height unit" }).selectOption({ label: "Millimetres (mm)" });
      await inspector.getByRole("spinbutton", { name: "Height", exact: true }).fill("15");
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("the preview prints a hidden block of that height", async () => {
      await openDesignerPreview(page);
      const preview = designerPreviewPanel(page);
      await preview.getByRole("button", { name: "Run preview" }).click();
      await expect(preview.frameLocator('iframe[title="Report preview"]').locator('div.spacer[aria-hidden="true"]')).toHaveAttribute("style", /height: 1\.5cm/);
      await closeDesignerPreview(page);
    });

    await test.step("saving and reloading keep it, and the text view writes it", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@spacer 15 mm/);
    });
  });

  test("a table layout refuses a spacer when it is saved", async ({ request }) => {
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-spacer-refuse-${suffix}@example.com`;
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Spacer table ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Spacer Refuse", password: PASSWORD, role: "org_admin" },
    });
    const headers = await login(request, adminEmail, PASSWORD);
    const refused = await request.post(`${API}/orgs/${org.id}/report-layouts`, {
      headers, data: {
        name: `Table spacer ${suffix}`, description: "", family: "table",
        tree: { schema_version: 1, family: "table", nodes: [{ type: "spacer", height: 1 }] },
      },
    });
    expect(refused.status()).toBe(422);
  });
});
