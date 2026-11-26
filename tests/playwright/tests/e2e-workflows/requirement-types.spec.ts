import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import {
  addDefinition, deleteOrgOnCleanup, installCleanupHook, loginAs, openRequirementByName, PASSWORD, selectOrgAdminGroup,
  selectProjectAdminGroup,
} from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an organisation names the kinds a requirement can be (Business, Stakeholder and Project Requirement
 * by default), a project adds one of its own or hides one it does not use, and a requirement is given a type when it
 * is created or edited, so the list can be filtered by it.
 *
 * Covers: the default types and their ranks in Organisation Admin and Project Admin, adding a ranked type at both tiers, a type chosen in
 * the create dialog and shown in the list column, the Type filter, and retyping a draft requirement on its page.
 *
 * Each test builds its own organisation, so none depends on state left by another test.
 */

const apiBaseUrl = "http://localhost:8000";

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
  projectId: string;
  componentId: string;
  categoryId: string;
}

async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `Requirement types ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Requirement Types Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const project = await (
    await request.post(`${apiBaseUrl}/api/v1/projects`, { headers, data: { organization_id: org.id, name: "Types Project", summary: "" } })
  ).json();
  const base = `${apiBaseUrl}/api/v1/projects/${project.id}`;
  const component = await (await request.post(`${base}/components`, { headers, data: { name: "Software", prefix: "SW" } })).json();
  const category = await (
    await request.post(`${base}/categories`, { headers, data: { name: "Performance", prefix: "PERF", component_id: component.id } })
  ).json();
  return { orgId: org.id, adminEmail, headers, projectId: project.id, componentId: component.id, categoryId: category.id };
}

/** The current values of every text box with this accessible name (a list row keeps its value in the field). */
async function valuesOf(page: Page, name: string): Promise<string[]> {
  return page.getByRole("textbox", { name, exact: true }).evaluateAll((fields) => fields.map((f) => (f as HTMLInputElement).value));
}

async function openSection(page: Page, name: string): Promise<void> {
  const toggle = page.getByRole("button", { name: `${name} section` });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
}

test.describe("requirement types", () => {
  test("an organisation adds a type and a project lists the defaults with it", async ({ page }) => {
    test.setTimeout(90_000);
    const world = await createWorld(page.request, "org");
    await loginAs(page, world.adminEmail);

    await test.step("the organisation list starts with the three default types", async () => {
      await page.goto(`/orgs/${world.orgId}/admin`);
      await selectOrgAdminGroup(page, "Projects");
      await openSection(page, "Requirement types");
      await expect.poll(() => valuesOf(page, "Requirement type name")).toEqual([
        "Business Requirement", "Stakeholder Requirement", "Project Requirement",
      ]);
    });

    await test.step("a type added there is offered to the project", async () => {
      await addDefinition(page, "Add Requirement type", { Name: "Regulatory", Rank: "2" });
      await expect(page.getByText("Requirement type created.")).toBeVisible();
      const types = await (await page.request.get(`${apiBaseUrl}/api/v1/projects/${world.projectId}/requirement-types`, { headers: world.headers })).json();
      expect(types.map((t: { name: string }) => t.name)).toContain("Regulatory");
      expect(types.find((t: { name: string }) => t.name === "Regulatory").rank).toBe(2);
      expect(types.slice(0, 3).map((t: { rank: number }) => t.rank)).toEqual([1, 2, 3]);
    });
  });

  test("a project adds a type of its own and hides an organisation default", async ({ page }) => {
    test.setTimeout(90_000);
    const world = await createWorld(page.request, "project");
    await loginAs(page, world.adminEmail);
    await page.goto(`/projects/${world.projectId}/admin`);
    await selectProjectAdminGroup(page, "Fields & actions");
    await openSection(page, "Requirement types");

    await test.step("the project adds its own type", async () => {
      await addDefinition(page, "Add project-only Requirement type", { Name: "Interface" });
      await expect(page.getByText("Project Requirement type created.")).toBeVisible();
      await expect.poll(() => valuesOf(page, "Project Requirement type name")).toContain("Interface");
    });

    await test.step("hiding an organisation default removes it from this project only", async () => {
      await page.getByRole("button", { name: "Hide Requirement type in this project" }).first().click();
      await page.getByRole("dialog").getByRole("button", { name: /Hide/ }).click();
      await expect(page.getByText("Requirement type hidden in this project.")).toBeVisible();
      const hidden = await (await page.request.get(`${apiBaseUrl}/api/v1/projects/${world.projectId}/requirement-types/hidden`, { headers: world.headers })).json();
      expect(hidden).toHaveLength(1);
    });
  });

  test("a requirement is given a type, listed with it, filtered by it and retyped", async ({ page }) => {
    test.setTimeout(120_000);
    const world = await createWorld(page.request, "req");
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${world.projectId}/requirements`, {
      headers: world.headers,
      data: { name: "Untyped boot requirement", component_id: world.componentId, category_id: world.categoryId },
    });
    await loginAs(page, world.adminEmail);
    await page.goto(`/projects/${world.projectId}/requirements`);

    await test.step("the create dialog offers the project's types", async () => {
      await page.getByRole("button", { name: "New requirement" }).click();
      const dialog = page.getByRole("dialog", { name: "New requirement" });
      await dialog.getByPlaceholder("Name", { exact: true }).fill("Stakeholder boot requirement");
      await dialog.getByRole("combobox", { name: "Type" }).selectOption({ label: "Stakeholder Requirement" });
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(dialog).not.toBeVisible();
    });

    await test.step("the list shows the type and the Type filter narrows to it", async () => {
      await page.getByRole("button", { name: "List view" }).click();
      await expect(page.getByRole("row", { name: /Stakeholder boot requirement.*Stakeholder Requirement/ })).toBeVisible();
      await page.getByRole("combobox", { name: "Type" }).selectOption({ label: "Stakeholder Requirement" });
      await expect(page.getByText("Stakeholder boot requirement")).toBeVisible();
      await expect(page.getByText("Untyped boot requirement")).toHaveCount(0);
    });

    await test.step("a draft requirement is retyped on its page", async () => {
      await openRequirementByName(page, "Stakeholder boot requirement");
      await page.getByRole("combobox", { name: "Type" }).selectOption({ label: "Business Requirement" });
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText(/saved/i).first()).toBeVisible();
      await page.reload();
      await expect(page.getByRole("combobox", { name: "Type" })).toHaveValue(/.+/);
      await expect(page.getByRole("combobox", { name: "Type" }).locator("option:checked")).toHaveText("Business Requirement");
    });
  });
});
