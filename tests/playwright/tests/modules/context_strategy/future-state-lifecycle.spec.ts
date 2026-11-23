import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: e2e coverage of Future State's create -> propose -> submit-for-review -> approve -> activate flow
 * (`frontend/src/modules/context_strategy/`) against a real backend, ending Active on its detail page.
 *
 * Mirrors `strategy-lifecycle.spec.ts`: Future State's backend is a structural mirror of Strategy's. Uses a
 * disposable org + admin + project created via the API (Context & Strategy is `default_enabled=False`, so the
 * spec enables it), `Date.now()`-suffixed names, and no `seed_e2e_dataset.py` fixtures. Project-scoped flow
 * only: the org-scoped lifecycle is identical server-side (`orgFutureStateApi`/`projectFutureStateApi` share
 * one factory in `modules/context_strategy/api.ts`).
 */
test.describe("Context & Strategy: create -> propose -> approve -> activate a Future State", () => {
  test("moves a project-scoped Future State through its lifecycle to Active", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Context Strategy FS Org ${suffix}`;
    const adminEmail = `e2e-context-strategy-fs-admin-${suffix}@example.com`;
    const projectName = `E2E Context Strategy FS Project ${suffix}`;
    const futureStateTitle = `Regional number one by 2028 ${suffix}`;

    // Disposable org + admin + project, via the API: the server admin creates the org and its first admin, who
    // creates their own project and becomes its ProjectRole.PROJECT_MANAGER, which composes with every
    // module-contributed project-scoped role's override, so this one persona can both propose and approve.
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
      data: { email: adminEmail, display_name: "E2E Context Strategy FS Admin", password: PASSWORD, role: "org_admin" },
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

    // --- Enable Context & Strategy for this org (default_enabled=False).
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Modules");
    await expect(page.getByRole("combobox", { name: "Context & Strategy availability", exact: true })).toHaveValue("off");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");

    // Navigate into the project's "Future State" nav entry. `exact: true` disambiguates from the header's user-menu
    // link, whose display name ("E2E Context Strategy FS Admin") contains the same substring.
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Future State", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/future-states(?:\\?.*)?$`));

    // --- Create the Future State and open its detail page.
    await page.getByRole("button", { name: "New Future State" }).click();
    const dialog = page.getByRole("dialog", { name: "New Future State (project)" });
    await dialog.getByLabel("Future State title").fill(futureStateTitle);
    await dialog.getByLabel("Desired state").fill("We are the top provider in our region.");
    await dialog.getByRole("button", { name: "Save" }).click();
    // `DirectoryTable`'s `onRowClick` renders the first column's cell
    // (Title) as a real `<button>`, not a bare clickable `<tr>`.
    await expect(page.getByRole("button", { name: futureStateTitle })).toBeVisible();

    await page.getByRole("button", { name: futureStateTitle }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/future-states/[^/]+$`));
    await expect(page.getByRole("heading", { name: futureStateTitle })).toBeVisible();
    await expect(page.getByText("Draft", { exact: true })).toBeVisible();

    // --- Walk the lifecycle: Draft -> Proposed -> Under review -> Approved -> Active.
    await page.getByRole("button", { name: "Propose" }).click();
    await expect(page.getByText("Proposed", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Submit for review" }).click();
    await expect(page.getByText("Under review", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Approve" }).click();
    const approveDialog = page.getByRole("dialog", { name: "Approve this Future State?" });
    await approveDialog.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Activate" }).click();
    const activateDialog = page.getByRole("dialog", { name: "Activate this Future State?" });
    await activateDialog.getByRole("button", { name: "Activate" }).click();
    await expect(page.getByText("Active", { exact: true })).toBeVisible();

    // --- Back on the list, the Future State shows its final status.
    await page.getByRole("link", { name: "← Future States", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/future-states(?:\\?.*)?$`));
    const row = page.locator("tr", { hasText: futureStateTitle });
    await expect(row.getByText("Active", { exact: true })).toBeVisible();
  });
});
