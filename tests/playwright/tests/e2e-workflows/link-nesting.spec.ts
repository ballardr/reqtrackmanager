import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an org admin decides, per link type, whether a record may be
 * linked to one in a parent or child project, and which end may sit higher; a
 * pain point at product level can be traced to the requirements below it but
 * not the other way round, and narrowing a type never deletes a link already made.
 *
 * Covers: access (a child-only member is told "not found" for the parent; detaching a project hides its cross-level links and
 * reattaching restores them); the "Across nested projects" select on a link type (label map, default
 * "Either end may be in a parent project"); the directional option is disabled,
 * with the reason, for a type with no direction; choosing it saves with a Toast and
 * the API then allows the upstream end in the parent and refuses it in the child;
 * narrowing a type that existing cross-project links rely on first says how many
 * will be flagged (Tier-1 confirmation), keeps them, and stops new ones.
 *
 * Each test builds its own organisation, so none depends on state left by
 * another test or an earlier run.
 */

const apiBaseUrl = "http://localhost:8000";

interface Project {
  id: string;
  componentId: string;
  categoryId: string;
}

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
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Link Nesting ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Nesting Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  return { orgId: org.id, adminEmail, headers: { Authorization: `Bearer ${token}` } };
}

async function createProject(request: APIRequestContext, world: World, name: string, parentId?: string): Promise<Project> {
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
  return { id: project.id, componentId: component.id, categoryId: category.id };
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

async function createOrgLinkType(request: APIRequestContext, world: World, forward: string, flow: string): Promise<string> {
  const resp = await request.post(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/link-types`, {
    headers: world.headers, data: { forward_name: forward, reverse_name: `${forward} reverse`, flow },
  });
  expect(resp.status()).toBe(201);
  return (await resp.json()).id;
}

/** Links `fromId` (in `fromProject`) to `toId` (in `toProject`) through the generic endpoint; returns the HTTP status. */
async function linkAcross(
  request: APIRequestContext, world: World, fromProject: Project, fromId: string, toProject: Project, toId: string, typeId: string,
): Promise<number> {
  const resp = await request.post(`${apiBaseUrl}/api/v1/projects/${fromProject.id}/artefacts/requirement/${fromId}/links`, {
    headers: world.headers,
    data: { link_type_id: typeId, direction: "outgoing", other_type: "requirement", other_id: toId, other_project_id: toProject.id },
  });
  return resp.status();
}

async function openOrgLinkTypes(page: Page, orgId: string): Promise<void> {
  await page.goto(`/orgs/${orgId}/admin`);
  await selectOrgAdminGroup(page, "Projects & workflow");
  await ensureExpanded(page, "Link types");
}

test.describe("org admin: link types across nested projects", () => {
  test("the directional option needs a direction, and once chosen only the parent may hold the upstream end", async ({ page }) => {
    const world = await createWorld(page.request, "scope");
    const parent = await createProject(page.request, world, `E2E Parent ${Date.now()}`);
    const child = await createProject(page.request, world, `E2E Child ${Date.now()}`, parent.id);
    const parentReq = await createRequirement(page.request, world, parent, "Parent requirement");
    const childReq = await createRequirement(page.request, world, child, "Child requirement");
    const directional = `E2E Derives ${Date.now()}`;
    const plain = `E2E Plain ${Date.now()}`;
    const directionalId = await createOrgLinkType(page.request, world, directional, "forward_is_upstream");
    await createOrgLinkType(page.request, world, plain, "none");

    await loginAs(page, world.adminEmail, PASSWORD);
    await openOrgLinkTypes(page, world.orgId);

    await test.step("a new type may span nested projects, and the directional option is unavailable without a direction", async () => {
      const plainSelect = page.getByRole("combobox", { name: `Across nested projects: ${plain}` });
      await expect(plainSelect).toHaveValue("ancestor_either_way");
      await expect(plainSelect.getByRole("option", { name: "Upstream end may be in a parent project" })).toBeDisabled();
      await expect(page.getByText(/Needs a direction: choose a direction/).first()).toBeVisible();
    });

    await test.step("choosing the directional option saves with a Toast", async () => {
      const select = page.getByRole("combobox", { name: `Across nested projects: ${directional}` });
      await select.selectOption({ label: "Upstream end may be in a parent project" });
      await expect(page.getByText("Link type nesting updated.")).toBeVisible();
      await expect(select).toHaveValue("upstream_in_ancestor");
    });

    await test.step("the upstream end may sit in the parent but not below it", async () => {
      // Forward is upstream: the target is upstream, so the parent's requirement must be the target.
      expect(await linkAcross(page.request, world, child, childReq, parent, parentReq, directionalId)).toBe(201);
      const refused = await page.request.post(`${apiBaseUrl}/api/v1/projects/${parent.id}/artefacts/requirement/${parentReq}/links`, {
        headers: world.headers,
        data: { link_type_id: directionalId, direction: "outgoing", other_type: "requirement", other_id: childReq, other_project_id: child.id },
      });
      expect(refused.status()).toBe(400);
      expect((await refused.json()).detail).toContain("upstream end");
    });
  });

  test("narrowing a type that cross-project links rely on asks first, keeps the links and stops new ones", async ({ page }) => {
    const world = await createWorld(page.request, "narrow");
    const parent = await createProject(page.request, world, `E2E Narrow Parent ${Date.now()}`);
    const child = await createProject(page.request, world, `E2E Narrow Child ${Date.now()}`, parent.id);
    const parentReq = await createRequirement(page.request, world, parent, "Parent requirement");
    const childReq = await createRequirement(page.request, world, child, "Child requirement");
    const extraChildReq = await createRequirement(page.request, world, child, "Second child requirement");
    const name = `E2E Related ${Date.now()}`;
    const typeId = await createOrgLinkType(page.request, world, name, "none");
    expect(await linkAcross(page.request, world, child, childReq, parent, parentReq, typeId)).toBe(201);

    await loginAs(page, world.adminEmail, PASSWORD);
    await openOrgLinkTypes(page, world.orgId);
    const select = page.getByRole("combobox", { name: `Across nested projects: ${name}` });

    await test.step("narrowing says how many links will be flagged, and cancelling changes nothing", async () => {
      await select.selectOption({ label: "Same project only" });
      const dialog = page.getByRole("dialog", { name: "Narrow where this link type can be used?" });
      await expect(dialog.getByText(/1 existing link\(s\)/)).toBeVisible();
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(select).toHaveValue("ancestor_either_way");
    });

    await test.step("confirming saves, keeps the link flagged, and refuses new cross-project links", async () => {
      await select.selectOption({ label: "Same project only" });
      await page.getByRole("dialog", { name: "Narrow where this link type can be used?" }).getByRole("button", { name: "Narrow" }).click();
      await expect(page.getByText("Link type nesting updated.")).toBeVisible();
      await expect(select).toHaveValue("same_project");

      const graph = await (
        await page.request.get(`${apiBaseUrl}/api/v1/projects/${child.id}/artefacts/requirement/${childReq}/link-graph`, { headers: world.headers })
      ).json();
      expect(graph.edges).toHaveLength(1);
      expect(graph.edges[0].nesting_permitted).toBe(false);
      expect(await linkAcross(page.request, world, child, extraChildReq, parent, parentReq, typeId)).toBe(400);
    });
  });

  test("a child-only member cannot link upwards, and detaching a project hides its links until it is reattached", async ({ page }) => {
    const world = await createWorld(page.request, "access");
    const parent = await createProject(page.request, world, `E2E Access Parent ${Date.now()}`);
    const child = await createProject(page.request, world, `E2E Access Child ${Date.now()}`, parent.id);
    const parentReq = await createRequirement(page.request, world, parent, "Parent requirement");
    const childReq = await createRequirement(page.request, world, child, "Child requirement");
    const typeId = await createOrgLinkType(page.request, world, `E2E Related ${Date.now()}`, "none");

    await test.step("a project manager of the child alone gets 'not found' for the parent, never 'forbidden'", async () => {
      const email = `e2e-access-pm-${Date.now()}@example.com`;
      const created = await (
        await page.request.post(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/users`, {
          headers: world.headers, data: { email, display_name: "E2E Child Manager", password: PASSWORD, role: "member" },
        })
      ).json();
      await page.request.post(`${apiBaseUrl}/api/v1/projects/${child.id}/roles`, {
        headers: world.headers, data: { user_id: created.user_id, role: "project_manager" },
      });
      const token = (await (await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email, password: PASSWORD } })).json()).access_token;
      const refused = await page.request.post(`${apiBaseUrl}/api/v1/projects/${child.id}/artefacts/requirement/${childReq}/links`, {
        headers: { Authorization: `Bearer ${token}` },
        data: { link_type_id: typeId, direction: "outgoing", other_type: "requirement", other_id: parentReq, other_project_id: parent.id },
      });
      expect(refused.status()).toBe(404);
    });

    await test.step("an admin links across; detaching the child hides the link and reattaching restores it", async () => {
      expect(await linkAcross(page.request, world, child, childReq, parent, parentReq, typeId)).toBe(201);
      const graphUrl = `${apiBaseUrl}/api/v1/projects/${child.id}/artefacts/requirement/${childReq}/link-graph`;
      const nodes = async (): Promise<number> => (await (await page.request.get(graphUrl, { headers: world.headers })).json()).nodes.length;
      expect(await nodes()).toBe(2);

      expect((await page.request.patch(`${apiBaseUrl}/api/v1/projects/${child.id}`, { headers: world.headers, data: { parent_project_id: null } })).status()).toBe(200);
      expect(await nodes()).toBe(1);

      expect((await page.request.patch(`${apiBaseUrl}/api/v1/projects/${child.id}`, { headers: world.headers, data: { parent_project_id: parent.id } })).status()).toBe(200);
      expect(await nodes()).toBe(2);
    });
  });
});
