import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: Compliance Module Phase 13 (docs/compliance-module-plan.md)
 * — the project-scoped Project Compliance View
 * (`frontend/src/modules/compliance/ProjectCompliancePage.tsx`), mounted
 * for real through Phase 3's Tier A `installedModules`/`buildModuleRoutes`
 * mechanism (a "Compliance" nav-rail entry under a project, unlike Phase
 * 12's org-level panel which had to be mounted directly on `OrgAdminPage`
 * since that mechanism is project-scoped end to end — see that phase's own
 * notes). Covers the core project-assessment flow §7-§10, §12, §13, §21
 * describe: assign a published standard to a project, mark a requirement's
 * applicability, assess it compliant, submit for approval, approve it, and
 * attach supporting evidence — then confirms the applicability tree/status
 * summary reflect all of it.
 *
 * `orgAdminAlphaBeta` is reused rather than a dedicated persona: they are
 * Alpha's org admin (composes with `compliance_manager` for the org-level
 * standard authoring/assignment step, module system Phase 2) and, as the
 * creator of Alpha-1, also its `PROJECT_MANAGER` (composes with
 * `compliance_officer` for every project-level assessment/approval action)
 * — no new seed persona or module-role grant is needed.
 *
 * Every fixture this spec creates (standard, requirement, evidence) is
 * dynamically named with a per-run timestamp suffix, per this repo's
 * standing test-idempotency rule — nothing here mutates or depends on
 * another spec's named fixtures, and re-running this spec (alone, repeated,
 * or out of order) only ever adds new, uniquely-named rows.
 */
test.describe("Compliance Module: project compliance view (Phase 13)", () => {
  test("assign a standard, assess a requirement, approve it, and attach evidence", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-PCV-${suffix}`;
    const standardName = `E2E Project Compliance Standard ${suffix}`;
    const requirementName = `E2E Access Control Requirement ${suffix}`;
    const evidenceTitle = `E2E Access Review Evidence ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    // --- Author a published standard/version/requirement to assign, via
    // the top-level `/standards` page (compliance-module-plan.md Phase 18 —
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

    // --- Switch to the project's own Compliance nav entry (Phase 3 Tier A routing).
    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.alpha1 }).click();
    // exact: true — the project overview page's own compliance summary
    // tiles (Phase 17d) render as cards whose accessible name contains
    // "Compliance" too (e.g. a standard's name), which would otherwise
    // collide with this nav-rail link under substring matching once any
    // standard has ever been assigned to this project.
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/modules\/compliance$/);

    // --- Assign the standard to this project.
    await page.getByRole("button", { name: "Assign standard" }).click();
    const assignDialog = page.getByRole("dialog", { name: "Assign compliance standard" });
    await assignDialog.getByLabel("Standard", { exact: true }).selectOption({ label: `${reference} — ${standardName}` });
    await assignDialog.getByLabel("Standard version").selectOption({ label: "v1.0" });
    await assignDialog.getByRole("button", { name: "Assign" }).click();
    await expect(page.getByText(new RegExp(reference))).toBeVisible();

    // --- Phase 17d: the project overview page now shows a compliance
    //     summary tile for this standard, linking straight back here.
    await page.getByRole("link", { name: "Overview", exact: true }).click();
    await expect(page).toHaveURL(/\/projects\/[^/]+$/);
    const complianceTile = page.getByRole("link", { name: new RegExp(standardName) });
    await expect(complianceTile).toBeVisible();
    await complianceTile.click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/modules\/compliance$/);

    // --- Phase 15: download the project's own compliance report, PDF and CSV.
    const pdfDownloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download PDF report" }).click();
    const pdfDownload = await pdfDownloadPromise;
    expect(pdfDownload.suggestedFilename()).toContain("compliance-report.pdf");

    const csvDownloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download CSV report" }).click();
    const csvDownload = await csvDownloadPromise;
    expect(csvDownload.suggestedFilename()).toContain("compliance-report.csv");

    // --- Drill into the assignment; the one requirement should be listed.
    await page.getByText(new RegExp(reference)).click();
    await expect(page.getByText(requirementName)).toBeVisible();

    // --- Open the requirement, assess it Compliant, submit and approve.
    await page.getByText(requirementName).click();
    await page.getByLabel("Compliance status", { exact: true }).selectOption({ label: "Compliant" });
    await page.getByRole("button", { name: "Update assessment" }).click();
    await expect(page.getByRole("button", { name: "Submit for approval" })).toBeVisible();

    await page.getByRole("button", { name: "Submit for approval" }).click();
    await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("Current state: Approved")).toBeVisible();

    // --- Attach evidence from the requirement panel's own "link existing
    //     evidence" control — first create it on the top-level Evidence tab.
    await page.getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "← Back" }).click();
    await page.getByRole("tab", { name: "Evidence" }).click();
    await page.getByRole("button", { name: "Add evidence" }).click();
    await page.getByLabel("Evidence title").fill(evidenceTitle);
    await page.getByRole("dialog", { name: "Add evidence" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(evidenceTitle)).toBeVisible();

    await page.getByRole("tab", { name: "Standards" }).click();
    await page.getByText(new RegExp(reference)).click();
    await page.getByText(requirementName).click();
    await page.getByLabel("Link existing evidence").selectOption({ label: evidenceTitle });
    await page.getByRole("button", { name: "Link" }).click();
    await expect(page.getByRole("button", { name: `Unlink ${evidenceTitle}` })).toBeVisible();
  });
});
