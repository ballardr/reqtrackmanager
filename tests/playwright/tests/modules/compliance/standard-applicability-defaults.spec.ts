import { expect, test } from "@playwright/test";

import { loginAs, logout, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: Compliance Module Phase 20 (docs/compliance-module-plan.md)
 * — "Standard Applicability Defaults, Exceptions, and Project-Manager
 * Assignment." Two independent scenarios:
 *
 * 1. The *default, primary* assignment path: a plain Project Manager, with
 *    no `compliance_officer` module-role grant at all, can assign a
 *    published standard to their own project directly from `Project
 *    CompliancePage.tsx`'s existing "Assign standard" flow — no Compliance
 *    Manager needs to act on their behalf first.
 * 2. The *secondary*, org-wide-mandate path: a Compliance Manager (here,
 *    via the org-admin override) can switch a standard to "applies to all
 *    projects by default," watch it materialise onto every current project
 *    in the org without any manual per-project assignment, then except one
 *    project back out — which archives (not deletes) the assignment
 *    reconciliation had created for it.
 *
 * `e2e-projectmgr-g@example.com` (Gamma, member-only, `PROJECT_MANAGER` on
 * Gamma-1 alone) is the persona proving scenario 1 has no dependency on any
 * compliance-specific role grant. `e2e-orgadmin-g@example.com` (Gamma's own
 * org admin) proves scenario 2 — org admins retain full Compliance Manager
 * access via `require_module_role`'s existing composition, and, per this
 * app's project-view rules, can also open Gamma-1/Gamma-2's own Compliance
 * pages to observe reconciliation without needing a project role there.
 *
 * Every fixture standard this spec creates is dynamically named with a
 * per-run timestamp suffix, per this repo's standing test-idempotency rule.
 */
test.describe("Compliance Module: standard applicability defaults (Phase 20)", () => {
  test("a plain Project Manager can self-assign a published standard without a compliance_officer grant", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-PM-SELF-${suffix}`;
    const standardName = `E2E PM Self-Service Standard ${suffix}`;

    // --- Author + publish the standard as Gamma's org admin (Compliance
    // Manager access via the existing org-admin override).
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.gamma, reference, name: standardName, versionLabel: "v1.0" });
    await page.getByRole("link", { name: "Versions" }).click();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("Published")).toBeVisible();
    await logout(page);

    // --- A plain Project Manager on Gamma-1 alone — no org role, no
    // compliance_officer grant — self-assigns the standard directly.
    await loginAs(page, PERSONAS.projectMgrGamma.email);
    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.gamma1 }).click();
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/modules\/compliance$/);

    await page.getByRole("button", { name: "Assign standard" }).click();
    const assignDialog = page.getByRole("dialog", { name: "Assign compliance standard" });
    await assignDialog.getByLabel("Standard", { exact: true }).selectOption({ label: `${reference} — ${standardName}` });
    await assignDialog.getByLabel("Standard version").selectOption({ label: "v1.0" });
    await assignDialog.getByRole("button", { name: "Assign" }).click();
    await expect(page.getByText(new RegExp(reference))).toBeVisible();
  });

  test("a Compliance Manager can make a standard apply to all projects by default, then except one back out", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-APPLIES-ALL-${suffix}`;
    const standardName = `E2E Applies-To-All Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.gamma, reference, name: standardName, versionLabel: "v1.0" });
    await page.getByRole("link", { name: "Versions" }).click();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("Published")).toBeVisible();

    // --- Before switching the default, Gamma-2 has no such assignment.
    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.gamma2 }).click();
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await expect(page.getByText(new RegExp(reference))).not.toBeVisible();

    // --- Switch the standard's applicability default; reconciliation
    // should materialise a real assignment for every current project in
    // the org, with no manual per-project action.
    await page.goto("/standards");
    await page.getByRole("button", { name: reference }).click();
    await expect(page.getByRole("switch", { name: "Applies to all projects by default" })).toHaveAttribute("aria-checked", "false");
    await page.getByRole("switch", { name: "Applies to all projects by default" }).click();
    await expect(page.getByRole("switch", { name: "Applies to all projects by default" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByText("No projects are excluded")).toBeVisible();

    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.gamma2 }).click();
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await expect(page.getByText(new RegExp(reference))).toBeVisible();

    // --- Gamma-1 was reconciled too (not just Gamma-2) — confirmed before
    // excluding it below, so that exclusion's own effect is provably a
    // change from an actually-reconciled state, not a no-op against a
    // project reconciliation never reached.
    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.gamma1 }).click();
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await expect(page.getByText(new RegExp(reference))).toBeVisible();

    // --- Except Gamma-1 back out — its reconciled assignment archives,
    // never deletes, preserving whatever history it may have accrued.
    await page.goto("/standards");
    await page.getByRole("button", { name: reference }).click();
    await page.getByRole("button", { name: "Exclude a project" }).click();
    const excludeDialog = page.getByRole("dialog", { name: "Exclude a project" });
    await excludeDialog.getByLabel("Project").selectOption({ label: PROJECT_NAMES.gamma1 });
    await excludeDialog.getByLabel("Reason (required)").fill("Already governed by a separate local standard.");
    await excludeDialog.getByRole("button", { name: "Exclude" }).click();
    await expect(page.getByText(PROJECT_NAMES.gamma1)).toBeVisible();
    await expect(page.getByText("Already governed by a separate local standard.")).toBeVisible();

    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.gamma1 }).click();
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    // An archived assignment's row deliberately renders "—" for its
    // Standard column (`GET .../status` excludes archived assignments by
    // design, per `ProjectCompliancePage.tsx`'s own Phase 13 notes — there
    // is no per-project-compliance-row reference/name join on this list
    // view once archived), so the reference text this standard's active
    // row displayed a moment ago is gone from the page entirely — the
    // observable signal that the exclusion took effect, combined with the
    // exclusion already having been confirmed directly above.
    await expect(page.getByText(new RegExp(reference))).not.toBeVisible();
  });
});
