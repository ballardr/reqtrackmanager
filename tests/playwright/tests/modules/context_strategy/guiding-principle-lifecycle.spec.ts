import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability, chooseRecordMenuAction, expectCurrentStep, promoteTo, expectRecordLocked } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: e2e coverage of Guiding Principle's full lifecycle (`frontend/src/modules/context_strategy/`)
 * against a real backend.
 *
 * Mirrors `strategy-lifecycle.spec.ts` for setup: a disposable org + admin + project created via the API
 * (Context & Strategy is `default_enabled=False`), `Date.now()`-suffixed names, no `seed_e2e_dataset.py`
 * fixtures, and the project-scoped flow only (the org-scoped lifecycle shares one API factory in
 * `modules/context_strategy/api.ts`). Unlike Strategy's seven states, Guiding Principle has no "Under review"
 * step: `Propose` is followed by `Approve`/`Send back`. The spec walks the send-back path (mandatory comment)
 * before re-proposing and completing to `Active`, covering rework and happy path together.
 */
test.describe("Context & Strategy: create -> propose -> send back -> re-propose -> approve -> activate a Guiding Principle", () => {
  test("moves a project-scoped Guiding Principle through its lifecycle to Active", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Guiding Principle Org ${suffix}`;
    const adminEmail = `e2e-guiding-principle-admin-${suffix}@example.com`;
    const projectName = `E2E Guiding Principle Project ${suffix}`;
    const guidingPrincipleName = `Field data is captured once ${suffix}`;

    // Disposable org + admin + project, via the API: the server admin creates the org and its first admin, who
    // creates their own project and becomes its ProjectRole.PROJECT_MANAGER, which composes with every
    // module-contributed project-scoped role's override, so this one persona can both propose and approve without any extra role grant.
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

    // Enable Context & Strategy for this org (`default_enabled=False`, an opt-in module). `OrgListPage.tsx`
    // redirects to `/orgs/:orgId/admin` when the caller belongs to exactly one org, so there is no "org link" to click.
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Modules");
    await expect(page.getByRole("combobox", { name: "Context & Strategy availability", exact: true })).toHaveValue("off");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");

    // Navigate into the project's "Guiding Principle" nav entry. `exact: true` disambiguates from the header's user-menu
    // link, whose display name ("E2E Guiding Principle Admin") contains the same substring.
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Guiding Principle", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/guiding-principles(?:\\?.*)?$`));

    // --- Create the Guiding Principle and open its detail page.
    await page.getByRole("button", { name: "New Guiding Principle" }).click();
    const dialog = page.getByRole("dialog", { name: "New Guiding Principle (project)" });
    await dialog.getByLabel("Guiding Principle name").fill(guidingPrincipleName);
    await dialog.getByLabel("Principle statement").fill("Every field observation is recorded exactly once, at the point of inspection.");
    await dialog.getByRole("button", { name: "Save" }).click();
    // `DirectoryTable`'s `onRowClick` renders the first column's cell (Name) as a real `<button>` (accessibility;
    // see that component's docstring), so the row is reached as `strategy-lifecycle.spec.ts` reaches its Title button.
    await expect(page.getByRole("button", { name: guidingPrincipleName })).toBeVisible();

    await page.getByRole("button", { name: guidingPrincipleName }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/guiding-principles/[^/]+$`));
    await expect(page.getByRole("heading", { name: guidingPrincipleName })).toBeVisible();
    await expectCurrentStep(page, "Draft");

    // Propose, then send back for rework (mandatory comment), Guiding Principle's "reject" equivalent. There is
    // no "Under review" step: `Propose` goes straight to offering `Approve`/`Send back`.
    await promoteTo(page, "Proposed");
    await expectCurrentStep(page, "Proposed");
    await expect(page.getByRole("list", { name: "Lifecycle" }).getByText("Under review")).toHaveCount(0);

    await chooseRecordMenuAction(page, "Send back");
    const sendBackDialog = page.getByRole("dialog", { name: "Send this Guiding Principle back to Draft?" });
    await expect(sendBackDialog.getByRole("button", { name: "Send back" })).toBeDisabled();
    await sendBackDialog.getByLabel("Send-back comment").fill("Needs a stronger rationale before it can be approved.");
    await sendBackDialog.getByRole("button", { name: "Send back" }).click();
    await expectCurrentStep(page, "Draft");

    // --- Re-propose and complete the happy path: Proposed -> Approved -> Active.
    await promoteTo(page, "Proposed");
    await expectCurrentStep(page, "Proposed");

    await promoteTo(page, "Approved");
    const approveDialog = page.getByRole("dialog", { name: "Approve this Guiding Principle?" });
    await approveDialog.getByRole("button", { name: "Approve" }).click();
    await expectCurrentStep(page, "Approved");
    await expectRecordLocked(page);

    await promoteTo(page, "Active");
    const activateDialog = page.getByRole("dialog", { name: "Activate this Guiding Principle?" });
    await activateDialog.getByRole("button", { name: "Activate" }).click();
    await expectCurrentStep(page, "Active");

    // --- Back on the list, the Guiding Principle shows its final status.
    await page.getByRole("link", { name: "← Guiding Principles", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/guiding-principles(?:\\?.*)?$`));
    const row = page.locator("tr", { hasText: guidingPrincipleName });
    await expect(row.getByText("Active", { exact: true })).toBeVisible();
  });
});
