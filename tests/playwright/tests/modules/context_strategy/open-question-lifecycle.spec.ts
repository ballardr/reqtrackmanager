import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: e2e coverage of Open Question's full lifecycle (`frontend/src/modules/context_strategy/`)
 * against a real backend.
 *
 * Mirrors `pain-point-lifecycle.spec.ts` for setup: a disposable org + admin + project created via the API
 * (Context & Strategy is `default_enabled=False`), `Date.now()`-suffixed names, no `seed_e2e_dataset.py`
 * fixtures. Open Question has no organisation scope (§9), so the project-scoped flow is its only flow. Covers
 * both branch points: a happy path (`Open -> Investigating -> Ready for Decision -> Resolved`) and a second
 * question showing `Investigating -> Withdraw` is blocked until a comment is entered.
 */
test.describe("Context & Strategy: create -> investigate -> mark ready -> resolve an Open Question", () => {
  test("moves an Open Question through its lifecycle to Resolved, and blocks an uncommented Withdraw", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Open Question Org ${suffix}`;
    const adminEmail = `e2e-open-question-admin-${suffix}@example.com`;
    const projectName = `E2E Open Question Project ${suffix}`;
    const questionText = `Should we standardise on a single battery vendor ${suffix}?`;
    const secondQuestionText = `Is the UI presentation question still open ${suffix}?`;

    // Disposable org + admin + project, via the API: the server admin creates the org and its first admin, who
    // creates their own project and becomes its ProjectRole.PROJECT_MANAGER, which composes with every
    // module-contributed project-scoped role's override, so this one persona can create, investigate, mark ready and resolve without any extra role grant.
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

    // Enable Context & Strategy for this org (`default_enabled=False`, an opt-in module). `OrgListPage.tsx`
    // redirects to `/orgs/:orgId/admin` when the caller belongs to exactly one org, so there is no "org link" to click.
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Modules");
    await expect(page.getByRole("combobox", { name: "Context & Strategy availability", exact: true })).toHaveValue("off");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");

    // Navigate into the project's "Open Question" nav entry. `exact: true` disambiguates from the header's user-menu
    // link, whose display name ("E2E Open Question Admin") contains the same substring.
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Open Question", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/open-questions(?:\\?.*)?$`));

    // --- Create the first Open Question and open its detail page.
    await page.getByRole("button", { name: "New Open Question" }).click();
    const dialog = page.getByRole("dialog", { name: "New Open Question" });
    await dialog.getByLabel("Question").fill(questionText);
    await dialog.getByLabel("Context").fill("Two vendors are currently qualified for field deployment.");
    await dialog.getByRole("button", { name: "Save" }).click();
    // `DirectoryTable`'s `onRowClick` renders the first column's cell (Question) as a real `<button>`
    // (accessibility; see that component's docstring), as `pain-point-lifecycle.spec.ts` reaches its Title button.
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
    await page.getByRole("link", { name: "← Open Questions", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/open-questions(?:\\?.*)?$`));
    // The list opens on unresolved questions only, so the resolved one appears once that filter is cleared.
    await expect(page.getByRole("checkbox", { name: "Open only" })).toBeChecked();
    await expect(page.locator("tr", { hasText: questionText })).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Open only" }).uncheck();
    const firstRow = page.locator("tr", { hasText: questionText });
    await expect(firstRow.getByText("Resolved", { exact: true })).toBeVisible();

    // Second Open Question: `Investigating -> Withdraw` is blocked until a comment is entered (a mandatory
    // comment on a negative outcome, matching backend enforcement).
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
