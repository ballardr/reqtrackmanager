import { expect, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";
const MODULE = "Traceability & Governance";
const RULES = "Traceability rules";
const EXCEPTIONS = "Traceability exceptions";
const CROSS_PROJECT = "Cross-project traceability";
const INACTIVE = `Inactive until ${RULES} is on.`;

/** The module's row in the shared `ModuleSettingsList`, with its sub-components expanded. */
async function expandedRow(page: Page) {
  const row = page.locator(".module-settings-row", { has: page.getByText(MODULE, { exact: true }) });
  await row.getByRole("button", { name: /components? ·/ }).click();
  return row;
}

/**
 * Job to be done: a sub-component that requires another (Traceability exceptions and Cross-project traceability
 * require Traceability rules) has no effect while the other is off, says so under its own row in organisation and
 * project administration, and keeps its own switch.
 *
 * Uses a disposable organisation, project and administrator created through the API.
 */
test.describe("sub-component requirements", () => {
  test("a dependent says what it waits on in organisation and project administration", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-requires-admin-${suffix}@example.com`;
    const serverAdminToken = (
      await (await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
    ).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverAdminHeaders, data: { name: `E2E Requires Org ${suffix}` } })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E Requires Admin", password: PASSWORD, role: "org_admin" },
    });
    const adminHeaders = {
      Authorization: `Bearer ${(
        await (await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
      ).access_token}`,
    };
    await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/modules/traceability`, {
      headers: adminHeaders, data: { enabled: true, default_project_enabled: true },
    });
    const project = await (
      await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
        headers: adminHeaders, data: { organization_id: org.id, name: `E2E Requires Project ${suffix}`, summary: "" },
      })
    ).json();

    await loginAs(page, adminEmail, PASSWORD);

    // Organisation administration: switching the requirement off marks both dependents, and their own selects keep their value.
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    const orgRow = await expandedRow(page);
    await expect(orgRow.getByText(/Inactive until/)).toHaveCount(0);
    const rules = page.getByRole("combobox", { name: `${RULES} (${MODULE}) availability`, exact: true });
    await rules.selectOption("off");
    await expect(rules).toHaveValue("off");
    await expect(orgRow.getByText(INACTIVE)).toHaveCount(2);
    await expect(page.getByRole("combobox", { name: `${EXCEPTIONS} (${MODULE}) availability`, exact: true })).toHaveValue("default_on");

    // Project administration lists the dependents with the same explanation, though the organisation hides the requirement itself.
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Modules");
    const projectRow = await expandedRow(page);
    await expect(projectRow.getByText(INACTIVE)).toHaveCount(2);
    await expect(page.getByRole("switch", { name: `Enable ${RULES} (${MODULE}) for this project` })).toHaveCount(0);
    await expect(page.getByRole("switch", { name: `Enable ${EXCEPTIONS} (${MODULE}) for this project` })).toBeVisible();

    // Switching the requirement back on in the organisation clears the explanation for the project.
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    await expandedRow(page);
    await page.getByRole("combobox", { name: `${RULES} (${MODULE}) availability`, exact: true }).selectOption("default_on");
    await expect(page.getByText(/Inactive until/)).toHaveCount(0);

    // A project can switch the requirement off for itself; the dependents then say so there only.
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Modules");
    const row = await expandedRow(page);
    await expect(row.getByText(/Inactive until/)).toHaveCount(0);
    const rulesSwitch = page.getByRole("switch", { name: `Enable ${RULES} (${MODULE}) for this project` });
    await rulesSwitch.click();
    await expect(rulesSwitch).not.toBeChecked();
    await expect(row.getByText(INACTIVE)).toHaveCount(2);
    await expect(row.locator("li", { hasText: CROSS_PROJECT }).getByText(INACTIVE)).toBeVisible();
    await rulesSwitch.click();
    await expect(rulesSwitch).toBeChecked();
    await expect(row.getByText(/Inactive until/)).toHaveCount(0);
  });
});
