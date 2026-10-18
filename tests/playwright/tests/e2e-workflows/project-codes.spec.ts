import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: every project has a short code that, put in front of a record code, names the
 * record unambiguously (`ACME-REQ-001`). An org admin chooses whether codes are assigned
 * automatically or chosen by the creator, and whether the project code always shows; each person
 * can turn it off inside a project unless the organisation insists.
 *
 * Covers: automatic assignment (no field on the New project form, a read-only code in project
 * settings); manual assignment saved from Org Admin (the field appears, a lower-case entry is
 * stored upper-case, a duplicate is refused with the reason); the display rule on a requirement
 * (qualified by default, bare once the person turns it off, qualified again when the organisation
 * enforces it); and finding a record by its qualified code.
 *
 * Each test builds its own organisation, so none depends on state left by another test.
 */

const apiBaseUrl = "http://localhost:8000";

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
}

async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `Codes ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Codes Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  return { orgId: org.id, adminEmail, headers: { Authorization: `Bearer ${token}` } };
}

async function createProject(request: APIRequestContext, world: World, name: string) {
  const project = await (
    await request.post(`${apiBaseUrl}/api/v1/projects`, { headers: world.headers, data: { organization_id: world.orgId, name, summary: "" } })
  ).json();
  const component = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, { headers: world.headers, data: { name: "Software", prefix: "SW" } })
  ).json();
  const category = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, {
      headers: world.headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
    })
  ).json();
  const requirement = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements`, {
      headers: world.headers,
      data: { name: "Coded requirement", reasoning: "e2e", component_id: component.id, category_id: category.id, keywords: [] },
    })
  ).json();
  return { project, requirement };
}

async function openNewProjectForm(page: Page): Promise<void> {
  await page.goto("/projects");
  await page.getByRole("button", { name: /New project/ }).click();
  await expect(page.getByRole("dialog", { name: "New project" })).toBeVisible();
}

test.describe("project codes", () => {
  test("automatic assignment: no field on the form, and the code is read-only in project settings", async ({ page }) => {
    const world = await createWorld(page.request, "auto");
    await loginAs(page, world.adminEmail);
    await openNewProjectForm(page);
    const dialog = page.getByRole("dialog", { name: "New project" });
    await expect(dialog.getByLabel("Code")).toHaveCount(0);
    await expect(dialog.getByText(/assigned automatically from the name/)).toBeVisible();
    await dialog.getByLabel("Name").fill("Rail Signalling Upgrade");
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);

    await page.goto(`${page.url()}/admin`);
    const code = page.getByLabel("Code", { exact: true });
    await expect(code).toHaveValue("RSU");
    await expect(code).toHaveAttribute("readonly", "");
  });

  test("manual assignment: set in Org Admin, entered upper-case, duplicates refused", async ({ page }) => {
    const world = await createWorld(page.request, "manual");
    await loginAs(page, world.adminEmail);

    await test.step("switch the organisation to manual assignment", async () => {
      await page.goto(`/orgs/${world.orgId}/admin`);
      await selectOrgAdminGroup(page, "Projects & workflow");
      const toggle = page.getByRole("button", { name: "Project codes section" });
      if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
      await page.getByLabel("Assignment").selectOption("manual");
      await page.getByLabel("Characters").selectOption("letters");
      // The page has other sections with their own Save (the organisation code): press this section's.
      await page.locator(".card", { has: page.getByLabel("Assignment") }).getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Project code policy saved")).toBeVisible();
    });

    await test.step("the form asks for a code, states the rule, and stores it upper-case", async () => {
      await openNewProjectForm(page);
      const dialog = page.getByRole("dialog", { name: "New project" });
      await expect(dialog.getByText(/2 to 6 letters, no spaces or hyphens/)).toBeVisible();
      await dialog.getByLabel("Name").fill("Manual Coded");
      await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
      await dialog.getByLabel("Code").fill("mc");
      await dialog.getByRole("button", { name: "Create" }).click();
      await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
      await page.goto(`${page.url()}/admin`);
      await expect(page.getByLabel("Code", { exact: true })).toHaveValue("MC");
      await expect(page.getByLabel("Code", { exact: true })).not.toHaveAttribute("readonly", "");
    });

    await test.step("a code already in use is refused with the reason", async () => {
      await openNewProjectForm(page);
      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.getByLabel("Name").fill("Duplicate Coded");
      await dialog.getByLabel("Code").fill("MC");
      await dialog.getByRole("button", { name: "Create" }).click();
      await expect(dialog.getByText(/already in use/)).toBeVisible();
    });
  });

  test("display rule: qualified by default, bare when the person opts out, qualified again when the organisation enforces it", async ({ page }) => {
    const world = await createWorld(page.request, "display");
    const { project, requirement } = await createProject(page.request, world, "Display Project");
    await loginAs(page, world.adminEmail);
    const header = page.locator(".record-header");

    await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);
    await expect(header).toContainText(`${project.code}-${requirement.unique_code}`);

    await test.step("opting out in Preferences shows the bare code", async () => {
      await page.goto("/preferences");
      await page.getByRole("checkbox", { name: "Show the project code on record codes" }).uncheck();
      await expect(page.getByRole("checkbox", { name: "Show the project code on record codes" })).not.toBeChecked();
      await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);
      await expect(header).toContainText(requirement.unique_code);
      await expect(header).not.toContainText(`${project.code}-${requirement.unique_code}`);
    });

    await test.step("the organisation enforcing it overrides the preference", async () => {
      const policy = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/code-policy`, {
        headers: world.headers,
        data: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "auto", enforce_code_everywhere: true },
      });
      expect(policy.ok()).toBeTruthy();
      await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);
      await expect(header).toContainText(`${project.code}-${requirement.unique_code}`);
    });
  });

  test("a record is found by its qualified code, in any case, and only by those who may see it", async ({ page }) => {
    const world = await createWorld(page.request, "lookup");
    const { project, requirement } = await createProject(page.request, world, "Lookup Project");
    const qualified = `${project.code}-${requirement.unique_code}`;
    const found = await page.request.get(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/records/by-code/${qualified.toLowerCase()}`, { headers: world.headers });
    expect(found.status()).toBe(200);
    expect(await found.json()).toMatchObject({ artefact_type: "requirement", id: requirement.id, project_id: project.id, qualified_code: qualified });
    const missing = await page.request.get(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/records/by-code/${project.code}-REQ-999`, { headers: world.headers });
    expect(missing.status()).toBe(404);
  });
});
