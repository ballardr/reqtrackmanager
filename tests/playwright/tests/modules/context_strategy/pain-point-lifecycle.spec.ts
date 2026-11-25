import { expect, type Page, test } from "@playwright/test";

import { addDefinition, deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectProjectAdminGroup, setOrgModuleAvailability, chooseRecordMenuAction, expectCurrentStep, promoteTo, expectRecordLocked } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/** `DefinitionList` type-vocabulary names render as editable `<input>` value attributes (the rename form), not
 * text nodes. Playwright has no `getByDisplayValue` (a Testing Library API), so this mirrors
 * `project-admin-action-types.spec.ts`'s `inputWithValue` helper. */
function inputWithValue(page: Page, value: string) {
  return page.locator(`input.input[value="${value}"]:not([placeholder])`);
}

/**
 * Job to be done: e2e coverage of Pain Point's full branching lifecycle plus its two-tier type-vocabulary admin
 * surfaces (`frontend/src/modules/context_strategy/`) against a real backend.
 *
 * Mirrors `strategy-lifecycle.spec.ts` for setup: a disposable org + admin + project created via the API,
 * `Date.now()`-suffixed names, no `seed_e2e_dataset.py` fixtures. Pain Point is project-scoped only (§6), but
 * its org-scoped Type vocabulary tier needs coverage here. A new organisation has Market/User/Operator types
 * seeded (`on_org_created` hook, §6.2; `run_on_org_created_hooks` runs whatever the module's enablement).
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
      await selectOrgAdminGroup(page, "Pain Point Types", "Pain Points");
      await expect(inputWithValue(page, "Market")).toBeVisible();
      await expect(inputWithValue(page, "User")).toBeVisible();
      await expect(inputWithValue(page, "Operator")).toBeVisible();

      await addDefinition(page, "Add Pain Point type", { Name: orgTypeName });
      await expect(inputWithValue(page, orgTypeName)).toBeVisible();
    });

    await test.step("project tier: the new org type appears in this project's effective list and can be overridden locally", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Types", "Pain Points");
      // Scoped to this type's row: every untouched org default (Market/User/Operator, and this new org type before
      // its override) shares the "Org default" text, so a page-wide `getByText` would match several elements
      // (a Playwright strict-mode violation).
      let orgTypeRow = inputWithValue(page, orgTypeName).locator("xpath=ancestor::div[contains(@class,'definition-grid__row')][1]");
      await expect(orgTypeRow.getByText("Org default", { exact: true })).toBeVisible();

      await inputWithValue(page, orgTypeName).fill(overriddenTypeName);
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(inputWithValue(page, overriddenTypeName)).toBeVisible();
      orgTypeRow = inputWithValue(page, overriddenTypeName).locator("xpath=ancestor::div[contains(@class,'definition-grid__row')][1]");
      await expect(orgTypeRow.getByText("Org default (overridden)")).toBeVisible();
    });

    // --- Navigate into the project's own new "Pain Point" nav entry.
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Pain Point", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/pain-points(?:\\?.*)?$`));

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
    await expectCurrentStep(page, "Submitted");

    await test.step("walk the lifecycle: Submitted -> Triaged -> Accepted -> Addressed -> Closed", async () => {
      await promoteTo(page, "Triaged");
      await expectCurrentStep(page, "Triaged");

      await promoteTo(page, "Accepted");
      const acceptDialog = page.getByRole("dialog", { name: "Accept this Pain Point?" });
      await acceptDialog.getByRole("button", { name: "Accept" }).click();
      await expectCurrentStep(page, "Accepted");

      await promoteTo(page, "Addressed");
      const addressDialog = page.getByRole("dialog", { name: "Mark this Pain Point addressed?" });
      await addressDialog.getByRole("button", { name: "Address" }).click();
      await expectCurrentStep(page, "Addressed");

      await promoteTo(page, "Closed");
      const closeDialog = page.getByRole("dialog", { name: "Close this Pain Point?" });
      // `closeDialog.getByRole("button", { name: "Close" })` would be ambiguous: `Modal`'s header dismiss ("X")
      // button also has `aria-label="Close"`, colliding with this action's `confirmLabel` ("Close"). The
      // locator is scoped to the confirm button's class instead.
      await closeDialog.locator("button.btn-danger").click();
      await expectCurrentStep(page, "Closed");
      await expectRecordLocked(page);
    });

    // --- Back on the list, the Pain Point shows its final status.
    await page.getByRole("link", { name: "← Pain Points", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/pain-points(?:\\?.*)?$`));
    // The list opens on open Pain Points only, so a closed one appears once that filter is cleared.
    await expect(page.getByRole("checkbox", { name: "Open only" })).toBeChecked();
    await expect(page.locator("tr", { hasText: painPointTitle })).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Open only" }).uncheck();
    const row = page.locator("tr", { hasText: painPointTitle });
    await expect(row.getByText("Closed", { exact: true })).toBeVisible();

    await test.step("Triaged -> Reject requires a comment", async () => {
      await page.getByRole("button", { name: "New Pain Point" }).click();
      const dialog = page.getByRole("dialog", { name: "New Pain Point" });
      await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Operator" });
      await dialog.getByLabel("Pain Point title").fill(duplicatePainPointTitle);
      await dialog.getByRole("button", { name: "Save" }).click();
      await page.getByRole("button", { name: duplicatePainPointTitle }).click();

      await promoteTo(page, "Triaged");
      await expectCurrentStep(page, "Triaged");

      await chooseRecordMenuAction(page, "Reject");
      const rejectDialog = page.getByRole("dialog", { name: "Reject this Pain Point?" });
      await expect(rejectDialog.getByRole("button", { name: "Reject" })).toBeDisabled();
      await rejectDialog.getByLabel("Rejection comment").fill("Out of scope for this quarter.");
      await expect(rejectDialog.getByRole("button", { name: "Reject" })).toBeEnabled();
      await rejectDialog.getByRole("button", { name: "Reject" }).click();
      await expectCurrentStep(page, "Rejected");
    });
  });
});
