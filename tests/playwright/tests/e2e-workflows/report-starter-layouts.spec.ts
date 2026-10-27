import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";
const STARTERS = ["Business Requirements Document", "Engineering Specification", "Review Package"];

/**
 * Job to be done: start a Business Requirements Document, an Engineering Specification or a Review Package from the
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
    await selectOrgAdminGroup(page, "Templates & reports");
    await ensureExpanded(page, "Report layouts");
  }

  test("a new organisation has the starters, a project runs one, and a deleted one is brought back", async ({ page, request }) => {
    const { org, headers, project, requirement } = await setup(page, request);

    await test.step("Org Admin lists the three starters", async () => {
      await openOrgLayouts(page, org.id);
      const table = page.getByRole("table", { name: "Report layouts" });
      for (const name of STARTERS) await expect(table.getByRole("link", { name })).toBeVisible();
    });

    await test.step("a project runs the Business Requirements Document on its own records", async () => {
      await page.goto(`/projects/${project.id}/reports`);
      const picker = page.getByLabel("Report", { exact: true });
      const option = picker.locator("option", { hasText: "Business Requirements Document" });
      await expect(option).toHaveCount(1); // waits for the catalogue to load
      await picker.selectOption({ label: (await option.textContent())! });
      await expect(page.getByRole("cell", { name: requirement })).toBeVisible();
      await expect(page.getByRole("heading", { name: /Pain Points/ })).toHaveCount(0); // its module is off in this project, so the section is left out
    });

    await test.step("a deleted starter comes back with Add starter layouts, and nothing else changes", async () => {
      const layouts: { id: string; name: string }[] = await (await request.get(`${API}/orgs/${org.id}/report-layouts`, { headers })).json();
      const doomed = layouts.find((layout) => layout.name === "Review Package")!;
      expect((await request.delete(`${API}/orgs/${org.id}/report-layouts/${doomed.id}`, { headers })).ok()).toBeTruthy();

      await openOrgLayouts(page, org.id);
      const table = page.getByRole("table", { name: "Report layouts" });
      await expect(table.getByRole("link", { name: "Review Package" })).toHaveCount(0);

      await page.getByRole("button", { name: "Add starter layouts" }).click();
      await expect(page.getByText("Added Review Package.")).toBeVisible();
      await expect(table.getByRole("link", { name: "Review Package" })).toBeVisible();

      await page.getByRole("button", { name: "Add starter layouts" }).click();
      await expect(page.getByText("Every starter layout is already here.")).toBeVisible();
    });
  });
});
