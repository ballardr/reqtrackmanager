import { expect, test } from "@playwright/test";

import { PASSWORD, loginAs, selectOrgAdminGroup } from "../../e2e-workflows/helpers";

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: docs/plans/module-01-context-and-strategy-plan.md Phase
 * 7.5's own exit criteria — Playwright e2e coverage for Open Question's full
 * lifecycle, the fifth and last artefact type this module ships. Exercises
 * the Context & Strategy frontend's own `frontend/src/modules/
 * context_strategy/{OpenQuestionFormModal,ProjectOpenQuestionsPage,
 * OpenQuestionDetailPage}.tsx` against a real backend.
 *
 * Mirrors `pain-point-lifecycle.spec.ts`'s own structure and reasoning
 * closely — both artefacts share the same "project-scoped only, branching
 * lifecycle, no version table" backend shape:
 *
 * - **Disposable org + admin + project, created via the API**, not shared
 *   seeded state — same reasoning as every other spec in this module: Context
 *   & Strategy is `default_enabled=False`, so this spec must toggle it on for
 *   whichever org it runs against, and every identifier is
 *   `Date.now()`-suffixed per CLAUDE.md's "tests must not depend on state
 *   left behind by another test" rule.
 * - **`backend/scripts/seed_e2e_dataset.py` deliberately left untouched
 *   (Decided by: Agent)** — matching Phase 7.1-7.4's own identical
 *   precedent exactly (see those specs' own docstrings).
 * - Open Question has **no organisation scope at all** (source overview §9),
 *   so unlike `strategy-lifecycle.spec.ts`/`future-state-lifecycle.spec.ts`/
 *   `guiding-principle-lifecycle.spec.ts` there is no "project-scoped at
 *   minimum" caveat to record here — the project-scoped flow below is this
 *   artefact's *only* flow.
 * - Covers **both of this lifecycle's two branch points** in one spec, the
 *   same "a branch and the happy path together" precedent
 *   `pain-point-lifecycle.spec.ts` already established: the first Open
 *   Question walks the full happy path (`Open -> Investigating -> Ready for
 *   Decision -> Resolved`); a second, independently created Open Question
 *   confirms `Investigating -> Withdraw` is blocked until a comment is
 *   entered (the lifecycle's *other* branch point — `WITHDRAWN` reachable
 *   directly from `INVESTIGATING`, not only from `READY_FOR_DECISION`).
 */
test.describe("Context & Strategy: create -> investigate -> mark ready -> resolve an Open Question", () => {
  test("moves an Open Question through its lifecycle to Resolved, and blocks an uncommented Withdraw", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Open Question Org ${suffix}`;
    const adminEmail = `e2e-open-question-admin-${suffix}@example.com`;
    const projectName = `E2E Open Question Project ${suffix}`;
    const questionText = `Should we standardise on a single battery vendor ${suffix}?`;
    const secondQuestionText = `Is the UI presentation question still open ${suffix}?`;

    // --- Disposable org + admin + project, via the API (server admin
    // creates the org and its first admin; that admin then creates their
    // own project, becoming its ProjectRole.PROJECT_MANAGER — which
    // auto-composes with every module-contributed project-scoped role's
    // override, so this one persona can create, investigate, mark ready,
    // and resolve without any extra role grant, the same reasoning
    // `pain-point-lifecycle.spec.ts` already relies on for its own single
    // admin persona satisfying both `pain_point_manager`-gated actions).
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
      data: { email: adminEmail, display_name: "E2E Open Question Admin", password: PASSWORD, role: "org_admin" },
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

    // --- Navigate into the project's own new "Open Question" nav entry
    // (`exact: true` disambiguates from the header's own user-menu link,
    // whose display name — "E2E Open Question Admin" — also contains the
    // substring "Open Question", the same disambiguation
    // `pain-point-lifecycle.spec.ts` needs for its own persona name).
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Open Question", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/open-questions$`));

    // --- Create the first Open Question and open its detail page.
    await page.getByRole("button", { name: "New Open Question" }).click();
    const dialog = page.getByRole("dialog", { name: "New Open Question" });
    await dialog.getByLabel("Question").fill(questionText);
    await dialog.getByLabel("Context").fill("Two vendors are currently qualified for field deployment.");
    await dialog.getByRole("button", { name: "Save" }).click();
    // `DirectoryTable`'s `onRowClick` renders the first column's cell
    // (Question) as a real `<button>`, not a bare clickable `<tr>`
    // (accessibility — see that component's own docstring), the same
    // pattern `pain-point-lifecycle.spec.ts` reaches its own Title-column
    // button through.
    await expect(page.getByRole("button", { name: questionText })).toBeVisible();

    await page.getByRole("button", { name: questionText }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/open-questions/[^/]+$`));
    await expect(page.getByRole("heading", { name: questionText })).toBeVisible();
    await expect(page.getByText("Open", { exact: true })).toBeVisible();

    // --- Happy path: Open -> Investigating -> Ready for Decision -> Resolved.
    await page.getByRole("button", { name: "Investigate" }).click();
    await expect(page.getByText("Investigating", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Mark ready for decision" }).click();
    const markReadyDialog = page.getByRole("dialog", { name: "Mark this Open Question ready for decision?" });
    await markReadyDialog.getByRole("button", { name: "Mark ready for decision" }).click();
    await expect(page.getByText("Ready for Decision", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Resolve" }).click();
    const resolveDialog = page.getByRole("dialog", { name: "Resolve this Open Question?" });
    await resolveDialog.getByRole("button", { name: "Resolve" }).click();
    await expect(page.getByText("Resolved", { exact: true })).toBeVisible();

    // --- Back on the list, the first Open Question shows its final status.
    await page.getByRole("link", { name: "← Open Question", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/open-questions$`));
    const firstRow = page.locator("tr", { hasText: questionText });
    await expect(firstRow.getByText("Resolved", { exact: true })).toBeVisible();

    // --- Second Open Question: confirm the *other* branch point —
    // `Investigating -> Withdraw` is blocked until a comment is entered
    // (mandatory-comment-on-a-negative-outcome, matching backend
    // enforcement exactly).
    await page.getByRole("button", { name: "New Open Question" }).click();
    const secondDialog = page.getByRole("dialog", { name: "New Open Question" });
    await secondDialog.getByLabel("Question").fill(secondQuestionText);
    await secondDialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: secondQuestionText })).toBeVisible();

    await page.getByRole("button", { name: secondQuestionText }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/open-questions/[^/]+$`));
    await page.getByRole("button", { name: "Investigate" }).click();
    await expect(page.getByText("Investigating", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Withdraw" }).click();
    const withdrawDialog = page.getByRole("dialog", { name: "Withdraw this Open Question?" });
    await expect(withdrawDialog.getByRole("button", { name: "Withdraw" })).toBeDisabled();
    await withdrawDialog.getByLabel("Withdrawal comment").fill("Already answered by the field ops team directly.");
    await expect(withdrawDialog.getByRole("button", { name: "Withdraw" })).toBeEnabled();
    await withdrawDialog.getByRole("button", { name: "Withdraw" }).click();
    await expect(page.getByText("Withdrawn", { exact: true })).toBeVisible();
  });
});
