import { expect, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectProjectAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/** A module's row in the shared `ModuleSettingsList`. */
function moduleRow(page: Page, name: string) {
  return page.locator(".module-settings-row", { has: page.getByText(name, { exact: true }) });
}

interface ProjectModule {
  module_key: string;
  name: string;
  effective_enabled: boolean;
  org_hard_enabled: boolean;
}

/**
 * Job to be done: the project-admin Modules tab (`/projects/:id/admin/modules`)
 * is always present, lists every registered module, and works for a project
 * administrator who is not an organisation admin (its endpoint uses a
 * different gate from the org page). The list is compared against
 * `GET /projects/{id}/modules` by name, so a newly registered module is
 * covered without editing this spec.
 *
 * Uses a disposable org, project and users created via the API, per the
 * repo's test-idempotency rule.
 */
async function setup(page: Page) {
  const suffix = Date.now();
  const serverAdminToken = (
    await (
      await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      })
    ).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverAdminToken}` };
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: serverHeaders, data: { name: `E2E Modules Tab Org ${suffix}` },
    })
  ).json();
  deleteOrgOnCleanup({ id: org.id });

  const createUser = async (label: string, role: "org_admin" | "member") => {
    const email = `e2e-modtab-${label}-${suffix}@example.com`;
    const created = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
        headers: serverHeaders, data: { email, display_name: `E2E ${label}`, password: PASSWORD, role },
      })
    ).json();
    return { email, userId: created.user_id as string };
  };
  const orgAdmin = await createUser("orgadmin", "org_admin");
  const projectAdmin = await createUser("projadmin", "member");

  const adminHeaders = {
    Authorization: `Bearer ${(
      await (
        await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: orgAdmin.email, password: PASSWORD } })
      ).json()
    ).access_token}`,
  };
  const project = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: adminHeaders, data: { organization_id: org.id, name: `E2E Modules Tab Project ${suffix}`, summary: "" },
    })
  ).json();
  await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/roles`, {
    headers: adminHeaders, data: { user_id: projectAdmin.userId, role: "project_administrator" },
  });
  const listModules = async (): Promise<ProjectModule[]> =>
    (await page.request.get(`${apiBaseUrl}/api/v1/projects/${project.id}/modules`, { headers: adminHeaders })).json();

  return { org, project, orgAdmin, projectAdmin, adminHeaders, listModules };
}

/** Asserts one row per registered module, by name. */
async function expectEveryModuleListed(page: Page, modules: ProjectModule[]) {
  expect(modules.length).toBeGreaterThan(0);
  await expect(page.locator(".module-settings-row")).toHaveCount(modules.length);
  for (const m of modules) await expect(moduleRow(page, m.name)).toBeVisible();
}

test.describe("project admin Modules tab", () => {
  test("an org admin reaches the tab from the menu and sees every registered module", async ({ page }) => {
    const { project, orgAdmin, listModules } = await setup(page);
    const modules = await listModules();
    await loginAs(page, orgAdmin.email, PASSWORD);

    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Project admin", exact: true }).click();
    await selectProjectAdminGroup(page, "Modules");

    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/admin/modules$`));
    await expectEveryModuleListed(page, modules);
  });

  test("a project administrator who is not an org admin sees the same list", async ({ page }) => {
    const { project, projectAdmin, listModules } = await setup(page);
    const modules = await listModules();
    await loginAs(page, projectAdmin.email, PASSWORD);

    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Project admin", exact: true }).click();
    await selectProjectAdminGroup(page, "Modules");

    await expectEveryModuleListed(page, modules);
  });

  test("direct navigation to /admin/modules lands on the Modules tab, not the default group", async ({ page }) => {
    const { project, projectAdmin, listModules } = await setup(page);
    const modules = await listModules();
    await loginAs(page, projectAdmin.email, PASSWORD);

    await page.goto(`/projects/${project.id}/admin/modules`);

    await expect(page.getByRole("link", { name: "Modules", exact: true })).toHaveAttribute("aria-current", "page");
    await expectEveryModuleListed(page, modules);
  });

  test("an org-disabled module is hidden; an available one toggles with a Toast", async ({ page }) => {
    const { org, project, projectAdmin, adminHeaders, listModules } = await setup(page);

    // Make the org-level state explicit rather than relying on defaults: switch the module on so
    // the project is offered it, then off again.
    const offKey = "context_strategy";
    const turnedOn = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/modules/${offKey}`, {
      headers: adminHeaders, data: { enabled: true },
    });
    expect(turnedOn.ok()).toBeTruthy();
    const off = (await listModules()).find((m) => m.module_key === offKey);
    expect(off, "Context & Strategy is registered").toBeTruthy();
    const turnedOff = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/modules/${offKey}`, {
      headers: adminHeaders, data: { enabled: false },
    });
    expect(turnedOff.ok()).toBeTruthy();

    const modules = await listModules();
    const toggleable = modules.find((m) => m.org_hard_enabled && m.effective_enabled && m.module_key !== offKey);
    expect(toggleable, "at least one module is on by default").toBeTruthy();

    await loginAs(page, projectAdmin.email, PASSWORD);
    await page.goto(`/projects/${project.id}/admin/modules`);

    await test.step("org-disabled: the module is not offered at all", async () => {
      await expect(moduleRow(page, toggleable!.name)).toBeVisible();
      await expect(moduleRow(page, off!.name)).toHaveCount(0);
    });

    await test.step("available module: enabled switch round-trips, each change confirmed by a Toast", async () => {
      const toggle = moduleRow(page, toggleable!.name).getByRole("switch");
      await expect(toggle).toBeEnabled();
      await expect(toggle).toHaveAttribute("aria-checked", "true");

      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-checked", "false");
      await expect(page.getByText(`${toggleable!.name} disabled for this project`)).toBeVisible();

      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-checked", "true");
      await expect(page.getByText(`${toggleable!.name} enabled for this project`)).toBeVisible();
    });
  });
});
