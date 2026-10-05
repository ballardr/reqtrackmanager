import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: docs/plans/module-01-context-and-strategy-plan.md Phase
 * 7.1's own exit criteria — Playwright e2e coverage for Strategy's create
 * -> propose -> approve flow. Exercises the full Context & Strategy
 * frontend (`frontend/src/modules/context_strategy/`) against a real
 * backend: creating a project-scoped Strategy, moving it through its
 * lifecycle to Active on its own detail page, reached via this phase's new
 * "Strategy" nav-rail entry (the first of Phase 0 Q7's five planned
 * top-level entries to actually ship a route).
 *
 * Mirrors `modules/decisions/decision-lifecycle.spec.ts`'s own structure
 * and reasoning closely — the closest existing precedent (a project-scoped
 * artefact with its own opt-in module toggle and a multi-step review
 * lifecycle):
 *
 * - **Disposable org + admin + project, created via the API**, not shared
 *   seeded state — same reasoning as `decision-lifecycle.spec.ts`: Context
 *   & Strategy is `default_enabled=False`, so this spec must toggle it on
 *   for whichever org it runs against, and a shared org would leak that
 *   toggle (and this spec's own Strategy rows) into every other spec
 *   running concurrently against it. Per CLAUDE.md's "tests must not
 *   depend on state left behind by another test" rule, every identifier
 *   below is suffixed with `Date.now()`.
 * - **`backend/scripts/seed_e2e_dataset.py` deliberately left untouched
 *   (Decided by: Agent) — a considered deviation from this phase's own
 *   brief, not an oversight.** The brief suggested adding fixed persona/
 *   org/project data to that script; checked the closest real precedent
 *   first (`decision-lifecycle.spec.ts`, a structurally identical
 *   project-scoped-artefact-with-opt-in-module case) and found it never
 *   touches that script either, using a disposable org created via the API
 *   instead. Adding unused fixed fixture data to a script that already has
 *   a working, precedented alternative — one that also satisfies CLAUDE.md's
 *   own "prefer dynamically-named fixtures over mutating shared named seed
 *   data" rule more directly than a fixed dataset would — would be doing
 *   the same job twice for no benefit, so this spec follows the existing
 *   precedent instead.
 * - The project-scoped flow only (org-scoped Strategy's own lifecycle is
 *   identical server-side — same schemas, same transition endpoints,
 *   `orgStrategyApi`/`projectStrategyApi` share one factory,
 *   `modules/context_strategy/api.ts` — so it is not independently at risk
 *   here; this matches the brief's own "project-scoped at minimum" bar).
 */
test.describe("Context & Strategy: create -> propose -> approve -> activate a Strategy", () => {
  test("moves a project-scoped Strategy through its lifecycle to Active", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Context Strategy Org ${suffix}`;
    const adminEmail = `e2e-context-strategy-admin-${suffix}@example.com`;
    const projectName = `E2E Context Strategy Project ${suffix}`;
    const strategyTitle = `Lead the regional market ${suffix}`;

    // --- Disposable org + admin + project, via the API (server admin
    // creates the org and its first admin; that admin then creates their
    // own project, becoming its ProjectRole.PROJECT_MANAGER — which
    // auto-composes with every module-contributed project-scoped role's
    // override, so this one persona can both propose and approve without
    // any extra role grant, the same reasoning `decision-lifecycle.spec.ts`
    // already relies on for its own single admin persona).
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

    // --- Enable Context & Strategy for this org (default_enabled=False —
    // `module.py`'s deliberate opt-in design). `OrgListPage.tsx` auto-
    // redirects straight to `/orgs/:orgId/admin` when the caller belongs to
    // exactly one org (true here), so there's no "org link" to click first.
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Modules");
    await expect(page.getByRole("combobox", { name: "Context & Strategy availability", exact: true })).toHaveValue("off");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");

    // --- Navigate into the project's own new "Strategy" nav entry
    // (`exact: true` disambiguates from the header's own user-menu link,
    // whose display name — "E2E Context Strategy Admin" — also contains
    // the substring "Strategy", the same disambiguation `decision-
    // lifecycle.spec.ts` needs for its own "Decisions"-containing persona
    // name).
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Strategy", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/strategies$`));

    // --- Create the Strategy and open its detail page.
    await page.getByRole("button", { name: "New Strategy" }).click();
    const dialog = page.getByRole("dialog", { name: "New Strategy (project)" });
    await dialog.getByLabel("Strategy title").fill(strategyTitle);
    await dialog.getByLabel("Objective / strategic theme").fill("Become the top provider in our region.");
    await dialog.getByRole("button", { name: "Save" }).click();
    // `DirectoryTable`'s `onRowClick` renders the first column's cell (Title)
    // as a real `<button>`, not a bare clickable `<tr>` (accessibility — see
    // that component's own docstring), so this row is reached the same way
    // `decision-lifecycle.spec.ts` reaches its own `unique_code`-as-button
    // first column.
    await expect(page.getByRole("button", { name: strategyTitle })).toBeVisible();

    await page.getByRole("button", { name: strategyTitle }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/strategies/[^/]+$`));
    await expect(page.getByRole("heading", { name: strategyTitle })).toBeVisible();
    await expect(page.getByText("Draft", { exact: true })).toBeVisible();

    // --- Walk the lifecycle: Draft -> Proposed -> Under review -> Approved -> Active.
    await page.getByRole("button", { name: "Propose" }).click();
    await expect(page.getByText("Proposed", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Submit for review" }).click();
    await expect(page.getByText("Under review", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Approve" }).click();
    const approveDialog = page.getByRole("dialog", { name: "Approve this Strategy?" });
    await approveDialog.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Activate" }).click();
    const activateDialog = page.getByRole("dialog", { name: "Activate this Strategy?" });
    await activateDialog.getByRole("button", { name: "Activate" }).click();
    await expect(page.getByText("Active", { exact: true })).toBeVisible();

    // --- Back on the list, the Strategy shows its final status.
    await page.getByRole("link", { name: "← Strategy", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/strategies$`));
    const row = page.locator("tr", { hasText: strategyTitle });
    await expect(row.getByText("Active", { exact: true })).toBeVisible();
  });
});
