import crypto from "node:crypto";

import { expect, type APIRequestContext, test } from "@playwright/test";

import { closeDesignerPreview, deleteOrgOnCleanup, installCleanupHook, loginAs, openDesignerPreview, PASSWORD, saveNewVersion, selectProjectAdminGroup, designerPreviewPanel } from "./helpers";

const API = "http://localhost:8000/api/v1";

const GRID_TEXT = `@layout document

@grid columns=4 headerrows=1
  @col 1 fill=#000000 color=#ffffff bold
  @col 3 fill=#000000 color=#ffffff bold
  | {colspan=4 align=center fill=#1f4e79 color=#ffffff bold} Document details |
  | Document | {{report_title}} | Version | {align=right} 1.2 |
  | {rowspan=2 valign=middle} Review | Reviewer | Date | |
  | Signed off | Status | Draft |
@end
`;

/**
 * Job to be done: put a document-details box or a sign-off sheet in a report, with merged cells and per-cell alignment and
 * colour, which the record tables cannot express.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout custom table", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  test("a custom table is written in the text view, previewed with its merges and colours, saved and read back", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-grid-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Grid ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Grid Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Grid project ${suffix}`, summary: "" } })).json();
    const name = `E2E grid layout ${suffix}`;
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();

    await test.step("the Add block menu offers Table (custom) beside Table (records)", async () => {
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.getByRole("button", { name: "Add block" }).click();
      await expect(page.getByRole("menuitem", { name: "Table (records)", exact: true })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Table (custom)", exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("the text view takes the grid and reports no problems", async () => {
      await page.getByRole("tab", { name: "Text" }).click();
      await page.getByRole("textbox", { name: "Layout text" }).fill(GRID_TEXT);
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("the toolbar inserts a starter grid", async () => {
      await page.getByRole("button", { name: "Insert block: Table (custom)" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@grid columns=2 borders=all/);
      await page.getByRole("textbox", { name: "Layout text" }).fill(GRID_TEXT);
    });

    await test.step("the preview draws the merged, shaded and aligned cells", async () => {
      await openDesignerPreview(page);
      const preview = designerPreviewPanel(page);
      await preview.getByRole("button", { name: "Run preview" }).click();
      const grid = preview.frameLocator('iframe[title="Report preview"]').locator("table.grid");
      await expect(grid.locator('td[colspan="4"]')).toContainText("Document details");
      await expect(grid.locator('td[rowspan="2"]')).toHaveText("Review");
      await expect(grid.locator("td.a-right")).toContainText("1.2");
      await expect(grid.locator("td").nth(1)).toHaveCSS("background-color", "rgb(0, 0, 0)");
      await closeDesignerPreview(page);
    });

    await test.step("saving and reloading keep it", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@grid columns=4 headerrows=1/);
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/\| \{colspan=4 align=center fill=#1f4e79 color=#ffffff bold\} Document details \|/);
    });
  });

  test("a grid whose merge runs past the table, or that sits in a table layout, is refused when saved", async ({ request }) => {
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-grid-refuse-${suffix}@example.com`;
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Grid refuse ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Grid Refuse", password: PASSWORD, role: "org_admin" },
    });
    const headers = await login(request, adminEmail, PASSWORD);
    const grid = (colspan: number) => ({
      type: "grid", columns: [{}, {}], rows: [{ cells: [{ text: "a", colspan }] }],
    });
    const tooWide = await request.post(`${API}/orgs/${org.id}/report-layouts`, {
      headers, data: { name: `Wide ${suffix}`, description: "", family: "document", tree: { schema_version: 1, family: "document", nodes: [grid(3)] } },
    });
    expect(tooWide.status()).toBe(422);
    expect(JSON.stringify(await tooWide.json())).toContain("runs past the edge");
    const inTable = await request.post(`${API}/orgs/${org.id}/report-layouts`, {
      headers, data: { name: `Table ${suffix}`, description: "", family: "table", tree: { schema_version: 1, family: "table", nodes: [grid(1)] } },
    });
    expect(inTable.status()).toBe(422);
    const fine = await request.post(`${API}/orgs/${org.id}/report-layouts`, {
      headers, data: { name: `Fine ${suffix}`, description: "", family: "document", tree: { schema_version: 1, family: "document", nodes: [grid(2)] } },
    });
    expect(fine.status()).toBe(201);
  });
});
