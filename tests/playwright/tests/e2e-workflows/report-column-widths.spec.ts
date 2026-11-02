import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, openDesignerPreviewDialog, openSetupReport, PASSWORD, saveNewVersion, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: fix a table column's width so the columns stop changing with the content: set it in the designer, read it in
 * the text view, and see the starter layouts print the same columns for every component.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report column widths", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation and project with two components, each with a requirement whose content differs in length. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-column-widths-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Column Widths ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Column Widths Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Widths ${suffix}`, summary: "" } })).json();
    for (const [name, prefix, title] of [["Hardware", "HW", "Short"], ["Software", "SW", "A much longer requirement name that would normally widen its column"]]) {
      const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name, prefix } })).json();
      const category = await (await request.post(`${API}/projects/${project.id}/categories`, {
        headers, data: { name: `${name} functional`, prefix: `${prefix}F`, component_id: component.id },
      })).json();
      const created = await request.post(`${API}/projects/${project.id}/requirements`, {
        headers, data: { name: `${title} ${suffix}`, component_id: component.id, category_id: category.id },
      });
      expect(created.ok(), await created.text()).toBeTruthy();
    }
    const layoutName = `E2E widths ${suffix}`;
    const layout = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: {
        name: layoutName, description: "E2E layout", family: "document",
        tree: {
          schema_version: 1, family: "document", orientation: "portrait",
          nodes: [{ type: "table", source: { record_type: "requirement" }, columns: [{ field: "code" }, { field: "title" }, { field: "status" }] }],
        },
      },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();
    return { org, headers, project, layoutName };
  }

  async function runHtml(request: APIRequestContext, headers: Record<string, string>, projectId: string, layoutId: string) {
    const run = await request.get(`${API}/projects/${projectId}/custom-reports/${layoutId}/run`, { headers, params: { format: "html" } });
    expect(run.ok(), await run.text()).toBeTruthy();
    return run.text();
  }

  test("a width is set in the block's details, read in the text view and kept in the preview", async ({ page, request }) => {
    const { project, layoutName } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, layoutName);
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.locator(".blocklyText.rl-block-title", { hasText: /^Table.\(records\)$/ }).first().click();
    const inspector = page.getByLabel("Block details");

    await test.step("each column has a Width, automatic until set", async () => {
      // A column's width is in the popover behind its gear, one popover at a time.
      const setWidth = async (nth: number, width: string) => {
        await inspector.getByRole("list", { name: "Columns" }).getByRole("listitem").nth(nth).getByRole("button", { name: /^Settings for column/ }).click();
        const box = page.getByRole("dialog", { name: /^Settings for column/ }).getByRole("textbox", { name: "Width" });
        await expect(box).toHaveAttribute("placeholder", "auto");
        await box.fill(width);
        await page.keyboard.press("Escape");
      };
      await setWidth(0, "15%");
      await setWidth(1, "5 cm");
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("the preview fixes the columns", async () => {
      await openDesignerPreviewDialog(page);
      const dialog = page.getByRole("dialog", { name: "Report preview" });
      await dialog.getByRole("button", { name: "Run preview" }).click();
      const frame = dialog.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("table.fixed")).toHaveCount(1);
      await expect(frame.locator("table.fixed col")).toHaveCount(3);
      await dialog.getByRole("button", { name: "Close" }).click();
    });

    await test.step("saved, the text view writes the widths and reports a bad one at its line", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.getByRole("tab", { name: "Text" }).click();
      const editor = page.getByRole("textbox", { name: "Layout text" });
      const text = await editor.inputValue();
      expect(text).toContain("@column code width 15%");
      expect(text).toContain("@column title width 5 cm");
      await editor.fill("@layout document\n\n@table requirement\n  @column code width wide\n@end\n");
      await expect(page.getByText(/Line 4/)).toBeVisible();
    });
  });

  test("the Engineering Specification prints the same columns for every component", async ({ page, request }) => {
    const { org, headers, project } = await setup(page, request);
    const layouts = await (await request.get(`${API}/orgs/${org.id}/report-layouts`, { headers })).json();
    const specification = layouts.find((l: { name: string }) => l.name === "Engineering Specification");
    expect(specification).toBeTruthy();
    const html = await runHtml(request, headers, project.id, specification.id);
    // The requirement hierarchy prints one six-column table per component; they must line up.
    const groups = (html.match(/<colgroup>.*?<\/colgroup>/g) ?? []).filter((g) => (g.match(/<col[ >]/g) ?? []).length === 6);
    expect(groups.length).toBeGreaterThanOrEqual(2);
    expect(new Set(groups).size).toBe(1);
    expect(groups[0]).toContain("width:12%");
  });
});
