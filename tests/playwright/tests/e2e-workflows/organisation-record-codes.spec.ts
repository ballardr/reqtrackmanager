import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a record that an organisation owns and every project shares (a Persona, a
 * Strategy, a Stakeholder Group...) has a short code like any other record, and that code names
 * the record unambiguously by carrying the organisation's code (`ACME-PER-001`), because a bare
 * `PER-001` could just as well be a project's own.
 *
 * Covers: the organisation-owned code in a project's lists and in the organisation's own detail
 * page, next to a project-owned record with the same bare code; and an organisation admin changing
 * the organisation code (with its confirmation) and every code following it.
 *
 * Each test builds its own organisation, so none depends on state left by another test.
 */

const apiBaseUrl = "http://localhost:8000";

interface World {
  orgId: string;
  orgCode: string;
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
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `Org codes ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Org Codes Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  for (const key of ["context_strategy", "stakeholders"]) {
    const enabled = await request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/modules/${key}`, { headers, data: { enabled: true } });
    expect(enabled.ok(), `enable ${key}`).toBe(true);
  }
  return { orgId: org.id, orgCode: org.code, adminEmail, headers };
}

async function post(request: APIRequestContext, world: World, path: string, data: unknown) {
  const response = await request.post(`${apiBaseUrl}/api/v1${path}`, { headers: world.headers, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBe(201);
  return response.json();
}

const PERSONA = { description: "", role_title: "Technician", goals: "", needs: "", behaviours: "" };

async function createRecords(request: APIRequestContext, world: World) {
  const project = await post(request, world, "/projects", { organization_id: world.orgId, name: "Org Codes Project", summary: "" });
  const pid = project.id as string;
  const orgBase = `/orgs/${world.orgId}/modules`;
  const projectBase = `/projects/${pid}/modules`;
  const orgPersona = await post(request, world, `${orgBase}/stakeholders/personas`, { name: "Shared technician", ...PERSONA });
  const projectPersona = await post(request, world, `${projectBase}/stakeholders/personas`, { name: "Local operator", ...PERSONA });
  const orgStrategy = await post(request, world, `${orgBase}/context_strategy/strategies`, { title: "Group strategy", objective: "Win" });
  await post(request, world, `${orgBase}/stakeholders/stakeholder-groups`, { name: "Clients" });
  await post(request, world, `${projectBase}/stakeholders/stakeholder-groups`, { name: "Site contacts" });
  return { project, pid, orgPersona, projectPersona, orgStrategy };
}

/** The Organisation code section (Org Admin shows several sections, each with its own Save). */
function codeCard(page: Page) {
  return page.locator(".card", { has: page.getByRole("textbox", { name: "Code", exact: true }) });
}

test.describe("organisation-owned record codes", () => {
  test("an organisation-owned record carries the organisation code, next to a project record with the same bare code", async ({ page }) => {
    const world = await createWorld(page.request, "lists");
    const { pid, orgPersona, projectPersona, orgStrategy, project } = await createRecords(page.request, world);
    expect(orgPersona.unique_code).toBe("PER-001");
    expect(projectPersona.unique_code).toBe("PER-001");
    await loginAs(page, world.adminEmail);

    await test.step("a project's Persona list shows both, qualified by their own owner", async () => {
      await page.goto(`/projects/${pid}/modules/stakeholders/personas`);
      const table = page.getByRole("table", { name: "Personas" });
      await expect(table.getByText(`${world.orgCode}-PER-001`, { exact: true })).toBeVisible();
      await expect(table.getByText(`${project.code}-PER-001`, { exact: true })).toBeVisible();
    });

    await test.step("the organisation's own detail page carries the organisation code in its header", async () => {
      await page.goto(`/orgs/${world.orgId}/modules/stakeholders/personas/${orgPersona.id}`);
      const header = page.locator(".record-header");
      await expect(header.getByRole("heading")).toContainText("Shared technician");
      await expect(header.getByText(`${world.orgCode}-PER-001`, { exact: true })).toBeVisible();
    });

    await test.step("an organisation Strategy is numbered from the organisation's own counter", async () => {
      await page.goto(`/orgs/${world.orgId}/modules/context_strategy/strategies/${orgStrategy.id}`);
      await expect(page.locator(".record-header").getByText(`${world.orgCode}-STR-001`, { exact: true })).toBeVisible();
    });

    await test.step("the group tree shows each group's code", async () => {
      await page.goto(`/projects/${pid}/modules/stakeholders/groups`);
      const tree = page.getByRole("tree", { name: "Stakeholder groups" });
      await expect(tree.getByText(`${world.orgCode}-SGP-001`, { exact: true })).toBeVisible();
      await expect(tree.getByText(`${project.code}-SGP-001`, { exact: true })).toBeVisible();
    });
  });

  test("an organisation admin changes the organisation code, and codes follow it", async ({ page }) => {
    const world = await createWorld(page.request, "rename");
    const { pid, orgPersona } = await createRecords(page.request, world);
    await loginAs(page, world.adminEmail);

    await test.step("the change asks for confirmation, and cancelling changes nothing", async () => {
      await page.goto(`/orgs/${world.orgId}/admin`);
      await selectOrgAdminGroup(page, "Projects & workflow");
      const toggle = page.getByRole("button", { name: "Organisation code section" });
      if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
      const field = page.getByRole("textbox", { name: "Code", exact: true });
      await expect(field).toHaveValue(world.orgCode);
      await field.fill("zulu9");
      await codeCard(page).getByRole("button", { name: "Save", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Change the organisation code?" });
      await expect(dialog.getByText(new RegExp(`${world.orgCode} becomes ZULU9`))).toBeVisible();
      await dialog.getByRole("button", { name: "Cancel" }).click();
      const stillOld = await page.request.get(`${apiBaseUrl}/api/v1/orgs/${world.orgId}`, { headers: world.headers });
      expect((await stillOld.json()).code).toBe(world.orgCode);
    });

    await test.step("confirming saves it upper-case", async () => {
      await codeCard(page).getByRole("button", { name: "Save", exact: true }).click();
      await page.getByRole("dialog", { name: "Change the organisation code?" }).getByRole("button", { name: "Change code" }).click();
      await expect(page.getByText("Organisation code saved")).toBeVisible();
      const saved = await page.request.get(`${apiBaseUrl}/api/v1/orgs/${world.orgId}`, { headers: world.headers });
      expect((await saved.json()).code).toBe("ZULU9");
    });

    await test.step("the records show the new code, and the old qualified code no longer finds them", async () => {
      await page.goto(`/orgs/${world.orgId}/modules/stakeholders/personas/${orgPersona.id}`);
      await expect(page.locator(".record-header").getByText("ZULU9-PER-001", { exact: true })).toBeVisible();
      const byNew = await page.request.get(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/records/by-code/ZULU9-PER-001`, { headers: world.headers });
      expect(byNew.status()).toBe(200);
      expect(await byNew.json()).toMatchObject({ artefact_type: "persona", id: orgPersona.id, project_id: null });
      const byOld = await page.request.get(
        `${apiBaseUrl}/api/v1/orgs/${world.orgId}/records/by-code/${world.orgCode}-PER-001`, { headers: world.headers },
      );
      expect(byOld.status()).toBe(404);
      await page.goto(`/projects/${pid}/modules/stakeholders/personas`);
      await expect(page.getByRole("table", { name: "Personas" }).getByText("ZULU9-PER-001", { exact: true })).toBeVisible();
    });
  });
});
