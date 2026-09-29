import { expect, test } from "@playwright/test";

import { PASSWORD, loginAs, selectOrgAdminGroup } from "../../e2e-workflows/helpers";

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: docs/plans/module-01-context-and-strategy-plan.md Phase
 * 7.4's own exit criteria — Playwright e2e coverage for Guiding Principle's
 * full lifecycle. Exercises the Context & Strategy frontend's fourth
 * artefact type (`frontend/src/modules/context_strategy/`) against a real
 * backend.
 *
 * Mirrors `strategy-lifecycle.spec.ts`'s/`future-state-lifecycle.spec.ts`'s/
 * `pain-point-lifecycle.spec.ts`'s own structure and reasoning closely:
 *
 * - **Disposable org + admin + project, created via the API**, not shared
 *   seeded state — same reasoning as those three specs: Context & Strategy
 *   is `default_enabled=False`, so this spec must toggle it on for whichever
 *   org it runs against, and every identifier is `Date.now()`-suffixed per
 *   CLAUDE.md's "tests must not depend on state left behind by another test"
 *   rule.
 * - **`backend/scripts/seed_e2e_dataset.py` deliberately left untouched
 *   (Decided by: Agent)** — matching Phase 7.1/7.2/7.3's own identical
 *   precedent and reasoning exactly (see those specs' own docstrings): a
 *   disposable org created via the API already satisfies this repo's own
 *   "prefer dynamically-named fixtures over mutating shared named seed
 *   data" rule more directly than adding unused fixed fixture data would.
 * - The project-scoped flow only (org-scoped Guiding Principle's own
 *   lifecycle is identical server-side — same schemas, same transition
 *   endpoints, `orgGuidingPrincipleApi`/`projectGuidingPrincipleApi` share
 *   one factory, `modules/context_strategy/api.ts` — so it is not
 *   independently at risk here; this matches Phase 7.1/7.2's own "project-
 *   scoped at minimum" bar).
 * - Unlike Strategy's/Future State's seven-state lifecycle, Guiding
 *   Principle has **no "Under review" step** — `Propose` is followed
 *   directly by `Approve`/`Send back`, not `Submit for review`. This spec
 *   walks the send-back path first (mandatory comment, this module's
 *   "reject"-equivalent) before re-proposing and completing the lifecycle to
 *   `Active`, so both the rework path and the happy path get real coverage
 *   in one spec, mirroring `pain-point-lifecycle.spec.ts`'s own "both a
 *   branch and the happy path" precedent.
 */
test.describe("Context & Strategy: create -> propose -> send back -> re-propose -> approve -> activate a Guiding Principle", () => {
  test("moves a project-scoped Guiding Principle through its lifecycle to Active", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Guiding Principle Org ${suffix}`;
    const adminEmail = `e2e-guiding-principle-admin-${suffix}@example.com`;
    const projectName = `E2E Guiding Principle Project ${suffix}`;
    const guidingPrincipleName = `Field data is captured once ${suffix}`;

    // --- Disposable org + admin + project, via the API (server admin
    // creates the org and its first admin; that admin then creates their
    // own project, becoming its ProjectRole.PROJECT_MANAGER — which
    // auto-composes with every module-contributed project-scoped role's
    // override, so this one persona can both propose and approve without
    // any extra role grant, the same reasoning `strategy-lifecycle.spec.ts`
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
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E Guiding Principle Admin", password: PASSWORD, role: "org_admin" },
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
    const moduleRow = page.locator("tr", { hasText: "Context & Strategy" });
    await expect(moduleRow).toBeVisible();
    const moduleToggle = moduleRow.getByRole("switch");
    await expect(moduleToggle).toHaveAttribute("aria-checked", "false");
    await moduleToggle.click();
    await expect(moduleToggle).toHaveAttribute("aria-checked", "true");

    // --- Navigate into the project's own new "Guiding Principle" nav entry
    // (`exact: true` disambiguates from the header's own user-menu link,
    // whose display name — "E2E Guiding Principle Admin" — also contains
    // the substring "Guiding Principle", the same disambiguation
    // `strategy-lifecycle.spec.ts` needs for its own persona name).
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Guiding Principle", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/guiding-principles$`));

    // --- Create the Guiding Principle and open its detail page.
    await page.getByRole("button", { name: "New Guiding Principle" }).click();
    const dialog = page.getByRole("dialog", { name: "New Guiding Principle (project)" });
    await dialog.getByLabel("Guiding Principle name").fill(guidingPrincipleName);
    await dialog.getByLabel("Principle statement").fill("Every field observation is recorded exactly once, at the point of inspection.");
    await dialog.getByRole("button", { name: "Save" }).click();
    // `DirectoryTable`'s `onRowClick` renders the first column's cell (Name)
    // as a real `<button>`, not a bare clickable `<tr>` (accessibility — see
    // that component's own docstring), so this row is reached the same way
    // `strategy-lifecycle.spec.ts` reaches its own Title-column button.
    await expect(page.getByRole("button", { name: guidingPrincipleName })).toBeVisible();

    await page.getByRole("button", { name: guidingPrincipleName }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/guiding-principles/[^/]+$`));
    await expect(page.getByRole("heading", { name: guidingPrincipleName })).toBeVisible();
    await expect(page.getByText("Draft", { exact: true })).toBeVisible();

    // --- Propose, then send back for rework (mandatory comment) — Guiding
    // Principle's own "reject"-equivalent, with no "Under review" step in
    // between (unlike Strategy/Future State, `Propose` goes straight to
    // offering `Approve`/`Send back`).
    await page.getByRole("button", { name: "Propose" }).click();
    await expect(page.getByText("Proposed", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Submit for review" })).toHaveCount(0);

    await page.getByRole("button", { name: "Send back" }).click();
    const sendBackDialog = page.getByRole("dialog", { name: "Send this Guiding Principle back to Draft?" });
    await expect(sendBackDialog.getByRole("button", { name: "Send back" })).toBeDisabled();
    await sendBackDialog.getByLabel("Send-back comment").fill("Needs a stronger rationale before it can be approved.");
    await sendBackDialog.getByRole("button", { name: "Send back" }).click();
    await expect(page.getByText("Draft", { exact: true })).toBeVisible();

    // --- Re-propose and complete the happy path: Proposed -> Approved -> Active.
    await page.getByRole("button", { name: "Propose" }).click();
    await expect(page.getByText("Proposed", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Approve" }).click();
    const approveDialog = page.getByRole("dialog", { name: "Approve this Guiding Principle?" });
    await approveDialog.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Activate" }).click();
    const activateDialog = page.getByRole("dialog", { name: "Activate this Guiding Principle?" });
    await activateDialog.getByRole("button", { name: "Activate" }).click();
    await expect(page.getByText("Active", { exact: true })).toBeVisible();

    // --- Back on the list, the Guiding Principle shows its final status.
    await page.getByRole("link", { name: "← Guiding Principle", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/guiding-principles$`));
    const row = page.locator("tr", { hasText: guidingPrincipleName });
    await expect(row.getByText("Active", { exact: true })).toBeVisible();
  });
});
