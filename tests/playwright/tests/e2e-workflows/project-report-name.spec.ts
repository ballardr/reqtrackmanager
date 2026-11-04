import crypto from "node:crypto";

import { expect, type APIRequestContext, test } from "@playwright/test";

import { chooseReport } from "./reportPicker";
import { clickAndAwaitSave, deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: give a project with a long name a short report name, so a report that writes the placeholder
 * prints the short form while the project keeps its full name everywhere else.
 *
 * The test works in its own disposable organisation (created and deleted through the API), so it passes alone, in
 * any order and repeated.
 */
test.describe("Project report name", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  test("a report prints the short name where it asks for it and the full name elsewhere", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-report-name-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Report Name ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Report Name Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);

    const fullName = `The Very Long Programme Name Delivery Office ${suffix}`;
    const shortName = `Delivery ${suffix.slice(-8)}`;
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: fullName, summary: "" } })).json();
    const layoutName = `E2E report name layout ${suffix}`;
    const created = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers,
      data: {
        name: layoutName, description: "E2E layout", family: "document",
        tree: {
          schema_version: 1, family: "document",
          nodes: [
            { type: "heading", text: "Short: {{project_report_name}}" },
            { type: "text", text: "Full: {{project_name}}" },
          ],
        },
      },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await test.step("before the name is set, the placeholder falls back to the project name", async () => {
      await page.goto(`/projects/${project.id}?reports=choose`);
      await chooseReport(page, layoutName);
      await expect(page.getByText(`Short: ${fullName}`)).toBeVisible();
    });

    await test.step("the project's settings take the report name, with its help", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await page.getByLabel("Project report name").fill(shortName);
      await page.getByRole("button", { name: "Help: Project report name" }).hover();
      await expect(page.getByRole("tooltip")).toContainText("Leave it blank to use the project name");
      await clickAndAwaitSave(page, page.getByRole("button", { name: "Save settings" }), `/projects/${project.id}`);
      await page.reload();
      await expect(page.getByLabel("Project report name")).toHaveValue(shortName);
    });

    await test.step("the report now prints the short name where it asks, and the full name where it does not", async () => {
      await page.goto(`/projects/${project.id}?reports=choose`);
      await chooseReport(page, layoutName);
      await expect(page.getByText(`Short: ${shortName}`)).toBeVisible();
      await expect(page.getByText(`Full: ${fullName}`)).toBeVisible();
    });

    await test.step("clearing the name returns to the project name", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await page.getByLabel("Project report name").fill("");
      await clickAndAwaitSave(page, page.getByRole("button", { name: "Save settings" }), `/projects/${project.id}`);
      await page.goto(`/projects/${project.id}?reports=choose`);
      await chooseReport(page, layoutName);
      await expect(page.getByText(`Short: ${fullName}`)).toBeVisible();
    });
  });
});
