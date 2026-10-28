import crypto from "node:crypto";
import fs from "node:fs";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { chooseReport } from "./reportPicker";
import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: run one report layout for the categories I choose, from the Reports page (on screen and as a
 * file) and from the designer's preview, without making a copy of the layout per category.
 *
 * Each test works in its own disposable organisation (created and deleted through the API) with uniquely named
 * layouts and records, so it passes alone, in any order and repeated.
 */
test.describe("Custom report variables", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation and project with a requirement in each of three categories; the page is left logged in as the admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-report-variables-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Report Variables ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Variables Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Variables project ${suffix}`, summary: "" } })).json();
    const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Hardware", prefix: "HW" } })).json();
    const requirements: Record<string, string> = {};
    for (const category of ["Security", "Usability", "Billing"]) {
      const created = await (await request.post(`${API}/projects/${project.id}/categories`, {
        headers, data: { name: category, prefix: category.slice(0, 3).toUpperCase(), component_id: component.id },
      })).json();
      requirements[category] = `${category} requirement ${suffix}`;
      const resp = await request.post(`${API}/projects/${project.id}/requirements`, {
        headers, data: { name: requirements[category], component_id: component.id, category_id: created.id },
      });
      expect(resp.ok(), await resp.text()).toBeTruthy();
    }
    return { org, headers, project, requirements, suffix };
  }

  /** The layout in its text view: requirements whose category is one of the chosen ones, as a table. */
  const text = (extra = "") =>
    `@layout document\n@var categories enum list label "Categories" from requirement.category${extra}\n\n` +
    "@heading Requirements for {{var.categories}}\n\n" +
    "@table requirement where category in $categories\n  @column title \"Name\"\n@end\n";

  async function createLayout(request: APIRequestContext, headers: Record<string, string>, projectId: string, name: string, body: string) {
    const parsed = await request.post(`${API}/projects/${projectId}/report-layouts/text/parse`, { headers, data: { text: body } });
    const { tree, ok } = await parsed.json();
    expect(ok, JSON.stringify(await parsed.json())).toBeTruthy();
    const resp = await request.post(`${API}/projects/${projectId}/report-layouts`, {
      headers, data: { name, description: "E2E layout with a variable", family: "document", tree },
    });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    return resp.json();
  }

  async function choose(page: Page, ...categories: string[]) {
    await page.getByRole("button", { name: /Categories/ }).click();
    for (const category of categories) await page.getByRole("checkbox", { name: category }).click();
    await page.keyboard.press("Escape");
  }

  test("a report waits for its categories, shows only the chosen ones and downloads the same", async ({ page, request }) => {
    const { headers, project, requirements, suffix } = await setup(page, request);
    const name = `E2E Variables layout ${suffix}`;
    await createLayout(request, headers, project.id, name, text());

    await test.step("a required variable holds the report back, naming what is needed", async () => {
      await page.goto(`/projects/${project.id}/reports`);
      await chooseReport(page, name);
      await expect(page.getByText("Choose a value for Categories to run this report.")).toBeVisible();
      await expect(page.getByRole("cell", { name: requirements.Security })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Export", exact: true })).toHaveCount(0);
    });

    await test.step("the options are the project's own categories", async () => {
      await page.getByRole("button", { name: /Categories/ }).click();
      for (const category of ["Security", "Usability", "Billing"]) await expect(page.getByRole("checkbox", { name: category })).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("choosing two categories shows exactly their requirements and names them in the options order", async () => {
      await choose(page, "Security", "Billing");
      await expect(page.getByRole("cell", { name: requirements.Security })).toBeVisible();
      await expect(page.getByRole("cell", { name: requirements.Billing })).toBeVisible();
      await expect(page.getByRole("cell", { name: requirements.Usability })).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Requirements for Billing, Security" })).toBeVisible();
    });

    await test.step("the HTML file carries the same choice", async () => {
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const pending = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download HTML report" }).click();
      const html = fs.readFileSync((await (await pending).path())!, "utf8");
      expect(html).toContain(requirements.Security);
      expect(html).toContain(requirements.Billing);
      expect(html).not.toContain(requirements.Usability);
    });

    await test.step("another choice gives another report from the same layout", async () => {
      await choose(page, "Security", "Billing"); // unchecks both
      await choose(page, "Usability");
      await expect(page.getByRole("cell", { name: requirements.Usability })).toBeVisible();
      await expect(page.getByRole("cell", { name: requirements.Security })).toHaveCount(0);
    });
  });

  test("a default runs straight away, and the run records the values it used", async ({ page, request }) => {
    const { headers, project, requirements, suffix } = await setup(page, request);
    const name = `E2E Variables default ${suffix}`;
    await createLayout(request, headers, project.id, name, text(' default "Usability"'));

    await page.goto(`/projects/${project.id}/reports`);
    await chooseReport(page, name);

    await expect(page.getByRole("cell", { name: requirements.Usability })).toBeVisible();
    await expect(page.getByRole("cell", { name: requirements.Security })).toHaveCount(0);
    await expect(page.getByText("Choose a value for Categories")).toHaveCount(0);
  });

  test("the designer's preview asks for the draft's variables and previews with the chosen values", async ({ page, request }) => {
    const { headers, project, requirements, suffix } = await setup(page, request);
    const name = `E2E Variables designer ${suffix}`;
    const layout = await createLayout(request, headers, project.id, name, "@layout document\n\n@heading Draft\n");

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    await page.getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    expect(layout.id).toBeTruthy();

    await test.step("writing a variable puts its form in the preview and holds the preview back", async () => {
      await page.getByRole("textbox", { name: "Layout text" }).fill(text());
      await expect(page.getByText("The text is valid.")).toBeVisible();
      await expect(page.getByRole("button", { name: /Categories/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "Run preview" })).toBeDisabled();
      await expect(page.getByText("Choose a value for Categories to run this report.")).toBeVisible();
    });

    await test.step("choosing a category previews only its requirements", async () => {
      await choose(page, "Security");
      await page.getByRole("button", { name: "Run preview" }).click();
      const frame = page.frameLocator('iframe[title="Report preview"]');
      await expect(frame.getByText(requirements.Security)).toBeVisible();
      await expect(frame.getByText(requirements.Billing)).toHaveCount(0);
    });
  });
});
