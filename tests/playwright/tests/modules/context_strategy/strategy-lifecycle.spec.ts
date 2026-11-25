import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability, expectCurrentStep, promoteTo, expectRecordLocked } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: e2e coverage of Strategy's create -> propose -> approve flow
 * (`frontend/src/modules/context_strategy/`) against a real backend, ending Active on its detail page.
 *
 * Mirrors `modules/decisions/decision-lifecycle.spec.ts`. Uses a disposable org + admin + project created via
 * the API: Context & Strategy is `default_enabled=False`, and a shared org would leak that toggle and these
 * Strategy rows into concurrent specs. Names are `Date.now()`-suffixed; `seed_e2e_dataset.py` is not extended.
 * Project-scoped flow only: the org-scoped lifecycle is identical server-side (`orgStrategyApi` and
 * `projectStrategyApi` share one factory in `modules/context_strategy/api.ts`).
 */
test.describe("Context & Strategy: create -> propose -> approve -> activate a Strategy", () => {
  test("moves a project-scoped Strategy through its lifecycle to Active", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Context Strategy Org ${suffix}`;
    const adminEmail = `e2e-context-strategy-admin-${suffix}@example.com`;
    const projectName = `E2E Context Strategy Project ${suffix}`;
    const strategyTitle = `Lead the regional market ${suffix}`;

    // Disposable org + admin + project, via the API: the server admin creates the org and its first admin, who
    // creates their own project and becomes its ProjectRole.PROJECT_MANAGER, which composes with every
    // module-contributed project-scoped role's override, so one persona can both propose and approve.
    const serverAdminLoginResp = await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    });
    const serverAdminToken = (await serverAdminLoginResp.json()).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const org = await (
      await page.request.post(`${API_BASE_URL}/api/v1/orgs`, {
        headers: serverAdminHeaders,
        data: { name: orgName },
      })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E Context Strategy Admin", password: PASSWORD, role: "org_admin" },
    });

    await loginAs(page, adminEmail, PASSWORD);
    const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const adminHeaders = { Authorization: `Bearer ${adminToken}` };

    const project = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
        headers: adminHeaders,
        data: { organization_id: org.id, name: projectName, summary: "" },
      })
    ).json();

    // Enable Context & Strategy for this org (`default_enabled=False`, an opt-in module). `OrgListPage.tsx`
    // redirects to `/orgs/:orgId/admin` when the caller belongs to exactly one org, so there is no "org link" to click.
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Modules");
    await expect(page.getByRole("combobox", { name: "Context & Strategy availability", exact: true })).toHaveValue("off");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");

    // Navigate into the project's "Strategy" nav entry. `exact: true` disambiguates from the header's user-menu
    // link, whose display name ("E2E Context Strategy Admin") contains the same substring.
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Strategy", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/strategies(?:\\?.*)?$`));

    // --- Create the Strategy and open its detail page.
    await page.getByRole("button", { name: "New Strategy" }).click();
    const dialog = page.getByRole("dialog", { name: "New Strategy (project)" });
    await dialog.getByLabel("Strategy title").fill(strategyTitle);
    await dialog.getByLabel("Objective / strategic theme").fill("Become the top provider in our region.");
    await dialog.getByRole("button", { name: "Save" }).click();
    // `DirectoryTable`'s `onRowClick` renders the first column's cell (Title) as a real `<button>` (accessibility;
    // see that component's docstring), as `decision-lifecycle.spec.ts` reaches its `unique_code` button.
    await expect(page.getByRole("button", { name: strategyTitle })).toBeVisible();

    await page.getByRole("button", { name: strategyTitle }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/strategies/[^/]+$`));
    await expect(page.getByRole("heading", { name: strategyTitle })).toBeVisible();
    await expectCurrentStep(page, "Draft");

    // --- Walk the lifecycle: Draft -> Proposed -> Under review -> Approved -> Active.
    await promoteTo(page, "Proposed");
    await expectCurrentStep(page, "Proposed");

    await promoteTo(page, "Under review");
    await expectCurrentStep(page, "Under review");

    await promoteTo(page, "Approved");
    const approveDialog = page.getByRole("dialog", { name: "Approve this Strategy?" });
    await approveDialog.getByRole("button", { name: "Approve" }).click();
    await expectCurrentStep(page, "Approved");
    await expectRecordLocked(page);

    await promoteTo(page, "Active");
    const activateDialog = page.getByRole("dialog", { name: "Activate this Strategy?" });
    await activateDialog.getByRole("button", { name: "Activate" }).click();
    await expectCurrentStep(page, "Active");

    // --- Back on the list, the Strategy shows its final status.
    await page.getByRole("link", { name: "← Strategies", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/strategies(?:\\?.*)?$`));
    const row = page.locator("tr", { hasText: strategyTitle });
    await expect(row.getByText("Active", { exact: true })).toBeVisible();
  });
});
