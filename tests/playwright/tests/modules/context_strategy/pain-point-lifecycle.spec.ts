import { expect, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectProjectAdminGroup, setOrgModuleAvailability } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/** `DefinitionList` type-vocabulary names render as editable `<input>` value
 * attributes (the rename form), not plain text nodes — Playwright has no
 * built-in `getByDisplayValue` (that's a Testing Library API this repo's
 * frontend Storybook/Vitest stories use, not the Playwright `Page`/`Locator`
 * API), so this mirrors `project-admin-action-types.spec.ts`'s own
 * `inputWithValue` helper exactly. */
function inputWithValue(page: Page, value: string) {
  return page.locator(`input.input[value="${value}"]:not([placeholder])`);
}

/**
 * Job to be done: docs/plans/module-01-context-and-strategy-plan.md Phase
 * 7.3's own exit criteria — Playwright e2e coverage for Pain Point's full
 * branching lifecycle plus its two-tier type-vocabulary admin surfaces.
 * Exercises the Context & Strategy frontend's third artefact type
 * (`frontend/src/modules/context_strategy/`) against a real backend.
 *
 * Mirrors `strategy-lifecycle.spec.ts`'s/`future-state-lifecycle.spec.ts`'s
 * own structure and reasoning closely:
 *
 * - **Disposable org + admin + project, created via the API**, not shared
 *   seeded state — same reasoning as those two specs: Context & Strategy is
 *   `default_enabled=False`, so this spec must toggle it on for whichever
 *   org it runs against, and every identifier is `Date.now()`-suffixed per
 *   CLAUDE.md's "tests must not depend on state left behind by another
 *   test" rule.
 * - **`backend/scripts/seed_e2e_dataset.py` deliberately left untouched
 *   (Decided by: Agent)** — matching Phase 7.1/7.2's own identical
 *   precedent and reasoning exactly (see those specs' own docstrings): a
 *   disposable org created via the API already satisfies this repo's own
 *   "prefer dynamically-named fixtures over mutating shared named seed
 *   data" rule more directly than adding unused fixed fixture data would.
 * - Pain Point is project-scoped only (source overview §6), so unlike
 *   Strategy/Future State there is no org-scoped artefact flow to also
 *   cover — but its own org-scoped Pain Point *Type* vocabulary tier (Phase
 *   0 Q3) needs its own coverage here, since neither of those two specs'
 *   own artefacts have an equivalent two-tier configuration surface.
 * - The freshly-created organisation already has Market/User/Operator Pain
 *   Point types seeded automatically (`module.py`'s `on_org_created`
 *   hook, source overview §6.2) — `run_on_org_created_hooks` runs for
 *   every registered module regardless of enablement, so these three types
 *   exist before Context & Strategy is even toggled on for this org.
 */
test.describe("Context & Strategy: Pain Point lifecycle and type vocabulary", () => {
  test("walks a Pain Point through its branching lifecycle and exercises both type-vocabulary admin tiers", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Pain Point Org ${suffix}`;
    const adminEmail = `e2e-pain-point-admin-${suffix}@example.com`;
    const projectName = `E2E Pain Point Project ${suffix}`;
    const orgTypeName = `E2E Regulatory ${suffix}`;
    const overriddenTypeName = `E2E Regulatory Overridden ${suffix}`;
    const painPointTitle = `Report delays under poor connectivity ${suffix}`;
    const duplicatePainPointTitle = `Second report of the same problem ${suffix}`;

    // --- Disposable org + admin + project, via the API (same pattern as
    // strategy-lifecycle.spec.ts/future-state-lifecycle.spec.ts).
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
      data: { email: adminEmail, display_name: "E2E Pain Point Admin", password: PASSWORD, role: "org_admin" },
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

    // --- Enable Context & Strategy for this org.
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Modules");
    await expect(page.getByRole("combobox", { name: "Context & Strategy availability", exact: true })).toHaveValue("off");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");

    await test.step("org tier: Market/User/Operator are seeded, and a new org type can be added", async () => {
      await selectOrgAdminGroup(page, "Pain Point Types");
      await expect(inputWithValue(page, "Market")).toBeVisible();
      await expect(inputWithValue(page, "User")).toBeVisible();
      await expect(inputWithValue(page, "Operator")).toBeVisible();

      await page.getByPlaceholder("Pain Point type name").fill(orgTypeName);
      await page.getByRole("button", { name: "Add Pain Point type" }).click();
      await expect(inputWithValue(page, orgTypeName)).toBeVisible();
    });

    await test.step("project tier: the new org type appears in this project's effective list and can be overridden locally", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Types");
      // Scoped to this type's own row — every untouched org default (Market/
      // User/Operator, and this new org type before its override) shares the
      // same "Org default" text, so a page-wide `getByText` would match more
      // than one element (a Playwright strict-mode violation).
      let orgTypeRow = inputWithValue(page, orgTypeName).locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await expect(orgTypeRow.getByText("Org default", { exact: true })).toBeVisible();

      await inputWithValue(page, orgTypeName).fill(overriddenTypeName);
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(inputWithValue(page, overriddenTypeName)).toBeVisible();
      orgTypeRow = inputWithValue(page, overriddenTypeName).locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await expect(orgTypeRow.getByText("Org default (overridden)")).toBeVisible();
    });

    // --- Navigate into the project's own new "Pain Point" nav entry.
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Pain Point", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/pain-points$`));

    // --- Create the Pain Point (using the project-locally-overridden type)
    // and open its detail page.
    await page.getByRole("button", { name: "New Pain Point" }).click();
    const createDialog = page.getByRole("dialog", { name: "New Pain Point" });
    await createDialog.getByLabel("Type", { exact: true }).selectOption({ label: overriddenTypeName });
    await createDialog.getByLabel("Pain Point title").fill(painPointTitle);
    await createDialog.getByLabel("Description").fill("Field reports queue for days before reaching HQ.");
    await createDialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: painPointTitle })).toBeVisible();

    await page.getByRole("button", { name: painPointTitle }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/pain-points/[^/]+$`));
    await expect(page.getByRole("heading", { name: painPointTitle })).toBeVisible();
    await expect(page.getByText("Submitted", { exact: true })).toBeVisible();

    await test.step("walk the lifecycle: Submitted -> Triaged -> Accepted -> Addressed -> Closed", async () => {
      await page.getByRole("button", { name: "Triage" }).click();
      await expect(page.getByText("Triaged", { exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Accept" }).click();
      const acceptDialog = page.getByRole("dialog", { name: "Accept this Pain Point?" });
      await acceptDialog.getByRole("button", { name: "Accept" }).click();
      await expect(page.getByText("Accepted", { exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Address" }).click();
      const addressDialog = page.getByRole("dialog", { name: "Mark this Pain Point addressed?" });
      await addressDialog.getByRole("button", { name: "Address" }).click();
      await expect(page.getByText("Addressed", { exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Close" }).click();
      const closeDialog = page.getByRole("dialog", { name: "Close this Pain Point?" });
      // `closeDialog.getByRole("button", { name: "Close" })` would be
      // ambiguous: `Modal`'s own header dismiss ("X") button also has
      // `aria-label="Close"`, colliding with this specific action's
      // `confirmLabel` ("Close") — a naming coincidence unique to this
      // action (Strategy/Future State have no lifecycle action literally
      // named "Close"). Scoped to the confirm button's own class instead.
      await closeDialog.locator("button.btn-danger").click();
      await expect(page.getByText("Closed", { exact: true })).toBeVisible();
    });

    // --- Back on the list, the Pain Point shows its final status.
    await page.getByRole("link", { name: "← Pain Point", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/pain-points$`));
    const row = page.locator("tr", { hasText: painPointTitle });
    await expect(row.getByText("Closed", { exact: true })).toBeVisible();

    await test.step("Triaged -> Reject requires a comment", async () => {
      await page.getByRole("button", { name: "New Pain Point" }).click();
      const dialog = page.getByRole("dialog", { name: "New Pain Point" });
      await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Operator" });
      await dialog.getByLabel("Pain Point title").fill(duplicatePainPointTitle);
      await dialog.getByRole("button", { name: "Save" }).click();
      await page.getByRole("button", { name: duplicatePainPointTitle }).click();

      await page.getByRole("button", { name: "Triage" }).click();
      await expect(page.getByText("Triaged", { exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Reject" }).click();
      const rejectDialog = page.getByRole("dialog", { name: "Reject this Pain Point?" });
      await expect(rejectDialog.getByRole("button", { name: "Reject" })).toBeDisabled();
      await rejectDialog.getByLabel("Rejection comment").fill("Out of scope for this quarter.");
      await expect(rejectDialog.getByRole("button", { name: "Reject" })).toBeEnabled();
      await rejectDialog.getByRole("button", { name: "Reject" }).click();
      await expect(page.getByText("Rejected", { exact: true })).toBeVisible();
    });
  });
});
