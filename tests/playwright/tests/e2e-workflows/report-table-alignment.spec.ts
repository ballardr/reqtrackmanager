import crypto from "node:crypto";

import { expect, type APIRequestContext, type Locator, type Page, test } from "@playwright/test";

import { chooseReport } from "./reportPicker";
import { deleteOrgOnCleanup, installCleanupHook, loginAs, openDesignerPreviewDialog, openSetupReport, PASSWORD, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: put two tables that hold the same columns one under the other in a report and have their columns line up
 * (the Review Package's overdue and not-yet-overdue Open Questions), however different their content, in the designer's preview and
 * in the run on screen.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report table alignment", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation and project with a long overdue question and a short open one, and a layout that lists the two tables. */
  async function setup(page: Page, request: APIRequestContext, settings: Record<string, unknown> = {}) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-table-alignment-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Table Alignment ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Alignment Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const enabled = await request.put(`${API}/orgs/${org.id}/modules/context_strategy`, { headers, data: { enabled: true } });
    expect(enabled.ok(), await enabled.text()).toBeTruthy();
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Alignment ${suffix}`, summary: "" } })).json();

    const questions = `${API}/projects/${project.id}/modules/context_strategy/open-questions`;
    const past = new Date(Date.now() - 400 * 86_400_000).toISOString().slice(0, 10);
    const bodies = [
      { question: `Which regulator signs off the cross-border data transfer for every region ${suffix}`, priority: "high", due_date: past },
      { question: `Pricing ${suffix}`, priority: "low" },
    ];
    for (const body of bodies) {
      const created = await request.post(questions, { headers, data: body });
      expect(created.ok(), await created.text()).toBeTruthy();
    }

    const layoutName = `E2E aligned ${suffix}`;
    const layout = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: {
        name: layoutName, description: "E2E layout", family: "document",
        tree: {
          schema_version: 1, family: "document", orientation: "portrait", ...settings,
          nodes: [
            { type: "widget", key: "context_strategy.open-question-register.overdue" },
            { type: "widget", key: "context_strategy.open-question-register.not_overdue" },
          ],
        },
      },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();

    return { project, layoutName };
  }

  /** The pixel width of each of the given table headings. */
  const headingWidths = (headings: Locator) =>
    headings.evaluateAll((cells) => cells.map((cell) => Math.round(cell.getBoundingClientRect().width)));

  test("the preview lines up the columns of two tables with the same headings", async ({ page, request }) => {
    const { project, layoutName } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, layoutName);
    await openDesignerPreviewDialog(page);
    const dialog = page.getByRole("dialog", { name: "Report preview" });
    await dialog.getByRole("button", { name: "Run preview" }).click();
    const frame = dialog.frameLocator('iframe[title="Report preview"]');

    await expect(frame.locator("table")).toHaveCount(2);
    const [first, second] = [await headingWidths(frame.locator("table").nth(0).locator("th")), await headingWidths(frame.locator("table").nth(1).locator("th"))];
    expect(first.length).toBeGreaterThan(5);
    expect(second).toEqual(first);
    expect(Math.max(...first)).toBeGreaterThan(Math.min(...first)); // sized by the content, not equal columns
  });

  test("the on-screen run lines them up too", async ({ page, request }) => {
    const { project, layoutName } = await setup(page, request);
    await page.goto(`/projects/${project.id}?reports=choose`);
    await chooseReport(page, layoutName);
    const tables = page.getByRole("table");
    await expect(tables).toHaveCount(2);
    const [first, second] = [await headingWidths(tables.nth(0).locator("th")), await headingWidths(tables.nth(1).locator("th"))];
    expect(first.length).toBeGreaterThan(5);
    expect(second).toEqual(first);
  });

  test("a layout that turns the alignment off sizes each table from its own content", async ({ page, request }) => {
    const { project, layoutName } = await setup(page, request, { align_tables: false });
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, layoutName);
    await openDesignerPreviewDialog(page);
    const dialog = page.getByRole("dialog", { name: "Report preview" });
    await dialog.getByRole("button", { name: "Run preview" }).click();
    const frame = dialog.frameLocator('iframe[title="Report preview"]');

    await expect(frame.locator("table")).toHaveCount(2);
    const [first, second] = [await headingWidths(frame.locator("table").nth(0).locator("th")), await headingWidths(frame.locator("table").nth(1).locator("th"))];
    expect(first.length).toBeGreaterThan(5);
    expect(second).not.toEqual(first);
  });
});
