import crypto from "node:crypto";
import zlib from "node:zlib";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { chooseReport } from "./reportPicker";
import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, searchReportSetup, selectOrgAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";
const STARTERS = ["Business Requirements Document", "Engineering Specification", "Review Package", "Requirements by Component", "Project Workbook"];

/** The text of one file of a zip (an XLSX is one), read from its central directory. */
function zipEntry(zip: Buffer, name: string): string {
  let end = zip.length - 22;
  while (end >= 0 && zip.readUInt32LE(end) !== 0x06054b50) end -= 1;
  let at = zip.readUInt32LE(end + 16);
  for (let n = zip.readUInt16LE(end + 10); n > 0; n -= 1) {
    const method = zip.readUInt16LE(at + 10);
    const size = zip.readUInt32LE(at + 20);
    const nameLength = zip.readUInt16LE(at + 28);
    const extraLength = zip.readUInt16LE(at + 30);
    const commentLength = zip.readUInt16LE(at + 32);
    const local = zip.readUInt32LE(at + 42);
    if (zip.toString("utf8", at + 46, at + 46 + nameLength) === name) {
      const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
      const body = zip.subarray(start, start + size);
      return (method === 8 ? zlib.inflateRawSync(body) : body).toString("utf8");
    }
    at += 46 + nameLength + extraLength + commentLength;
  }
  throw new Error(`${name} is not in the zip`);
}

/**
 * Job to be done: start a Business Requirements Document, an Engineering Specification, a Review Package or Requirements by Component from the
 * ready-made layouts every organisation is created with, and bring one back after it was deleted.
 *
 * Each test works in its own disposable organisation (created and deleted through the API), so it passes alone, in
 * any order and repeated.
 */
test.describe("Report starter layouts", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with an admin and a project holding one requirement; the page is left logged in as the admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-starters-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Starters ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Starters Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Starters project ${suffix}`, summary: "" } })).json();
    const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Hardware", prefix: "HW" } })).json();
    const category = await (await request.post(`${API}/projects/${project.id}/categories`, {
      headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
    })).json();
    const requirement = `Brake pads ${suffix}`;
    const created = await request.post(`${API}/projects/${project.id}/requirements`, {
      headers, data: { name: requirement, component_id: component.id, category_id: category.id },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    return { org, headers, project, requirement };
  }

  async function openOrgLayouts(page: Page, orgId: string) {
    await page.goto(`/orgs/${orgId}/admin`);
    await selectOrgAdminGroup(page, "Reports");
    await ensureExpanded(page, "Report layouts");
  }

  test("a new organisation has the starters, a project runs one, and a deleted one is brought back", async ({ page, request }) => {
    const { org, headers, project, requirement } = await setup(page, request);

    await test.step("Org Admin lists the starters", async () => {
      await openOrgLayouts(page, org.id);
      // A row's name starts with the layout name and then its description, which may mention another starter.
      for (const name of STARTERS) {
        const grid = await searchReportSetup(page, name);
        await expect(grid.getByRole("button", { name: new RegExp(`^${name}`) })).toBeVisible();
      }
    });

    await test.step("a project runs the Business Requirements Document on its own records", async () => {
      await page.goto(`/projects/${project.id}?reports=choose`);
      await chooseReport(page, "Business Requirements Document");
      await expect(page.getByRole("cell", { name: requirement })).toBeVisible();
      await expect(page.getByRole("heading", { name: /Pain Points/ })).toHaveCount(0); // its module is off in this project, so the section is left out
    });

    await test.step("a project runs Requirements by Component, which groups requirements under their component", async () => {
      await page.goto(`/projects/${project.id}?reports=choose`);
      await chooseReport(page, "Requirements by Component");
      await expect(page.getByRole("cell", { name: requirement })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Hardware" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Functional" })).toBeVisible();
    });

    await test.step("the Project Workbook downloads as a spreadsheet with a sheet of core detail for the requirements only", async () => {
      const layouts: { id: string; name: string }[] = await (await request.get(`${API}/orgs/${org.id}/report-layouts`, { headers })).json();
      const workbook = layouts.find((layout) => layout.name === "Project Workbook")!;
      const run = await request.get(`${API}/projects/${project.id}/custom-reports/${workbook.id}/run`, { headers, params: { format: "xlsx" } });
      expect(run.ok(), await run.text()).toBeTruthy();
      const file = await run.body();
      const sheets = zipEntry(file, "xl/workbook.xml");
      expect(sheets).toContain('name="Contents"');
      expect(sheets).toContain('name="Requirement"');
      expect(sheets).not.toContain('name="Risk"'); // its module is off in this project, so its sheet is left out
      expect(zipEntry(file, "xl/worksheets/sheet2.xml")).toContain(requirement); // strings are written inline; sheet 2 is the Requirement sheet
    });

    await test.step("Add missing starters is not offered while every starter is present", async () => {
      await openOrgLayouts(page, org.id);
      await page.getByRole("button", { name: "New", exact: true }).click();
      await expect(page.getByRole("menuitem", { name: "New layout" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Add missing starters" })).toHaveCount(0);
      await page.keyboard.press("Escape");
    });

    await test.step("a deleted starter comes back with Add missing starters, and nothing else changes", async () => {
      const layouts: { id: string; name: string }[] = await (await request.get(`${API}/orgs/${org.id}/report-layouts`, { headers })).json();
      const doomed = layouts.find((layout) => layout.name === "Review Package")!;
      expect((await request.delete(`${API}/orgs/${org.id}/report-layouts/${doomed.id}`, { headers })).ok()).toBeTruthy();

      await openOrgLayouts(page, org.id);
      await page.getByRole("textbox", { name: "Search reports" }).fill("Review Package");
      await expect(page.getByText("Nothing matches these filters.")).toBeVisible();

      await page.getByRole("button", { name: "New", exact: true }).click();
      await page.getByRole("menuitem", { name: "Add missing starters" }).click();
      await expect(page.getByText("Added Review Package.")).toBeVisible();
      const grid = await searchReportSetup(page, "Review Package");
      await expect(grid.getByRole("button", { name: /^Review Package/ })).toBeVisible();

      await page.getByRole("button", { name: "New", exact: true }).click();
      await expect(page.getByRole("menuitem", { name: "Add missing starters" })).toHaveCount(0);
    });
  });
});
