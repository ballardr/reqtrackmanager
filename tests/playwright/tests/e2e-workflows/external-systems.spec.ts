import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an organisation names the outside tools its records point into (Jira, a customer's register), gives
 * each a link template so a bare key opens its item, and a project adds a tool of its own or hides one it does not use.
 *
 * Covers: an organisation administrator adding a system with a link template in Organisation Admin (and a template that
 * is not an http(s) address with `{key}` being refused with the reason), the system being offered to a project, and the
 * project administrator adding a system of its own and hiding an organisation default in Project Admin.
 *
 * Each test builds its own organisation, so none depends on state left by another test.
 */

const apiBaseUrl = "http://localhost:8000";
const TEMPLATE = "https://linear.example/issue/{key}";

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
  projectId: string;
}

async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `External systems ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E External Systems Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const project = await (
    await request.post(`${apiBaseUrl}/api/v1/projects`, { headers, data: { organization_id: org.id, name: "Systems Project", summary: "" } })
  ).json();
  return { orgId: org.id, adminEmail, headers, projectId: project.id };
}

/** The current values of every text box with this accessible name (a list row keeps its value in the field). */
async function valuesOf(page: Page, name: string): Promise<string[]> {
  return page.getByRole("textbox", { name, exact: true }).evaluateAll((fields) => fields.map((f) => (f as HTMLInputElement).value));
}

async function openSection(page: Page, name: string): Promise<void> {
  const toggle = page.getByRole("button", { name: `${name} section` });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
}

test.describe("external systems", () => {
  test("an organisation adds a system with a link template and a project sees it", async ({ page }) => {
    test.setTimeout(90_000);
    const world = await createWorld(page.request, "org");
    await loginAs(page, world.adminEmail);

    await test.step("a template that is not an http(s) address with {key} is refused with the reason", async () => {
      await page.goto(`/orgs/${world.orgId}/admin`);
      await selectOrgAdminGroup(page, "Projects");
      await openSection(page, "External systems");
      await page.getByPlaceholder("External system type name").fill("Broken");
      await page.getByRole("textbox", { name: "Link template" }).last().fill("javascript:alert(1)");
      await page.getByRole("button", { name: "Add External system type" }).click();
      await expect(page.getByText(/link template|http or https|\{key\}/i).first()).toBeVisible();
    });

    await test.step("a valid template is saved with the system", async () => {
      await page.getByPlaceholder("External system type name").fill("Linear");
      await page.getByRole("textbox", { name: "Link template" }).last().fill(TEMPLATE);
      await page.getByRole("button", { name: "Add External system type" }).click();
      await expect(page.getByText("External system type created.")).toBeVisible();
      await expect.poll(() => valuesOf(page, "Link template")).toContain(TEMPLATE);
    });

    await test.step("the project offers it with its template", async () => {
      const systems = await (await page.request.get(`${apiBaseUrl}/api/v1/projects/${world.projectId}/external-systems`, { headers: world.headers })).json();
      const linear = systems.find((s: { name: string }) => s.name === "Linear");
      expect(linear?.url_template).toBe(TEMPLATE);
    });
  });

  test("a project adds a system of its own and hides an organisation default", async ({ page }) => {
    test.setTimeout(90_000);
    const world = await createWorld(page.request, "project");
    await loginAs(page, world.adminEmail);
    await page.goto(`/projects/${world.projectId}/admin`);
    await selectProjectAdminGroup(page, "Fields & actions");
    await openSection(page, "External systems");

    await test.step("the project adds its own system", async () => {
      await page.getByPlaceholder("Project External system type name").fill("Internal tracker");
      await page.getByRole("button", { name: "Add project-only External system type" }).click();
      await expect(page.getByText("Project External system type created.")).toBeVisible();
      await expect.poll(() => valuesOf(page, "Project External system type name")).toContain("Internal tracker");
    });

    await test.step("hiding an organisation default removes it here only, and restoring brings it back", async () => {
      await page.getByRole("button", { name: "Hide External system type in this project" }).first().click();
      await page.getByRole("dialog").getByRole("button", { name: /Hide/ }).click();
      await expect(page.getByText("External system type hidden in this project.")).toBeVisible();
      const hidden = await (await page.request.get(`${apiBaseUrl}/api/v1/projects/${world.projectId}/external-systems/hidden`, { headers: world.headers })).json();
      expect(hidden).toHaveLength(1);
      await page.getByRole("button", { name: /Add organisation defaults/ }).click();
      const dialog = page.getByRole("dialog", { name: "Add organisation defaults" });
      await dialog.getByRole("checkbox").first().check();
      await dialog.getByRole("button", { name: /^Add 1 default/ }).click();
      await expect(page.getByText("Organisation default added back.")).toBeVisible();
    });
  });
});
