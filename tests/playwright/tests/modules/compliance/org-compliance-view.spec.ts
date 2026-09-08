import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: Compliance Module Phase 14 (docs/compliance-module-plan.md)
 * — the org-level Organisation Compliance View + Dashboard (§22/§23),
 * mounted as a new flat top-level `OrgAdminPage` resource-menu group
 * ("Compliance overview", `/orgs/:orgId/admin/compliance-overview`)
 * alongside Phase 12's own "Compliance" (standards management) group — see
 * `frontend/src/modules/compliance/OrgCompliancePanel.tsx`'s own docstring
 * for why this is a separate group rather than a fourth tab on that panel.
 *
 * Covers the read/drill-down path: author and publish a standard (Phase 12
 * UI), assign it to a project and assess a requirement Non-Compliant
 * (Phase 13 UI), then confirm the org-wide Dashboard, "Compliance by
 * standard" table (with its project filter), and "Outstanding" tab all
 * surface that project/requirement, and that the standard table's
 * drill-down link actually opens the underlying project's own Compliance
 * page.
 *
 * `orgAdminAlphaBeta` is reused rather than a dedicated persona, the same
 * way `project-compliance-view.spec.ts` (Phase 13) does — Alpha's org
 * admin composes with `compliance_manager` for both the org-level
 * authoring/assignment steps and the Phase 14 `_require_manage`-gated
 * dashboard endpoints, and is Alpha-1's own `PROJECT_MANAGER`/
 * `compliance_officer` for the assessment step.
 *
 * Every fixture this spec creates (standard, requirement) is dynamically
 * named with a per-run timestamp suffix, per this repo's standing test-
 * idempotency rule — assertions on the org-wide table/dashboard look for
 * this spec's own dynamically-named rows among whatever else may be
 * present, never an exact total count, since other specs' own fixtures
 * may coexist in the same organisation.
 */
test.describe("Compliance Module: org compliance view + dashboard (Phase 14)", () => {
  test("a non-compliant assessment surfaces on the org-wide dashboard, standards table, and outstanding tab", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-ORG-${suffix}`;
    const standardName = `E2E Org Dashboard Standard ${suffix}`;
    const requirementName = `E2E Org Dashboard Requirement ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    // --- Author + publish a standard/version/requirement, via the
    // top-level `/standards` page (compliance-module-plan.md Phase 18 —
    // supersedes Phase 12's org-admin "Compliance" group entirely).
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    await page.getByRole("link", { name: "Versions" }).click();
    await expect(page.getByRole("button", { name: "v1.0" })).toBeVisible();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill(requirementName);
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(requirementName)).toBeVisible();

    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("Published")).toBeVisible();

    // --- Assign to Alpha-1 and assess the one requirement Non-Compliant.
    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.alpha1 }).click();
    // exact: true — the project overview page's own compliance summary
    // tiles (Phase 17d) render as cards whose accessible name contains
    // "Compliance" too (e.g. a standard's name), which would otherwise
    // collide with this nav-rail link under substring matching once any
    // standard has ever been assigned to this project.
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/modules\/compliance$/);

    await page.getByRole("button", { name: "Assign standard" }).click();
    const assignDialog = page.getByRole("dialog", { name: "Assign compliance standard" });
    await assignDialog.getByLabel("Standard", { exact: true }).selectOption({ label: `${reference} — ${standardName}` });
    await assignDialog.getByLabel("Standard version").selectOption({ label: "v1.0" });
    await assignDialog.getByRole("button", { name: "Assign" }).click();
    await expect(page.getByText(new RegExp(reference))).toBeVisible();

    await page.getByText(new RegExp(reference)).click();
    await page.getByText(requirementName).click();
    await page.getByLabel("Compliance status", { exact: true }).selectOption({ label: "Non-compliant" });
    await page.getByLabel("Justification (required)").fill("Failed the required E2E inspection.");
    await page.getByRole("button", { name: "Update assessment" }).click();
    await expect(page.getByText("Current state: Assessed")).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();

    // --- Org-wide Dashboard: the non-compliant project is listed.
    await page.goto("/orgs");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await selectOrgAdminGroup(page, "Compliance overview");
    await expect(page.getByText("Active compliance standards")).toBeVisible();
    await expect(page.getByText("Non-compliant projects")).toBeVisible();
    const nonCompliantCard = page.locator("div.card", { hasText: "Non-compliant projects" });
    await expect(nonCompliantCard.getByRole("link", { name: PROJECT_NAMES.alpha1 })).toBeVisible();

    // --- Phase 15: download the organisation-wide compliance report.
    const pdfDownloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download PDF report" }).click();
    const pdfDownload = await pdfDownloadPromise;
    expect(pdfDownload.suggestedFilename()).toContain("compliance-report.pdf");

    // --- "Compliance by standard" table: the standard groups the project,
    //     and drilling down opens the project's own Compliance page.
    await page.getByRole("tab", { name: "Compliance by standard" }).click();
    const expandButton = page.getByRole("button", { name: new RegExp(`Expand projects for ${reference}`) });
    await expect(expandButton).toBeVisible();
    await expandButton.click();
    const projectLink = page.getByRole("link", { name: PROJECT_NAMES.alpha1 });
    await expect(projectLink).toBeVisible();
    await projectLink.click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/modules\/compliance$/);

    // --- Outstanding tab: the non-compliant requirement is listed, tagged
    //     with the project it belongs to.
    await page.goto("/orgs");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await selectOrgAdminGroup(page, "Compliance overview");
    await page.getByRole("tab", { name: "Outstanding" }).click();
    await expect(page.getByText(requirementName)).toBeVisible();
    await expect(page.getByRole("link", { name: PROJECT_NAMES.alpha1 }).first()).toBeVisible();
  });
});
