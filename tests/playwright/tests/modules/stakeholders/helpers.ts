import { expect, type Page } from "@playwright/test";

import { deleteOrgOnCleanup, loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability } from "../../e2e-workflows/helpers";

/**
 * Shared setup for the Stakeholders & Personas specs (`persona-lifecycle.spec.ts`,
 * `stakeholder-lifecycle.spec.ts`): each test builds a disposable org + admin
 * (+ project) through the API, per this repo's "tests must not depend on shared
 * seeded state" rule, `Date.now()`-suffixes every name, and switches the
 * default-off module on from Org Admin's Modules group. The org admin is the
 * project's `PROJECT_MANAGER`, which composes with the module's project-scoped
 * owner roles, so no extra grant is needed to create, activate and edit.
 */
export const API_BASE_URL = "http://localhost:8000";

export async function setUpOrg(page: Page, label: string, withChildProject = false) {
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
  await setOrgModuleAvailability(page, "Stakeholders & Personas", "default_on");

  return { suffix, org, project, child, adminHeaders };
}

export const statusBadge = (page: Page, label: string) => page.locator("span.badge", { hasText: new RegExp(`^${label}$`) });
