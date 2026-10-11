import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a project admin gives their project link types of its own
 * (which nested projects inherit), hides the organisation's types they never
 * use, and keeps a type for the projects that still use it when they delete
 * it; an org admin can switch all of that off so every project sees one shared
 * set, and back on without losing anything.
 *
 * Covers: the panel lists the organisation's types and a parent's types with
 * where each comes from, and the project's own types in an editable row; adding
 * a type and hiding/showing an organisation type confirm with a Toast and change
 * what the picker endpoint offers; a parent never sees a child's type; the org
 * switch (Tier-1 confirmation) makes the project panel read-only and leaves
 * every row dormant rather than deleted; deleting a parent's type that a child
 * uses offers (ticked) to keep it for the child, which then owns a copy so its
 * links read as before.
 *
 * Each test builds its own organisation, so none depends on state left by
 * another test or an earlier run.
 */

const apiBaseUrl = "http://localhost:8000";

interface Project {
  id: string;
  name: string;
  componentId: string;
  categoryId: string;
}

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
}

/** A disposable org with an org admin. */
async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Project Link Types ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Link Types Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  return { orgId: org.id, adminEmail, headers: { Authorization: `Bearer ${token}` } };
}

async function createProject(
  request: APIRequestContext, world: World, name: string, parentId?: string,
): Promise<Project> {
  const project = await (
    await request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: world.headers,
      data: { organization_id: world.orgId, name, summary: "", can_be_parent: true, ...(parentId ? { parent_project_id: parentId } : {}) },
    })
  ).json();
  const component = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, {
      headers: world.headers, data: { name: "Software", prefix: "SW" },
    })
  ).json();
  const category = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, {
      headers: world.headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
    })
  ).json();
  return { id: project.id, name, componentId: component.id, categoryId: category.id };
}

async function createRequirement(request: APIRequestContext, world: World, project: Project, name: string): Promise<string> {
  const created = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements`, {
      headers: world.headers,
      data: { name, reasoning: "e2e", component_id: project.componentId, category_id: project.categoryId, keywords: [] },
    })
  ).json();
  return created.id;
}

async function createLocalType(request: APIRequestContext, world: World, project: Project, forward: string): Promise<string> {
  const resp = await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/link-types`, {
    headers: world.headers, data: { forward_name: forward, reverse_name: `${forward} reverse` },
  });
  expect(resp.status()).toBe(201);
  return (await resp.json()).id;
}

async function linkRequirements(
  request: APIRequestContext, world: World, project: Project, from: string, to: string, linkTypeId: string,
): Promise<void> {
  const resp = await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/artefacts/requirement/${from}/links`, {
    headers: world.headers,
    data: { link_type_id: linkTypeId, direction: "outgoing", other_type: "requirement", other_id: to },
  });
  expect(resp.status()).toBe(201);
}

/** The names of the link types the project's pickers offer from a requirement. */
async function offeredNames(request: APIRequestContext, world: World, project: Project, requirementId: string): Promise<string[]> {
  const rows = await (
    await request.get(`${apiBaseUrl}/api/v1/projects/${project.id}/artefacts/requirement/${requirementId}/link-types`, {
      headers: world.headers,
    })
  ).json();
  return rows.map((r: { forward_name: string }) => r.forward_name);
}

async function openProjectLinkTypes(page: Page, project: Project): Promise<void> {
  await page.goto(`/projects/${project.id}/admin/fieldsActions`);
  await ensureExpanded(page, "Link types");
  await expect(page.getByRole("region", { name: "Available to this project" })).toBeVisible();
}

test.describe("project admin: project-level link types", () => {
  test("add an own type, hide and show an organisation type, inherit a parent's, and never leak a child's", async ({ page }) => {
    const world = await createWorld(page.request, "scope");
    const parent = await createProject(page.request, world, `E2E Parent ${Date.now()}`);
    const child = await createProject(page.request, world, `E2E Child ${Date.now()}`, parent.id);
    const parentVerb = `E2E Parent verb ${Date.now()}`;
    await createLocalType(page.request, world, parent, parentVerb);
    const requirement = await createRequirement(page.request, world, child, "Child requirement");

    await loginAs(page, world.adminEmail, PASSWORD);
    await openProjectLinkTypes(page, child);
    const available = page.getByRole("region", { name: "Available to this project" });

    await test.step("organisation types and the parent's type say where they come from", async () => {
      await expect(available.getByText("Related to", { exact: true }).first()).toBeVisible();
      await expect(available.getByText("Organisation").first()).toBeVisible();
      await expect(available.getByText(parentVerb, { exact: true })).toBeVisible();
      await expect(available.getByText(`Inherited from ${parent.name}`)).toBeVisible();
      expect(await offeredNames(page.request, world, child, requirement)).toContain(parentVerb);
    });

    const ownName = `E2E Own verb ${Date.now()}`;
    await test.step("adding the project's own type confirms with a Toast and offers it", async () => {
      const own = page.getByRole("region", { name: "Link types of this project" });
      await own.getByPlaceholder("Forward name").fill(ownName);
      await own.getByPlaceholder("Reverse name").fill(`${ownName} reverse`);
      await own.getByRole("button", { name: "New link type" }).click();
      await expect(page.getByText("Link type added.")).toBeVisible();
      await expect(own.locator(`input.input[value="${ownName}"]:not([placeholder])`)).toBeVisible();
      expect(await offeredNames(page.request, world, child, requirement)).toContain(ownName);
    });

    await test.step("hiding an organisation type removes it from the picker; showing it brings it back", async () => {
      await available.getByRole("button", { name: "Hide Related to in this project" }).click();
      await expect(page.getByText("Link type visibility updated.").first()).toBeVisible();
      await expect(available.getByText("Hidden", { exact: true })).toBeVisible();
      expect(await offeredNames(page.request, world, child, requirement)).not.toContain("Related to");

      await available.getByRole("button", { name: "Show Related to in this project" }).click();
      await expect(available.getByText("Hidden", { exact: true })).toHaveCount(0);
      expect(await offeredNames(page.request, world, child, requirement)).toContain("Related to");
    });

    await test.step("the parent never sees the child's own type", async () => {
      await openProjectLinkTypes(page, parent);
      await expect(page.getByText(ownName)).toHaveCount(0);
      await expect(page.locator(`input.input[value="${ownName}"]`)).toHaveCount(0);
    });
  });

  test("the organisation can forbid project link types: the project view goes read-only and back without losing anything", async ({ page }) => {
    const world = await createWorld(page.request, "lock");
    const project = await createProject(page.request, world, `E2E Locked ${Date.now()}`);
    const ownName = `E2E Dormant verb ${Date.now()}`;
    await createLocalType(page.request, world, project, ownName);
    await loginAs(page, world.adminEmail, PASSWORD);

    const switchName = "Let projects add their own link types and hide the organisation's";
    await test.step("the switch is on by default and says how many project types it affects", async () => {
      await page.goto(`/orgs/${world.orgId}/admin`);
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Link types");
      await expect(page.getByRole("switch", { name: switchName })).toBeChecked();
      await expect(page.getByText("1 project-level link type(s) in 1 project(s) are affected.")).toBeVisible();
    });

    await test.step("switching it off asks first, saves, and confirms", async () => {
      await page.getByRole("switch", { name: switchName }).click();
      const dialog = page.getByRole("dialog", { name: "Switch off project link types?" });
      await expect(dialog.getByText(/Nothing is deleted/)).toBeVisible();
      await dialog.getByRole("button", { name: "Switch off" }).click();
      await expect(page.getByText("Project customisation updated.")).toBeVisible();
      await expect(page.getByRole("switch", { name: switchName })).not.toBeChecked();
    });

    await test.step("the project panel is read-only and shows only the organisation's types", async () => {
      await page.goto(`/projects/${project.id}/admin/fieldsActions`);
      await ensureExpanded(page, "Link types");
      await expect(page.getByText("Your organisation uses one shared set of link types, so they cannot be changed here.")).toBeVisible();
      await expect(page.getByRole("button", { name: /^Hide .* in this project$/ })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "New link type" })).toHaveCount(0);
      await expect(page.getByText(ownName)).toHaveCount(0);
      const refused = await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/link-types`, {
        headers: world.headers, data: { forward_name: "Refused", reverse_name: "Refused reverse" },
      });
      expect(refused.status()).toBe(403);
    });

    await test.step("switching it back on restores the project's own type", async () => {
      await page.goto(`/orgs/${world.orgId}/admin`);
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Link types");
      await page.getByRole("switch", { name: switchName }).click();
      await expect(page.getByText("Project customisation updated.")).toBeVisible();
      await page.goto(`/projects/${project.id}/admin/fieldsActions`);
      await ensureExpanded(page, "Link types");
      await expect(page.locator(`input.input[value="${ownName}"]:not([placeholder])`)).toBeVisible();
    });
  });

  test("deleting a parent's type that a child uses keeps it for the child", async ({ page }) => {
    const world = await createWorld(page.request, "keep");
    const parent = await createProject(page.request, world, `E2E Keep Parent ${Date.now()}`);
    const child = await createProject(page.request, world, `E2E Keep Child ${Date.now()}`, parent.id);
    const shared = `E2E Shared verb ${Date.now()}`;
    const typeId = await createLocalType(page.request, world, parent, shared);
    const [pa, pb] = [await createRequirement(page.request, world, parent, "PA"), await createRequirement(page.request, world, parent, "PB")];
    const [ca, cb] = [await createRequirement(page.request, world, child, "CA"), await createRequirement(page.request, world, child, "CB")];
    await linkRequirements(page.request, world, parent, pa, pb, typeId);
    await linkRequirements(page.request, world, child, ca, cb, typeId);

    await loginAs(page, world.adminEmail, PASSWORD);
    await openProjectLinkTypes(page, parent);
    const own = page.getByRole("region", { name: "Link types of this project" });
    await own.locator(`input.input[value="${shared}"]:not([placeholder])`).locator("xpath=ancestor::div[contains(@class,'stack')][1]")
      .getByTitle("Delete this link type").click();

    const dialog = page.getByRole("dialog", { name: `Delete “${shared}”?` });
    await test.step("the dialog offers, ticked, to keep the type for the child", async () => {
      await expect(dialog.getByRole("checkbox", { name: "Keep this link type in the 1 other project(s) that use it" })).toBeChecked();
    });

    await test.step("the parent's own link is deleted behind the type-the-name confirmation; the child keeps a copy", async () => {
      await dialog.getByRole("button", { name: "Delete the links too…" }).click();
      const confirm = page.getByRole("button", { name: "Delete links and link type" });
      await expect(confirm).toBeDisabled();
      await page.getByLabel(`Type "${shared}" to confirm`).fill(shared);
      await confirm.click();
      await expect(page.getByText(/Link type deleted: 1 link\(s\) deleted; kept in 1 project\(s\)\./)).toBeVisible();
      await expect(own.locator(`input.input[value="${shared}"]`)).toHaveCount(0);
    });

    await test.step("the child now owns the type and its link still reads the same", async () => {
      await openProjectLinkTypes(page, child);
      await expect(
        page.getByRole("region", { name: "Link types of this project" }).locator(`input.input[value="${shared}"]:not([placeholder])`),
      ).toBeVisible();
      const graph = await (
        await page.request.get(`${apiBaseUrl}/api/v1/projects/${child.id}/artefacts/requirement/${ca}/link-graph`, { headers: world.headers })
      ).json();
      expect(graph.edges.map((e: { phrase: string }) => e.phrase)).toEqual([shared]);
    });
  });
});
