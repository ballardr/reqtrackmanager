import { expect, type Page, test } from "@playwright/test";

import {
  deleteOrgOnCleanup,
  installCleanupHook,
  loginAs,
  logout,
  PASSWORD,
  selectOrgAdminGroup,
  SERVER_ADMIN_LOGIN,
} from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";
const MODULE_NAME = "Decision Management";
const MODULE_KEY = "decisions";

/** A module's row in the shared `ModuleSettingsList`. */
function moduleRow(page: Page, name: string) {
  return page.locator(".module-settings-row", { has: page.getByText(name, { exact: true }) });
}

/**
 * Job to be done: a server administrator withdraws a module from one organisation (Server
 * Management → Modules) and nobody in that organisation is offered it any more: not its
 * organisation administrators, not its project administrators. The server administrator keeps
 * the full view and can grant it back.
 *
 * Uses a disposable organisation, project and users created via the API, per the repo's
 * test-idempotency rule. It never changes the server-wide defaults, which every other spec
 * shares; those are covered by the backend and Storybook tests.
 */
test("a server admin withdraws a module from an organisation and its admins stop seeing it", async ({ page }) => {
  const suffix = Date.now();
  const serverToken = (
    await (await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: SERVER_ADMIN_LOGIN })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: serverHeaders, data: { name: `E2E Module Availability Org ${suffix}` },
    })
  ).json();
  deleteOrgOnCleanup({ id: org.id });

  const createUser = async (label: string, role: "org_admin" | "member") => {
    const email = `e2e-availability-${label}-${suffix}@example.com`;
    const created = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
        headers: serverHeaders, data: { email, display_name: `E2E ${label}`, password: PASSWORD, role },
      })
    ).json();
    return { email, userId: created.user_id as string };
  };
  const orgAdmin = await createUser("orgadmin", "org_admin");
  const projectAdmin = await createUser("projadmin", "member");
  const orgAdminHeaders = {
    Authorization: `Bearer ${(
      await (
        await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: orgAdmin.email, password: PASSWORD } })
      ).json()
    ).access_token}`,
  };
  const project = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: orgAdminHeaders, data: { organization_id: org.id, name: `E2E Availability Project ${suffix}`, summary: "" },
    })
  ).json();
  await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/roles`, {
    headers: orgAdminHeaders, data: { user_id: projectAdmin.userId, role: "project_administrator" },
  });
  // Make the module explicitly available rather than relying on the deployment's defaults.
  const enabled = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/modules/${MODULE_KEY}`, {
    headers: orgAdminHeaders, data: { enabled: true, default_project_enabled: true },
  });
  expect(enabled.ok()).toBeTruthy();

  await test.step("before: the org admin and the project admin are offered the module", async () => {
    await loginAs(page, orgAdmin.email, PASSWORD);
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    await expect(moduleRow(page, MODULE_NAME)).toBeVisible();
    await logout(page);

    await loginAs(page, projectAdmin.email, PASSWORD);
    await page.goto(`/projects/${project.id}/admin/modules`);
    await expect(moduleRow(page, MODULE_NAME)).toBeVisible();
    await logout(page);
  });

  await test.step("the server admin withdraws it, with a Toast", async () => {
    await loginAs(page, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
    await page.goto("/server/management/modules");
    await page.getByRole("combobox", { name: /^Organi[sz]ation$/ }).selectOption({ label: org.name });
    const toggle = page.getByRole("switch", { name: `${MODULE_NAME} available` });
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await toggle.click();
    await expect(page.getByText(`${MODULE_NAME} withdrawn.`)).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(moduleRow(page, MODULE_NAME).getByText(/Not enabled/)).toBeVisible();
    await logout(page);
  });

  await test.step("after: neither admin is offered the module", async () => {
    await loginAs(page, orgAdmin.email, PASSWORD);
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    await expect(page.locator(".module-settings-list")).toBeVisible();
    await expect(moduleRow(page, MODULE_NAME)).toHaveCount(0);
    await logout(page);

    await loginAs(page, projectAdmin.email, PASSWORD);
    await page.goto(`/projects/${project.id}/admin/modules`);
    await expect(page.locator(".module-settings-list")).toBeVisible();
    await expect(moduleRow(page, MODULE_NAME)).toHaveCount(0);
  });
});
