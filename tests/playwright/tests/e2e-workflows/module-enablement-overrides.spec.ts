import { expect, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectProjectAdminGroup, setOrgModuleAvailability } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/** A module's row in the shared `ModuleSettingsList` (both admin pages). */
function moduleRow(page: Page, name: string) {
  return page.locator(".module-settings-row", { has: page.getByText(name, { exact: true }) });
}

/**
 * Job to be done: module/sub-component availability across org and project
 * (Decided by: User, 2026-10-04 — see `docs/decisions.md`):
 * - an org "Off" reaches every project immediately and can't be overridden;
 * - an org default only applies to projects that get the module afterwards
 *   — changing it never flips an existing project;
 * - a project may opt in to a module that is available but off by default.
 *
 * Uses Context & Strategy (registry default off, the only module with
 * sub-components) on a disposable org + projects created via the API, per
 * the repo's test-idempotency rule.
 */
/** Creates a disposable org with its own org admin (API), plus a
 * `createProject` helper, and logs that admin into the UI. */
async function setupOrg(page: Page, label: string) {
  const suffix = Date.now();
  const adminEmail = `e2e-module-${label}-admin-${suffix}@example.com`;
  const serverAdminToken = (
    await (
      await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      })
    ).json()
  ).access_token;
  const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: serverAdminHeaders, data: { name: `E2E Module ${label} Org ${suffix}` },
    })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverAdminHeaders,
    data: { email: adminEmail, display_name: "E2E Module Overrides Admin", password: PASSWORD, role: "org_admin" },
  });
  const adminHeaders = {
    Authorization: `Bearer ${(
      await (
        await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })
      ).json()
    ).access_token}`,
  };
  const createProject = async (name: string) =>
    (
      await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
        headers: adminHeaders, data: { organization_id: org.id, name: `${name} ${suffix}`, summary: "E2E seed project." },
      })
    ).json();
  await loginAs(page, adminEmail, PASSWORD);
  return { org, adminHeaders, createProject };
}

test.describe("module enablement overrides", () => {
  test("org Off is a hard floor, defaults only affect new projects, projects can opt in", async ({ page }) => {
    const { org, adminHeaders, createProject } = await setupOrg(page, "overrides");
    const existing = await createProject("E2E Module Overrides Existing");

    await test.step("module Off at org level: project toggle disabled with a hint, API widen rejected", async () => {
      const resp = await page.request.put(
        `${apiBaseUrl}/api/v1/projects/${existing.id}/modules/context_strategy/enablement`,
        { headers: adminHeaders, data: { enabled: true } },
      );
      expect(resp.status()).toBe(400);

      await page.goto(`/projects/${existing.id}/admin`);
      await selectProjectAdminGroup(page, "Modules");
      const row = moduleRow(page, "Context & Strategy");
      await expect(row.getByText("Turned off for your organisation — ask an organisation admin to turn it on.")).toBeVisible();
      await expect(row.getByRole("switch")).toBeDisabled();
    });

    await test.step("org turns it on for new projects: the existing project (nothing copied while Off) gets it", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Modules");
      await setOrgModuleAvailability(page, "Context & Strategy", "default_on");
      await expect(page.getByText("Context & Strategy: On for new projects")).toBeVisible();
      // Then switch the default off — must not affect the existing project.
      await setOrgModuleAvailability(page, "Context & Strategy", "opt_in");

      await page.goto(`/projects/${existing.id}/admin`);
      await selectProjectAdminGroup(page, "Modules");
      const existingRow = moduleRow(page, "Context & Strategy");
      await expect(existingRow.getByRole("switch")).toHaveAttribute("aria-checked", "true");
      await expect(existingRow.getByText("Organisation default for new projects: off")).toBeVisible();
    });

    await test.step("a project created after the change starts off and can opt in", async () => {
      const fresh = await createProject("E2E Module Overrides New");
      await page.goto(`/projects/${fresh.id}/admin`);
      await selectProjectAdminGroup(page, "Modules");
      const freshToggle = moduleRow(page, "Context & Strategy").getByRole("switch");
      await expect(freshToggle).toHaveAttribute("aria-checked", "false");
      await freshToggle.click();
      await expect(freshToggle).toHaveAttribute("aria-checked", "true");
      await expect(page.getByText("Context & Strategy enabled for this project")).toBeVisible();
    });
  });

  test("a sub-component turned Off at org level reaches existing projects", async ({ page }) => {
    const { org, createProject } = await setupOrg(page, "subfloor");
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Modules");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");
    const existing = await createProject("E2E Module Sub Floor Existing");

    await setOrgModuleAvailability(page, "Pain Points", "off", "Context & Strategy");

    await page.goto(`/projects/${existing.id}/admin`);
    await selectProjectAdminGroup(page, "Modules");
    await moduleRow(page, "Context & Strategy").getByRole("button", { name: "5 components · 4 on" }).click();
    const painPoints = page.getByRole("switch", { name: "Enable Pain Points (Context & Strategy) for this project" });
    await expect(painPoints).toHaveAttribute("aria-checked", "false");
    await expect(painPoints).toBeDisabled();
  });
});
