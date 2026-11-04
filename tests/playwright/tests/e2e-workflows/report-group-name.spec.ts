import crypto from "node:crypto";

import { expect, type APIRequestContext, test } from "@playwright/test";

import {
  closeDesignerPreview, deleteOrgOnCleanup, designerPreviewPanel, installCleanupHook, loginAs, openDesignerPreview, openSetupReport, PASSWORD,
  selectProjectAdminGroup,
} from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: put the name of a group above its table. Inside a group block, the + Field button on a heading offers
 * "Group: <field>"; choosing it writes the group's value, and the preview prints one heading per category above that
 * category's table. Nested groups each have their own name, so a heading can name both.
 *
 * The test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout group name in a heading", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  test("a heading inside a group takes the group's name from + Field and the preview prints one heading per category", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-group-name-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Group name ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Group Name Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Group name ${suffix}`, summary: "" } })).json();

    const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Avionics", prefix: "AVI" } })).json();
    for (const [category, prefix] of [["Safety", "SAFE"], ["Performance", "PERF"]]) {
      const made = await (await request.post(`${API}/projects/${project.id}/categories`, {
        headers, data: { name: category, prefix, component_id: component.id },
      })).json();
      const req = await request.post(`${API}/projects/${project.id}/requirements`, {
        headers, data: { name: `${category} requirement ${suffix}`, component_id: component.id, category_id: made.id },
      });
      expect(req.ok(), await req.text()).toBeTruthy();
    }

    const name = `E2E group name ${suffix}`;
    const created = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: {
        name, description: "", family: "document",
        tree: {
          schema_version: 1, family: "document",
          nodes: [{
            type: "group", as: "category", by: "category", source: { record_type: "requirement" },
            children: [
              { type: "heading", level: 2, text: "Group " },
              { type: "table", source: { group: "category" }, columns: [{ field: "code" }, { field: "title" }] },
            ],
          }],
        },
      },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, name);
    await page.getByRole("tab", { name: "Blocks" }).click();

    await test.step("the heading's + Field button offers the group's name by its field", async () => {
      await page.locator(".blocklyText").filter({ hasText: /^Heading/ }).first().click();
      const inspector = page.getByLabel("Block details");
      const field = inspector.getByRole("button", { name: "Insert a field into Heading" });
      await expect(field).toContainText("Field");
      await field.click();
      const entry = page.getByRole("button", { name: "Insert {{category.value}}" });
      await expect(entry).toContainText("Group: Category");
      await expect(page.getByRole("button", { name: "Insert {{category.count}}" })).toContainText("Group: count");
      await entry.click();
      await expect(inspector.getByRole("textbox", { name: "Heading", exact: true })).toHaveValue("Group {{category.value}}");
    });

    await test.step("the preview prints a heading per category above its table", async () => {
      await openDesignerPreview(page);
      const preview = designerPreviewPanel(page);
      await preview.getByRole("button", { name: "Run preview" }).click();
      const frame = preview.frameLocator('iframe[title="Report preview"]');
      await expect(frame.getByRole("heading", { name: "Group Performance" })).toBeVisible();
      await expect(frame.getByRole("heading", { name: "Group Safety" })).toBeVisible();
      await expect(frame.getByText(`Safety requirement ${suffix}`)).toBeVisible();
      await closeDesignerPreview(page);
    });
  });
});
