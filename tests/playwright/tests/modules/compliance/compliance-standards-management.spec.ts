import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, selectOrgAdminGroup } from "../../e2e-workflows/helpers";

/**
 * Job to be done: Compliance Module Phase 12 (docs/compliance-module-plan.md)
 * — the org-level, Compliance-Manager-facing management UI
 * (`frontend/src/modules/compliance/`, mounted as a new "Compliance" group
 * on `OrgAdminPage`). Covers the core authoring flow §2-§6 describe: create
 * a standard, create a draft version, add a requirement, add a required
 * action to it (needing an org-scoped action type first), then publish the
 * version and confirm its requirements become immutable in the UI.
 *
 * `orgAdminAlphaBeta` is used rather than a dedicated `compliance_manager`
 * persona — `require_module_role("compliance", "compliance_manager")`
 * composes with `OrgRole.ORG_ADMIN` by design (module system Phase 2), and
 * this persona is already seeded as Alpha's org admin
 * (`backend/scripts/seed_e2e_dataset.py`), so no new seed persona/module-
 * role grant is needed for this spec specifically.
 *
 * Every fixture this spec creates (standard, action type) is dynamically
 * named with a per-run timestamp suffix, per this repo's standing test-
 * idempotency rule — nothing here mutates or depends on another spec's
 * named fixtures, and re-running this spec (alone, repeated, or out of
 * order) only ever adds new, uniquely-named rows rather than colliding with
 * a previous run's.
 */
test.describe("Compliance Module: org-level standards management (Phase 12)", () => {
  test("create a standard, version, requirement and required action, then publish", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-${suffix}`;
    const standardName = `E2E Compliance Standard ${suffix}`;
    const actionTypeName = `E2E Evidence Review ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/orgs");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Compliance");

    // --- Action types: create one, needed for the required action below.
    await page.getByRole("tab", { name: "Action types" }).click();
    await page.getByPlaceholder("Action type name").fill(actionTypeName);
    await page.getByRole("button", { name: "Add action type" }).click();
    await expect(async () => {
      const values = await page.locator("input.input").evaluateAll((inputs) => inputs.map((i) => (i as HTMLInputElement).value));
      expect(values).toContain(actionTypeName);
    }).toPass();

    // --- Standards: create one.
    await page.getByRole("tab", { name: "Standards" }).click();
    await page.getByRole("button", { name: "New standard" }).click();
    await page.getByLabel("Standard reference").fill(reference);
    await page.getByLabel("Standard name").fill(standardName);
    await page.getByRole("dialog", { name: "New standard" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: reference })).toBeVisible();

    // --- Open it, create a draft version.
    await page.getByRole("button", { name: reference }).click();
    await expect(page.getByRole("dialog", { name: new RegExp(`${reference} `) })).toBeVisible();
    await page.getByRole("button", { name: "New version" }).click();
    await page.getByLabel("Version label").fill("v1.0");
    await page.getByRole("dialog", { name: "New version" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: "v1.0" })).toBeVisible();

    // --- Drill into the version workspace, add a requirement.
    await page.getByRole("button", { name: "v1.0" }).click();
    await expect(page.getByText("No requirements defined for this version yet.")).toBeVisible();
    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill("Access control policy");
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Access control policy")).toBeVisible();

    // --- Expand it and add a required action, using the action type created above.
    await page.getByRole("button", { name: "Expand Access control policy" }).click();
    await page.getByRole("button", { name: "Add required action" }).click();
    await page.getByLabel("Required action name").fill("Confirm policy reviewed annually");
    await page.getByLabel("Action type").selectOption({ label: actionTypeName });
    await page.getByRole("dialog", { name: "New required action" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Confirm policy reviewed annually")).toBeVisible();

    // --- Publish the version: requirements become immutable (§4).
    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("Published")).toBeVisible();
    await expect(page.getByRole("button", { name: "Add requirement" })).toHaveCount(0);
  });
});
