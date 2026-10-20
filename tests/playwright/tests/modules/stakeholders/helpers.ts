import { expect, type Page } from "@playwright/test";

import { deleteOrgOnCleanup, loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability } from "../../e2e-workflows/helpers";

/**
 * Shared setup for the Stakeholders & Personas specs (`persona-lifecycle.spec.ts`,
 * `stakeholder-lifecycle.spec.ts`): each test builds a disposable org + admin
 * (+ project) through the API, per this repo's "tests must not depend on shared
 * seeded state" rule, `Date.now()`-suffixes every name, and switches the
 * default-off module (`moduleName`, Stakeholders & Personas unless another module's
 * spec reuses this helper) on from Org Admin's Modules group. The org admin is the
 * project's `PROJECT_MANAGER`, which composes with the module's project-scoped
 * owner roles, so no extra grant is needed to create, activate and edit.
 */
export const API_BASE_URL = "http://localhost:8000";

export async function setUpOrg(page: Page, label: string, withChildProject = false, moduleName = "Stakeholders & Personas") {
  const suffix = Date.now();
  const orgName = `E2E ${label} Org ${suffix}`;
  const adminEmail = `e2e-${label.toLowerCase()}-admin-${suffix}@example.com`;

  const serverAdminToken = (
    await (await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };

  const org = await (await page.request.post(`${API_BASE_URL}/api/v1/orgs`, { headers: serverAdminHeaders, data: { name: orgName } })).json();
  deleteOrgOnCleanup({ id: org.id });
  await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverAdminHeaders,
    data: { email: adminEmail, display_name: `E2E ${label} Admin`, password: PASSWORD, role: "org_admin" },
  });

  await loginAs(page, adminEmail, PASSWORD);
  const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const adminHeaders = { Authorization: `Bearer ${adminToken}` };

  const project = await (
    await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
      headers: adminHeaders,
      data: { organization_id: org.id, name: `E2E ${label} Project ${suffix}`, summary: "", can_be_parent: withChildProject },
    })
  ).json();
  const child = withChildProject
    ? await (
        await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
          headers: adminHeaders,
          data: { organization_id: org.id, name: `E2E ${label} Child ${suffix}`, summary: "", parent_project_id: project.id },
        })
      ).json()
    : null;

  await page.goto("/orgs");
  await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
  await selectOrgAdminGroup(page, "Modules");
  await setOrgModuleAvailability(page, moduleName, "default_on");

  return { suffix, org, project, child, adminHeaders };
}

export const statusBadge = (page: Page, label: string) => page.locator("span.badge", { hasText: new RegExp(`^${label}$`) });

export type PeopleKind = "persona" | "stakeholder" | "group";

/**
 * Opens the People page from the project's nav rail, narrowed to one kind through its `?kind=` URL (the
 * state the kind chips write), so a list assertion sees that kind's own columns and filters.
 */
export async function openPeople(page: Page, projectId: string, kind?: PeopleKind) {
  await page.goto(`/projects/${projectId}`);
  await page.getByRole("link", { name: "People", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/modules/stakeholders/people$`));
  if (kind) {
    await page.goto(`/projects/${projectId}/modules/stakeholders/people?kind=${kind}`);
  }
}

/** Chooses an item from the People page's New menu (`Persona`, `Stakeholder`, `Stakeholder Need`, ...). */
export async function openNew(page: Page, item: string) {
  await page.getByRole("button", { name: "New", exact: true }).click();
  await page.getByRole("menuitem", { name: item, exact: true }).click();
}

/** Opens the Needs tab (Stakeholder Needs list) beside People, from the project's nav rail. */
export async function openNeeds(page: Page, projectId: string) {
  await page.goto(`/projects/${projectId}`);
  await page.getByRole("link", { name: "People", exact: true }).click();
  await page.getByRole("tab", { name: "Needs" }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/modules/stakeholders/needs$`));
}
