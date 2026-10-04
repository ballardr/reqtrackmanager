import { expect, test } from "@playwright/test";

import { PASSWORD, loginAs, selectOrgAdminGroup, setOrgModuleAvailability } from "../../e2e-workflows/helpers";

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: docs/plans/module-01-context-and-strategy-plan.md Phase
 * 7.2's own exit criteria — Playwright e2e coverage for Future State's
 * create -> propose -> submit-for-review -> approve -> activate flow.
 * Exercises the full Future State frontend
 * (`frontend/src/modules/context_strategy/{ProjectFutureStatesPage,
 * FutureStateDetailPage,FutureStateFormModal}.tsx`) against a real backend:
 * creating a project-scoped Future State, moving it through its lifecycle to
 * Active on its own detail page, reached via this phase's new "Future
 * State" nav-rail entry (the second of Phase 0 Q7's five planned top-level
 * entries to ship a route).
 *
 * Mirrors `strategy-lifecycle.spec.ts`'s own structure and reasoning
 * directly — Future State's backend is itself "an exact structural mirror"
 * of Strategy's (Phase 2's own scope text: same org/project scope
 * discriminator, same seven-state lifecycle, same owner/approver RBAC
 * pattern), so this spec follows the same conventions rather than
 * inventing new ones:
 *
 * - **Disposable org + admin + project, created via the API**, not shared
 *   seeded state — same reasoning as `strategy-lifecycle.spec.ts`: Context
 *   & Strategy is `default_enabled=False`, so this spec must toggle it on
 *   for whichever org it runs against, and every identifier below is
 *   suffixed with `Date.now()` per CLAUDE.md's "tests must not depend on
 *   state left behind by another test" rule.
 * - **`backend/scripts/seed_e2e_dataset.py` deliberately left untouched
 *   (Decided by: Agent), matching `strategy-lifecycle.spec.ts`'s own
 *   precedent exactly** — this spec creates its own disposable org/project
 *   via the API rather than adding unused fixed fixture data to that
 *   script.
 * - The project-scoped flow only (org-scoped Future State's own lifecycle
 *   is identical server-side — same schemas, same transition endpoints,
 *   `orgFutureStateApi`/`projectFutureStateApi` share one factory,
 *   `modules/context_strategy/api.ts` — so it is not independently at risk
 *   here; matches `strategy-lifecycle.spec.ts`'s own "project-scoped at
 *   minimum" bar).
 */
test.describe("Context & Strategy: create -> propose -> approve -> activate a Future State", () => {
  test("moves a project-scoped Future State through its lifecycle to Active", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Context Strategy FS Org ${suffix}`;
    const adminEmail = `e2e-context-strategy-fs-admin-${suffix}@example.com`;
    const projectName = `E2E Context Strategy FS Project ${suffix}`;
    const futureStateTitle = `Regional number one by 2028 ${suffix}`;

    // --- Disposable org + admin + project, via the API (server admin
    // creates the org and its first admin; that admin then creates their
    // own project, becoming its ProjectRole.PROJECT_MANAGER — which
    // auto-composes with every module-contributed project-scoped role's
    // override, so this one persona can both propose and approve, same
    // reasoning `strategy-lifecycle.spec.ts` already relies on).
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

    // --- Navigate into the project's own "Future State" nav entry
    // (`exact: true` disambiguates from the header's own user-menu link,
    // whose display name — "E2E Context Strategy FS Admin" — also contains
    // no "Future State" substring here, but kept for symmetry with
    // `strategy-lifecycle.spec.ts`'s own disambiguation).
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Future State", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/future-states$`));

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
    await page.getByRole("link", { name: "← Future State", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/future-states$`));
    const row = page.locator("tr", { hasText: futureStateTitle });
    await expect(row.getByText("Active", { exact: true })).toBeVisible();
  });
});
