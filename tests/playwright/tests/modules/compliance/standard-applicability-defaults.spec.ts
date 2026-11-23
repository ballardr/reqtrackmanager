import { expect, test } from "@playwright/test";

import { loginAs, logout, openProject, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: "Standard Applicability Defaults, Exceptions, and Project-Manager Assignment." Two scenarios:
 *
 * 1. A plain Project Manager with no `compliance_officer` grant assigns a published standard to their own
 *    project from `ProjectCompliancePage.tsx`'s "Assign standard" flow (persona `e2e-projectmgr-g@example.com`,
 *    `PROJECT_MANAGER` on Gamma-1 alone).
 * 2. A Compliance Manager (Gamma's org admin `e2e-orgadmin-g@example.com`, through `require_module_role`'s
 *    org-admin composition) switches a standard to "applies to all projects by default", sees it materialise
 *    onto every current project, then excepts one project, which archives (not deletes) its assignment.
 *
 * Every fixture standard carries a per-run timestamp suffix.
 */
test.describe("Compliance Module: standard applicability defaults", () => {
  test("a plain Project Manager can self-assign a published standard without a compliance_officer grant", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-PM-SELF-${suffix}`;
    const standardName = `E2E PM Self-Service Standard ${suffix}`;

    // --- Author + publish the standard as Gamma's org admin (Compliance
    // Manager access via the existing org-admin override).
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.gamma, reference, name: standardName, versionLabel: "v1.0" });
    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("Published", { exact: true })).toBeVisible();
    await logout(page);

    // --- A plain Project Manager on Gamma-1 alone — no org role, no
    // compliance_officer grant — self-assigns the standard directly.
    await loginAs(page, PERSONAS.projectMgrGamma.email);
    await page.goto("/projects");
    // `.first()`: Gamma-1 is a hierarchy `can_be_parent` fixture that other specs create and detach sub-projects
    // under concurrently (see playwright.config.ts's GLOBAL_STATE_SPECS comment on project-hierarchy.spec.ts),
    // so its row can transiently render more than one element with this accessible name, all for the same project.
    await openProject(page, PROJECT_NAMES.gamma1);
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
    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("Published", { exact: true })).toBeVisible();

    // --- Before switching the default, Gamma-2 has no such assignment.
    await page.goto("/projects");
    await openProject(page, PROJECT_NAMES.gamma2);
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await expect(page.getByText(new RegExp(reference))).not.toBeVisible();

    // Switch the standard's applicability default; reconciliation materialises an assignment for every current
    // project in the org with no manual per-project action. The control is a `link`, not a `button`, because
    // `/standards` defaults to its tiles view, whose cards are `<Link>`s.
    await page.goto("/standards");
    await page.getByRole("link", { name: new RegExp(reference) }).click();
    await expect(page.getByRole("switch", { name: "Applies to all projects by default" })).toHaveAttribute("aria-checked", "false");
    await page.getByRole("switch", { name: "Applies to all projects by default" }).click();
    await expect(page.getByRole("switch", { name: "Applies to all projects by default" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByText("No projects are excluded")).toBeVisible();

    await page.goto("/projects");
    await openProject(page, PROJECT_NAMES.gamma2);
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await expect(page.getByText(new RegExp(reference))).toBeVisible();

    // Gamma-1 was reconciled too (not just Gamma-2), confirmed before excluding it below so the exclusion is
    // a change from a reconciled state, not a no-op.
    await page.goto("/projects");
    await openProject(page, PROJECT_NAMES.gamma1);
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await expect(page.getByText(new RegExp(reference))).toBeVisible();

    // --- Except Gamma-1 back out — its reconciled assignment archives,
    // never deletes, preserving whatever history it may have accrued.
    await page.goto("/standards");
    await page.getByRole("link", { name: new RegExp(reference) }).click();
    await page.getByRole("button", { name: "Exclude a project" }).click();
    const excludeDialog = page.getByRole("dialog", { name: "Exclude a project" });
    await excludeDialog.getByLabel("Project").selectOption({ label: PROJECT_NAMES.gamma1 });
    await excludeDialog.getByLabel("Reason", { exact: true }).fill("Already governed by a separate local standard.");
    await excludeDialog.getByRole("button", { name: "Exclude" }).click();
    // Exact, and not the Exclude dialog's own <option>s (a merge-import can
    // add a "Gamma-1 … (imported)" project alongside).
    await expect(page.getByText(PROJECT_NAMES.gamma1, { exact: true }).filter({ visible: true }).first()).toBeVisible();
    await expect(page.getByText("Already governed by a separate local standard.")).toBeVisible();

    await page.goto("/projects");
    await openProject(page, PROJECT_NAMES.gamma1);
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    // An archived assignment's row renders "—" for its Standard column (`GET .../status` excludes archived
    // assignments, per `ProjectCompliancePage.tsx`), so the reference text of the active row is absent from
    // the page: the observable signal that the exclusion took effect, beside the direct confirmation above.
    await expect(page.getByText(new RegExp(reference))).not.toBeVisible();
  });
});
