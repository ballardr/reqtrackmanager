import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a requirement that concerns two components (an interface) is placed in both, with a code in each,
 * without being duplicated; a place can later be made a requirement of its own, and a project can stop new aliases.
 *
 * Covers: adding a further place on a requirement's page and reading its alias code, making the alias independent (the
 * code is typed to confirm, the new draft keeps the alias code), the project setting hiding the picker while an existing
 * alias stays listed, and the organisation default being followed and overridden.
 *
 * Each test builds its own organisation, so none depends on state left by another test.
 */

const apiBaseUrl = "http://localhost:8000";

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
  projectId: string;
  requirementId: string;
  hardware: { componentId: string; categoryId: string };
}

async function post(request: APIRequestContext, headers: World["headers"], path: string, data: unknown) {
  const response = await request.post(`${apiBaseUrl}/api/v1${path}`, { headers, data });
  expect(response.status(), await response.text()).toBeLessThan(300);
  return response.json();
}

/** An organisation with an administrator, a project with Software / Performance and Hardware / Interfaces, and one requirement in the first. */
async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await post(request, serverHeaders, "/orgs", { name: `Aliases ${label} ${suffix}` });
  deleteOrgOnCleanup({ id: org.id });
  await post(request, serverHeaders, `/orgs/${org.id}/users`, {
    email: adminEmail, display_name: "E2E Alias Admin", password: PASSWORD, role: "org_admin",
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const project = await post(request, headers, "/projects", { organization_id: org.id, name: "Alias Project", summary: "" });
  const software = await post(request, headers, `/projects/${project.id}/components`, { name: "Software", prefix: "SW" });
  const performance = await post(request, headers, `/projects/${project.id}/categories`, {
    name: "Performance", prefix: "PERF", component_id: software.id,
  });
  const hardwareComponent = await post(request, headers, `/projects/${project.id}/components`, { name: "Hardware", prefix: "HW" });
  const interfaces = await post(request, headers, `/projects/${project.id}/categories`, {
    name: "Interfaces", prefix: "IF", component_id: hardwareComponent.id,
  });
  const requirement = await post(request, headers, `/projects/${project.id}/requirements`, {
    name: "Bus timing", component_id: software.id, category_id: performance.id,
  });
  return {
    orgId: org.id, adminEmail, headers, projectId: project.id, requirementId: requirement.id,
    hardware: { componentId: hardwareComponent.id, categoryId: interfaces.id },
  };
}

async function addAlias(request: APIRequestContext, world: World): Promise<void> {
  const response = await request.put(`${apiBaseUrl}/api/v1/projects/${world.projectId}/requirements/${world.requirementId}/aliases`, {
    headers: world.headers, data: { places: [{ component_id: world.hardware.componentId, category_id: world.hardware.categoryId }] },
  });
  expect(response.status(), await response.text()).toBe(200);
}

async function openRequirement(page: Page, world: World, requirementId = world.requirementId): Promise<void> {
  await page.goto(`/projects/${world.projectId}/requirements/${requirementId}`);
  await expect(page.getByRole("heading", { name: "Components and codes" })).toBeVisible();
}

test.describe("requirement aliases", () => {
  test("a requirement is placed in a second component, then the alias is made independent", async ({ page }) => {
    test.setTimeout(120_000);
    const world = await createWorld(page.request, "place");
    await loginAs(page, world.adminEmail);
    await page.goto(`/projects/${world.projectId}/requirements/${world.requirementId}`);

    await test.step("adding the Hardware category gives the requirement a second code", async () => {
      await page.getByRole("button", { name: "Components and categories" }).click();
      await page.getByRole("checkbox", { name: "Hardware / Interfaces" }).click();
      await expect(page.getByLabel("Code HW-IF-002")).toBeVisible();
      await expect(page.getByLabel("Code SW-PERF-001")).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("the requirements list finds the requirement by the alias code", async () => {
      await page.goto(`/projects/${world.projectId}/requirements?search=HW-IF-002`);
      await expect(page.getByRole("link", { name: "Bus timing" })).toBeVisible();
    });

    await test.step("making the alias independent needs its code typed and creates a draft that keeps the code", async () => {
      await page.goto(`/projects/${world.projectId}/requirements/${world.requirementId}`);
      await page.getByRole("button", { name: "Actions for HW-IF-002" }).click();
      await page.getByRole("menuitem", { name: "Make independent" }).click();
      const confirm = page.getByRole("dialog").getByRole("button", { name: "Make independent" });
      await expect(confirm).toBeDisabled();
      await page.getByRole("textbox", { name: 'Type "HW-IF-002" to confirm' }).fill("HW-IF-002");
      await confirm.click();
      await expect(page.getByRole("dialog").getByText("HW-IF-002 is now a requirement of its own.")).toBeVisible();
      await page.getByRole("link", { name: "Open the new requirement" }).click();
      await page.waitForURL((url) => !url.pathname.endsWith(`/${world.requirementId}`) && url.pathname.includes("/requirements/"));
      await expect(page.getByText("HW-IF-002").first()).toBeVisible();
      const newId = page.url().split("/requirements/")[1].split(/[?#]/)[0];
      const made = await (await page.request.get(`${apiBaseUrl}/api/v1/projects/${world.projectId}/requirements/${newId}`, { headers: world.headers })).json();
      expect([made.status, made.unique_code]).toEqual(["draft", "HW-IF-002"]);
    });

    await test.step("the original no longer lists the alias", async () => {
      await page.goto(`/projects/${world.projectId}/requirements/${world.requirementId}`);
      await expect(page.getByLabel("Code HW-IF-002")).toHaveCount(0);
    });
  });

  test("disabling new aliases hides the picker but keeps an existing alias listed and resolving", async ({ page }) => {
    test.setTimeout(120_000);
    const world = await createWorld(page.request, "disable");
    await addAlias(page.request, world);
    await loginAs(page, world.adminEmail);

    await test.step("the project setting says where the value comes from, then is set to Disabled", async () => {
      await page.goto(`/projects/${world.projectId}/admin/structure`);
      await ensureExpanded(page, "Requirement aliases");
      await expect(page.getByText("Inherited from organisation").first()).toBeVisible();
      await expect(page.getByText("1 alias in this project")).toBeVisible();
      await page.getByRole("combobox", { name: /New requirement aliases/ }).selectOption("disabled");
      await expect(page.getByText("The setting was saved.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Use inherited value" })).toBeVisible();
    });

    await test.step("the requirement keeps listing its alias but offers no picker", async () => {
      await page.goto(`/projects/${world.projectId}/requirements/${world.requirementId}`);
      await expect(page.getByLabel("Code HW-IF-002")).toBeVisible();
      await expect(page.getByRole("button", { name: "Components and categories" })).toHaveCount(0);
    });

    await test.step("a new alias is refused by the server with the reason", async () => {
      // A category and its own component: the two lists are not ordered alike.
      const categories = await (await page.request.get(`${apiBaseUrl}/api/v1/projects/${world.projectId}/categories`, { headers: world.headers })).json();
      const own = categories.find((c: { id: string }) => c.id !== world.hardware.categoryId);
      const other = await post(page.request, world.headers, `/projects/${world.projectId}/requirements`, {
        name: "Other", component_id: own.component_id, category_id: own.id,
      });
      const refused = await page.request.put(`${apiBaseUrl}/api/v1/projects/${world.projectId}/requirements/${other.id}/aliases`, {
        headers: world.headers, data: { places: [{ component_id: world.hardware.componentId, category_id: world.hardware.categoryId }] },
      });
      expect(refused.status()).toBe(409);
      expect((await refused.json()).detail).toContain("disabled");
    });
  });

  test("the organisation default is followed by a project until it sets its own value", async ({ page }) => {
    test.setTimeout(90_000);
    const world = await createWorld(page.request, "org");
    await loginAs(page, world.adminEmail);

    await test.step("the organisation administrator disables new aliases for every project", async () => {
      await page.goto(`/orgs/${world.orgId}/admin`);
      await selectOrgAdminGroup(page, "Projects");
      await ensureExpanded(page, "Requirement aliases");
      await page.getByRole("combobox", { name: /New requirement aliases/ }).selectOption("disabled");
      await expect(page.getByText("The setting was saved.")).toBeVisible();
    });

    await test.step("the project follows it, then overrides it", async () => {
      await page.goto(`/projects/${world.projectId}/admin/structure`);
      await ensureExpanded(page, "Requirement aliases");
      await expect(page.getByRole("combobox", { name: /New requirement aliases/ })).toHaveValue("inherit");
      await page.getByRole("combobox", { name: /New requirement aliases/ }).selectOption("allowed");
      await expect(page.getByText("The setting was saved.")).toBeVisible();
      await addAlias(page.request, world);
      await openRequirement(page, world);
      await expect(page.getByLabel("Code HW-IF-002")).toBeVisible();
    });
  });
});
