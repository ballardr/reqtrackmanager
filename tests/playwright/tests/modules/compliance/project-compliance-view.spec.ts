import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "../../e2e-workflows/helpers";
import { createStandardWithVersion, selectFilterOption } from "./helpers";

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
    const actionTypeName = `E2E PCV Action Type ${suffix}`;
    const requiredActionName = `E2E PCV Required Action ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    // --- An action type is needed for the required action below —
    // created first via org compliance settings, same flow
    // `compliance-standards-management.spec.ts` uses.
    // `exact: true`: Phase 35a's default tiles view renders every standard
    // as a card whose accessible name also contains the org name, so a
    // plain substring match on `ORG_NAMES.alpha` now also resolves to
    // every tile card, not just the "Compliance settings" link below.
    await page.goto("/standards");
    await page.getByRole("link", { name: ORG_NAMES.alpha, exact: true }).click();
    await expect(page).toHaveURL(/\/standards\/settings\/[^/]+$/);
    await page.getByPlaceholder("Action type name").fill(actionTypeName);
    await page.getByRole("button", { name: "Add action type" }).click();
    await expect(async () => {
      const values = await page.locator("input.input").evaluateAll((inputs) => inputs.map((i) => (i as HTMLInputElement).value));
      expect(values).toContain(actionTypeName);
    }).toPass();

    // --- Author a published standard/version/requirement to assign, via
    // the top-level `/standards` page (compliance-module-plan.md Phase 18 —
    // supersedes Phase 12's org-admin "Compliance" group entirely).
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await expect(page.getByRole("button", { name: "v1.0" })).toBeVisible();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill(requirementName);
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(requirementName)).toBeVisible();

    // --- Phase 32: give this requirement a required action, so the
    // project-side assessment panel's assignee field (a searchable
    // `AssigneePicker`, not a plain unfiltered `<select>`) has something to
    // exercise below.
    await page.getByRole("button", { name: `Expand ${requirementName}` }).click();
    await page.getByRole("button", { name: "Add required action" }).click();
    await page.getByLabel("Required action name").fill(requiredActionName);
    await page.getByLabel("Action type").selectOption({ label: actionTypeName });
    await page.getByRole("dialog", { name: "New required action" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(requiredActionName)).toBeVisible();

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

    // --- Phase 31: fresh assignment, zero assessments yet — the
    //     "Non-compliant" column must read "Unknown", never "No" (which
    //     would misleadingly imply this has been checked and found clean).
    const assignmentRow = page.getByRole("row", { name: new RegExp(reference) });
    await expect(assignmentRow.getByRole("cell", { name: "Unknown", exact: true })).toBeVisible();

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

    // --- Phase 32: the required action's assignee field is a searchable
    // `AssigneePicker`, not a plain unfiltered `<select>` — search narrows
    // to the matching org member, picking them persists it, and
    // "Unassign" clears it back to "Unassigned".
    const assigneeSearch = page.getByRole("combobox", { name: `Assignee for ${requiredActionName}` });
    await assigneeSearch.fill("Member AlphaBeta");
    await page.getByRole("option", { name: new RegExp(PERSONAS.memberAlphaBeta.name) }).click();
    await expect(page.getByText(new RegExp(PERSONAS.memberAlphaBeta.name))).toBeVisible();
    await page.getByRole("button", { name: `Unassign: Assignee for ${requiredActionName}` }).click();
    await expect(page.getByText(new RegExp(PERSONAS.memberAlphaBeta.name))).toHaveCount(0);

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

    // --- Phase 33: "Upload new evidence" creates a new evidence record,
    //     auto-links it to this requirement (no separate manual "link
    //     existing" step), then lets you attach the actual file to it —
    //     all without leaving this panel.
    const inlineEvidenceTitle = `E2E Inline Upload Evidence ${suffix}`;
    await page.getByRole("button", { name: "Upload new evidence" }).click();
    const createEvidenceDialog = page.getByRole("dialog", { name: "Add evidence" });
    await createEvidenceDialog.getByLabel("Evidence title").fill(inlineEvidenceTitle);
    await createEvidenceDialog.getByRole("button", { name: "Save" }).click();

    const attachFilesDialog = page.getByRole("dialog", { name: `Attach files to "${inlineEvidenceTitle}"` });
    await expect(attachFilesDialog).toBeVisible();
    await attachFilesDialog.locator('input[type="file"]').setInputFiles({
      name: "inline-evidence.txt", mimeType: "text/plain", buffer: Buffer.from("Playwright inline evidence upload test"),
    });
    await expect(attachFilesDialog.getByText("inline-evidence.txt")).toBeVisible();
    await attachFilesDialog.getByRole("button", { name: "Done" }).click();

    // Linked immediately — no manual "link existing" step needed for it.
    await expect(page.getByRole("button", { name: `Unlink ${inlineEvidenceTitle}` })).toBeVisible();

    // And visible in the project's own Evidence library too.
    await page.getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "← Back" }).click();
    await page.getByRole("tab", { name: "Evidence" }).click();
    await expect(page.getByText(inlineEvidenceTitle)).toBeVisible();
  });

  /**
   * Phase 40 (docs/compliance-module-plan.md) — parity with the org-level
   * "Outstanding compliance items" filters (`org-compliance-view.spec.ts`),
   * minus a Project filter (this tab is already scoped to one project).
   * Same fixture shape: one top-level requirement ("section") with a
   * child, the child assessed Non-Compliant, confirming the sub-section
   * filter (derived from `parent_requirement_id`, since there is no
   * dedicated "section" field) narrows the Outstanding tab's Non-compliant
   * list correctly.
   */
  test("the project Outstanding tab's Standard/Standard version/Sub-section filters narrow rows", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-PCV-FILTER-${suffix}`;
    const standardName = `E2E Project Outstanding Filter Standard ${suffix}`;
    const sectionAName = `E2E PCV Section A ${suffix}`;
    const sectionBName = `E2E PCV Section B ${suffix}`;
    const childRequirementName = `E2E PCV Child Requirement ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await expect(page.getByRole("button", { name: "v1.0" })).toBeVisible();
    await page.getByRole("button", { name: "v1.0" }).click();

    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill(sectionAName);
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(sectionAName)).toBeVisible();

    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill(sectionBName);
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(sectionBName)).toBeVisible();

    await page.getByRole("button", { name: `Add child requirement under ${sectionAName}` }).click();
    await page.getByLabel("Requirement name").fill(childRequirementName);
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(childRequirementName)).toBeVisible();

    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("Published")).toBeVisible();

    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.alpha1 }).click();
    await page.getByRole("link", { name: "Compliance", exact: true }).click();
    await page.getByRole("button", { name: "Assign standard" }).click();
    const assignDialog = page.getByRole("dialog", { name: "Assign compliance standard" });
    await assignDialog.getByLabel("Standard", { exact: true }).selectOption({ label: `${reference} — ${standardName}` });
    await assignDialog.getByLabel("Standard version").selectOption({ label: "v1.0" });
    await assignDialog.getByRole("button", { name: "Assign" }).click();
    await expect(page.getByText(new RegExp(reference))).toBeVisible();

    await page.getByText(new RegExp(reference)).click();
    await page.getByText(childRequirementName).click();
    await page.getByLabel("Compliance status", { exact: true }).selectOption({ label: "Non-compliant" });
    await page.getByLabel("Justification (required)").fill("Failed the required E2E filter-fixture inspection.");
    await page.getByRole("button", { name: "Update assessment" }).click();
    await expect(page.getByText("Current state: Assessed")).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "← Back" }).click();

    await page.getByRole("tab", { name: "Outstanding" }).click();
    await expect(page.getByText(childRequirementName)).toBeVisible();

    await selectFilterOption(page, "Standard", `${reference} — ${standardName}`);
    await expect(page.getByText("Sub-section", { exact: true })).toBeVisible();

    await selectFilterOption(page, "Sub-section", sectionBName);
    await expect(page.getByText(childRequirementName)).toHaveCount(0);
    await selectFilterOption(page, "Sub-section", sectionAName);
    await expect(page.getByText(childRequirementName)).toBeVisible();
  });
});
