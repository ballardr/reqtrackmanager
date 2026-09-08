import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: Compliance Module Phase 18 (docs/compliance-module-plan.md)
 * — "Compliance Standards" promoted from three clicks deep inside Org Admin
 * to its own top-level, cross-org nav-rail tab. Covers:
 *
 * - Tab visibility: absent for a plain member with no relevant role and no
 *   standards in any org they belong to, present once granted.
 * - One-step standard+version creation from the new `/standards` page.
 * - Standard workspace navigation (Overview/Details, Versions, History) —
 *   the "Standard" nav-rail section, a sibling structural pattern to
 *   "Project."
 * - Org compliance settings (`/standards/settings/:orgId`, Action types /
 *   Mapping types via `ResourceMenu`) — supersedes Phase 12's org-admin
 *   "Compliance" group entirely (`ComplianceAdminPanel.tsx`, now deleted).
 *
 * `orgAdminAlphaBeta` is used rather than a dedicated `compliance_manager`
 * persona — `require_module_role("compliance", "compliance_manager")`
 * composes with `OrgRole.ORG_ADMIN` by design (module system Phase 2), and
 * this persona is already seeded as Alpha's (and Beta's) org admin
 * (`backend/scripts/seed_e2e_dataset.py`), so no new seed persona or
 * module-role grant is needed for this spec specifically. Because this
 * persona manages *two* orgs, the "New standard" dialog exercises its own
 * organisation picker (`StandardFormModal.tsx`), not just the single-org
 * path.
 *
 * Every fixture this spec creates (standard, action type) is dynamically
 * named with a per-run timestamp suffix, per this repo's standing test-
 * idempotency rule — nothing here mutates or depends on another spec's
 * named fixtures, and re-running this spec (alone, repeated, or out of
 * order) only ever adds new, uniquely-named rows rather than colliding with
 * a previous run's.
 */
test.describe("Compliance Module: \"Compliance Standards\" top-level nav-rail tab (Phase 18)", () => {
  test("tab is hidden for a user with no org memberships, and visible for a compliance manager", async ({ page }) => {
    // `orphan` has zero org memberships at all (seed_e2e_dataset.py — left
    // Alpha via self-service for the user-directory/ban workflow), so
    // `GET /api/v1/compliance/nav-visibility` is vacuously `false` for
    // them regardless of how many standards Alpha/Beta accumulate across
    // this suite's own runs. `memberAlphaBeta` (a genuine plain member of
    // both orgs) is deliberately *not* used here instead: this spec's own
    // "create a standard" test below adds a standard to Alpha every run,
    // which would flip a plain Alpha member's own visibility to `true` via
    // the "org has ≥1 non-archived standard" branch — an assertion against
    // a shared, cross-spec org's *content* would be flaky by construction.
    await loginAs(page, PERSONAS.orphan.email);
    await expect(page.getByRole("link", { name: "Compliance Standards" })).toHaveCount(0);

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await expect(page.getByRole("link", { name: "Compliance Standards" })).toBeVisible();
  });

  test("create a standard+version, navigate the workspace, author a requirement, and publish", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-${suffix}`;
    const standardName = `E2E Compliance Standard ${suffix}`;
    const actionTypeName = `E2E Evidence Review ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    // --- Org compliance settings: create an action type, needed for the
    // required action below (`/standards/settings/:orgId`, superseding the
    // old org-admin "Compliance" -> "Action types" tab).
    await page.goto("/standards");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/standards\/settings\/[^/]+$/);
    await page.getByPlaceholder("Action type name").fill(actionTypeName);
    await page.getByRole("button", { name: "Add action type" }).click();
    await expect(async () => {
      const values = await page.locator("input.input").evaluateAll((inputs) => inputs.map((i) => (i as HTMLInputElement).value));
      expect(values).toContain(actionTypeName);
    }).toPass();

    // --- The settings page's own `ResourceMenu` navigation between its two
    // groups — Mapping types is unaffected by anything created above.
    await page.getByRole("link", { name: "Mapping types" }).click();
    await expect(page).toHaveURL(/\/standards\/settings\/[^/]+\/mappingTypes$/);
    await page.getByRole("link", { name: "Action types" }).click();
    await expect(page).toHaveURL(/\/standards\/settings\/[^/]+\/actionTypes$/);

    // --- Standards: create one, with its mandatory first (draft) version,
    // in the single combined "New standard" dialog — a standard is never
    // left with zero versions. `orgAdminAlphaBeta` manages two orgs, so this
    // exercises the dialog's own organisation picker.
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    // --- Standard workspace navigation: Overview (landed here already) ->
    // Versions -> drill into v1.0.
    await page.getByRole("link", { name: "Versions" }).click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/versions$/);
    await expect(page.getByRole("button", { name: "v1.0" })).toBeVisible();
    await page.getByRole("button", { name: "v1.0" }).click();

    // --- Add a requirement, expand it, add a required action using the
    // action type created above.
    await expect(page.getByText("No requirements defined for this version yet.")).toBeVisible();
    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill("Access control policy");
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Access control policy")).toBeVisible();

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

    // --- History section shows this standard's own audit trail.
    await page.getByRole("link", { name: "History" }).click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/history$/);
    await expect(page.getByRole("listitem").filter({ hasText: "created" })).toBeVisible();
  });
});
