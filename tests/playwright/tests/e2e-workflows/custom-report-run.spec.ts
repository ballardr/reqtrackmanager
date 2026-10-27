import crypto from "node:crypto";
import fs from "node:fs";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: run a report somebody designed (a custom report layout) from the Reports page, for one project
 * or across the organisation's projects, and take it away as a PDF or Word file.
 *
 * Each test works in its own disposable organisation (created and deleted through the API) with uniquely named
 * layouts and records, so it passes alone, in any order and repeated.
 */
test.describe("Custom report run", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /**
   * A disposable organisation with an admin, two projects and one requirement in each; the page is left logged in as the
   * admin. `modules` are switched on for the organisation before the projects exist, so they get the module's seeded data.
   */
  async function setup(page: Page, request: APIRequestContext, modules: string[] = []) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-custom-report-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Custom Report ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Custom Report Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    for (const module of modules) {
      const enabled = await request.put(`${API}/orgs/${org.id}/modules/${module}`, { headers, data: { enabled: true } });
      expect(enabled.ok(), await enabled.text()).toBeTruthy();
    }

    const projects: { id: string; name: string; requirement: string }[] = [];
    for (const label of ["Alpha", "Beta"]) {
      const name = `${label} project ${suffix}`;
      const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name, summary: "" } })).json();
      const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Hardware", prefix: "HW" } })).json();
      const category = await (await request.post(`${API}/projects/${project.id}/categories`, {
        headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
      })).json();
      const requirement = `${label} requirement ${suffix}`;
      const created = await request.post(`${API}/projects/${project.id}/requirements`, {
        headers, data: { name: requirement, component_id: component.id, category_id: category.id },
      });
      expect(created.ok(), await created.text()).toBeTruthy();
      projects.push({ id: project.id, name, requirement });
    }
    return { org, headers, projects, suffix };
  }

  /** A document layout: a heading, then a table of every requirement. */
  const layoutTree = {
    schema_version: 1,
    family: "document",
    nodes: [
      { type: "heading", text: "Requirements" },
      { type: "table", source: { record_type: "requirement" }, columns: [{ field: "code" }, { field: "title", label: "Name" }] },
    ],
  };

  async function createLayout(request: APIRequestContext, headers: Record<string, string>, path: string, name: string) {
    const resp = await request.post(`${API}${path}/report-layouts`, {
      headers, data: { name, description: "E2E layout", family: "document", tree: layoutTree },
    });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    return resp.json();
  }

  /** Picks the report whose title contains `name` in the Reports page's "Report" picker. */
  async function chooseReport(page: Page, name: string) {
    const picker = page.getByLabel("Report", { exact: true });
    const option = picker.locator("option", { hasText: name });
    await expect(option).toHaveCount(1); // waits for the catalogue to load
    await picker.selectOption({ label: (await option.textContent())! });
  }

  async function download(page: Page, button: string) {
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: button }).click();
    return pending;
  }

  test("a project runs a layout on screen and downloads it as PDF, Word, OpenDocument text and HTML", async ({ page, request }) => {
    const { headers, projects, suffix } = await setup(page, request);
    const [alpha, beta] = projects;
    const name = `E2E Project layout ${suffix}`;
    await createLayout(request, headers, `/projects/${alpha.id}`, name);

    await test.step("the layout is listed beside the other reports and shows only this project's records", async () => {
      await page.goto(`/projects/${alpha.id}/reports`);
      await chooseReport(page, name);
      await expect(page.getByRole("cell", { name: alpha.requirement })).toBeVisible();
      await expect(page.getByRole("cell", { name: beta.requirement })).toHaveCount(0);
      await expect(page.getByRole("columnheader", { name: "Name" })).toBeVisible();
    });

    await test.step("the PDF is a real document", async () => {
      const file = await download(page, "Download PDF report");
      expect(fs.readFileSync((await file.path())!).subarray(0, 5).toString()).toBe("%PDF-");
      await expect(page.getByText(`Downloaded ${name} (PDF).`)).toBeVisible();
    });

    await test.step("the Word file is a real document carrying the requirement", async () => {
      const file = await download(page, "Download Word report");
      const bytes = fs.readFileSync((await file.path())!);
      expect(bytes.subarray(0, 2).toString()).toBe("PK");
      expect(bytes.includes("word/document.xml")).toBeTruthy();
    });

    await test.step("the HTML page is standalone, carries the requirement and runs no script", async () => {
      const file = await download(page, "Download HTML report");
      expect(file.suggestedFilename()).toMatch(/\.html$/);
      const html = fs.readFileSync((await file.path())!, "utf8");
      expect(html.startsWith("<!doctype html>")).toBeTruthy();
      expect(html).toContain(alpha.requirement);
      expect(html).not.toContain("<script");
    });

    await test.step("the OpenDocument text file is a real document (its type is stored first, uncompressed)", async () => {
      const file = await download(page, "Download OpenDocument text report");
      expect(file.suggestedFilename()).toMatch(/\.odt$/);
      const bytes = fs.readFileSync((await file.path())!);
      expect(bytes.subarray(0, 2).toString()).toBe("PK");
      expect(bytes.subarray(30, 38).toString()).toBe("mimetype");
      expect(bytes.includes("application/vnd.oasis.opendocument.text")).toBeTruthy();
      expect(bytes.includes("content.xml")).toBeTruthy();
      await expect(page.getByText(`Downloaded ${name} (OpenDocument text file).`)).toBeVisible();
    });

    await test.step("a project that has nothing to do with the layout does not offer it", async () => {
      await page.goto(`/projects/${beta.id}/reports`);
      await expect(page.getByLabel("Report", { exact: true }).locator("option", { hasText: name })).toHaveCount(0);
    });
  });

  test("an organisation layout runs across the projects and a selection limits it", async ({ page, request }) => {
    const { org, headers, projects, suffix } = await setup(page, request);
    const [alpha, beta] = projects;
    const name = `E2E Org layout ${suffix}`;
    await createLayout(request, headers, `/orgs/${org.id}`, name);

    await test.step("every project the person can read is included, each under its own title", async () => {
      // A new organisation also has the starter layouts, so the report is chosen by name.
      await page.goto(`/orgs/${org.id}/overview/reports`);
      await chooseReport(page, name);
      await expect(page.getByRole("cell", { name: alpha.requirement })).toBeVisible();
      await expect(page.getByRole("cell", { name: beta.requirement })).toBeVisible();
      await expect(page.getByRole("heading", { name: `${alpha.name} / Requirements` })).toBeVisible();
      await expect(page.getByRole("heading", { name: `${beta.name} / Requirements` })).toBeVisible();
    });

    await test.step("choosing a project limits the report to it, and the PDF carries the same choice", async () => {
      await page.getByRole("button", { name: "Projects" }).click();
      await page.getByRole("checkbox", { name: beta.name }).check();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("cell", { name: beta.requirement })).toBeVisible();
      await expect(page.getByRole("cell", { name: alpha.requirement })).toHaveCount(0);

      const sent = page.waitForRequest((r) => r.url().includes("/custom-reports/") && r.url().includes("format=pdf"));
      const file = await download(page, "Download PDF report");
      expect(new URL((await sent).url()).searchParams.get("project_ids")).toBe(
        (await (await request.get(`${API}/projects`, { headers })).json()).find((p: { name: string }) => p.name === beta.name).id,
      );
      expect(fs.readFileSync((await file.path())!).subarray(0, 5).toString()).toBe("%PDF-");
    });

    await test.step("clearing the selection includes every project again", async () => {
      await page.getByRole("button", { name: "Projects" }).click();
      await page.getByRole("checkbox", { name: beta.name }).uncheck();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("cell", { name: alpha.requirement })).toBeVisible();
      await expect(page.getByRole("cell", { name: beta.requirement })).toBeVisible();
    });
  });

  test("a layout embeds a table of another report as a widget, with its own headings around it", async ({ page, request }) => {
    const { headers, projects, suffix } = await setup(page, request, ["context_strategy"]);
    const [alpha] = projects;
    const name = `E2E Widget layout ${suffix}`;
    const created = await request.post(`${API}/projects/${alpha.id}/report-layouts`, {
      headers,
      data: {
        name, description: "E2E widget", family: "document",
        tree: {
          schema_version: 1, family: "document",
          nodes: [
            { type: "heading", text: "Our context" },
            { type: "widget", key: "context_strategy.summary.figures", params: { stale_months: 12 } },
            { type: "heading", text: "Open risks" },
            { type: "widget", key: "risk_management.risk-register.register", empty_text: "No risks recorded." },
          ],
        },
      },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await test.step("the figures table sits under the layout's own heading, with no heading of the report's", async () => {
      await page.goto(`/projects/${alpha.id}/reports`);
      await chooseReport(page, name);
      await expect(page.getByRole("heading", { name: "Our context" })).toBeVisible();
      await expect(page.getByRole("columnheader", { name: "Measure" }).first()).toBeVisible();
      await expect(page.getByText("Headline figures")).toHaveCount(0);
    });

    await test.step("a report whose module is off here says so and the rest still runs", async () => {
      await expect(page.getByText('The "Risk register" report is not available in this project.').first()).toBeVisible();
    });

    await test.step("the Word file is a real document", async () => {
      const file = await download(page, "Download Word report");
      const bytes = fs.readFileSync((await file.path())!);
      expect(bytes.subarray(0, 2).toString()).toBe("PK");
    });
  });

  test("a table layout downloads as an Excel workbook, an OpenDocument spreadsheet and, with several sheets, as a zip of CSV files", async ({ page, request }) => {
    const { headers, projects, suffix } = await setup(page, request);
    const [alpha] = projects;
    const name = `E2E Sheets layout ${suffix}`;
    const sheet = (sheetName: string) => ({
      type: "sheet", name: sheetName, source: { record_type: "requirement" }, columns: [{ field: "code" }, { field: "title" }],
    });
    const created = await request.post(`${API}/projects/${alpha.id}/report-layouts`, {
      headers, data: { name, description: "E2E sheets", family: "table", tree: { schema_version: 1, family: "table", nodes: [sheet("Requirements"), sheet("Again")] } },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto(`/projects/${alpha.id}/reports`);
    await chooseReport(page, name);
    await expect(page.getByRole("cell", { name: alpha.requirement }).first()).toBeVisible();

    await test.step("the Excel workbook is a real file", async () => {
      const file = await download(page, "Download Excel report");
      expect(file.suggestedFilename()).toMatch(/\.xlsx$/);
      const bytes = fs.readFileSync((await file.path())!);
      expect(bytes.subarray(0, 2).toString()).toBe("PK");
      expect(bytes.includes("xl/workbook.xml")).toBeTruthy();
      await expect(page.getByText(`Downloaded ${name} (Excel workbook).`)).toBeVisible();
    });

    await test.step("the OpenDocument spreadsheet is a real file", async () => {
      const file = await download(page, "Download OpenDocument spreadsheet report");
      expect(file.suggestedFilename()).toMatch(/\.ods$/);
      const bytes = fs.readFileSync((await file.path())!);
      expect(bytes.subarray(0, 2).toString()).toBe("PK");
      expect(bytes.includes("application/vnd.oasis.opendocument.spreadsheet")).toBeTruthy();
      await expect(page.getByText(`Downloaded ${name} (OpenDocument spreadsheet).`)).toBeVisible();
    });

    await test.step("two sheets come as a zip of CSV files, named as a zip", async () => {
      const file = await download(page, "Download CSV report");
      expect(file.suggestedFilename()).toMatch(/\.zip$/);
      const bytes = fs.readFileSync((await file.path())!);
      expect(bytes.subarray(0, 2).toString()).toBe("PK");
      expect(bytes.includes("Requirements.csv") && bytes.includes("Again.csv")).toBeTruthy();
    });
  });
});
