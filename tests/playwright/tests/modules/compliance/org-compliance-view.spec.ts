import { expect, test } from "@playwright/test";

import { expectTidyStatBlocks, loginAs, openProject, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "../../e2e-workflows/helpers";
import { createStandardWithVersion, openComplianceStatusTab, selectFilterOption } from "./helpers";

/**
 * Job to be done: the org-level Organisation Compliance View + Dashboard (§22/§23): the compliance summary is a
 * widget on the Organisation Overview dashboard (`OrgComplianceWidgets.tsx`, no tab click needed), and "By
 * standard" / "Outstanding" are tabs of the Standards page (`/standards/by-standard`, `/standards/outstanding`;
 * see `ComplianceStatusPage.tsx`). Covers the drill-down path: publish a standard, assign it to a project,
 * assess a requirement Non-Compliant, then confirm the gauges, Dashboard tab, By standard table (with its
 * project filter) and Outstanding tab surface it and the drill-down link opens the project's Compliance page.
 *
 * `orgAdminAlphaBeta` is reused, as in `project-compliance-view.spec.ts` (`compliance_manager` through the org
 * admin, `PROJECT_MANAGER`/`compliance_officer` on Alpha-1). Fixtures carry a per-run timestamp suffix and
 * assertions look for this spec's own rows, never an exact total.
 */
test.describe("Compliance Module: org compliance view + dashboard", () => {
  test("a non-compliant assessment surfaces on the org-wide dashboard, standards table, and outstanding tab", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-ORG-${suffix}`;
    const standardName = `E2E Org Dashboard Standard ${suffix}`;
    const requirementName = `E2E Org Dashboard Requirement ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    // --- Author + publish a standard/version/requirement, via the
    // top-level `/standards` page (replaces the
    // old org-admin "Compliance" group entirely).
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await expect(page.getByRole("button", { name: "v1.0" })).toBeVisible();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill(requirementName);
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(requirementName)).toBeVisible();

    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    // The exact toast text, not a bare "Published" substring: once a standard has more than one version, an
    // earlier version's nav-rail "Versions" entry also reads "v1.0 (Published)".
    await expect(page.getByText("Version published.")).toBeVisible();

    // --- Assign to Alpha-1 and assess the one requirement Non-Compliant.
    await page.goto("/projects");
    await openProject(page, PROJECT_NAMES.alpha1);
    // exact: true: the project overview's compliance summary tiles are cards whose accessible name contains
    // "Compliance" (a standard's name), which would collide with this nav-rail link under substring matching.
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
    await page.getByLabel("Justification", { exact: true }).fill("Failed the required E2E inspection.");
    await page.getByRole("button", { name: "Update assessment" }).click();
    await expect(page.getByText("Current state: Assessed")).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();

    // --- the compliance summary is a widget on the Organisation Overview's built-in dashboard (Compliance is enabled
    //     for the organisation, so the built-in layout includes it): no group click needed.
    await page.goto("/org-overview");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page.getByText("Active compliance standards")).toBeVisible();
    await expect(page.getByText("Overall compliance", { exact: true })).toBeVisible();

    // Compliance summary widget: the non-compliant project count is a headline tile that drills through to the
    // By standard tab, pre-filtered and pre-pivoted to the projects it counted.
    const nonCompliantTile = page.getByRole("link", { name: /Non-compliant projects/ });
    await expect(nonCompliantTile).toBeVisible();
    await nonCompliantTile.click();
    await expect(page).toHaveURL(/\/standards\/by-standard\?org=[^&]+&groupBy=project&state=non_compliant/);
    const expandProjectButton = page.getByRole("button", { name: `Expand standards for ${PROJECT_NAMES.alpha1}`, exact: true });
    await expect(expandProjectButton).toBeVisible();
    await expandProjectButton.click();
    // `getByText` alone would also match this standard's own <option> in the
    // "Standard"/"Standard version" filter selects — scope to the expanded
    // row's own link.
    await expect(page.getByRole("link", { name: new RegExp(reference) })).toBeVisible();

    // --- download the organisation-wide compliance report,
    //     behind the "Export" popover trigger (Principle 11), in the title row of the status tabs.
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const pdfDownloadPromise = page.waitForEvent("download");
    await page.getByRole("menuitem", { name: "Download PDF report" }).click();
    const pdfDownload = await pdfDownloadPromise;
    expect(pdfDownload.suggestedFilename()).toContain("compliance-by-standard-report.pdf");

    // --- By standard tab: the standard groups the project, and drilling down opens the project's own Compliance
    //     page. The tab is already open from the export step, with the project pivot the summary tile linked to, so
    //     open it afresh from the Standards page.
    await openComplianceStatusTab(page, "By standard", ORG_NAMES.alpha);

    // This panel's Export trigger carries its active Standard filter as a query parameter, as the Outstanding
    // tab does (covered in the filter test below).
    await selectFilterOption(page, "Standard", `${reference} — ${standardName}`);
    const standardsReportRequestPromise = page.waitForRequest(
      (req) => req.url().includes("/modules/compliance/reports") && req.url().includes("format=csv") && req.url().includes("standard_id=")
    );
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await page.getByRole("dialog", { name: "Export" }).getByRole("menuitem", { name: "Download CSV report" }).click();
    await standardsReportRequestPromise;
    await selectFilterOption(page, "Standard", "All standards");

    const expandButton = page.getByRole("button", { name: new RegExp(`Expand projects for ${reference}`) });
    await expect(expandButton).toBeVisible();
    await expandButton.click();
    const projectLink = page.getByRole("link", { name: PROJECT_NAMES.alpha1 });
    await expect(projectLink).toBeVisible();
    await projectLink.click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/modules\/compliance$/);

    // --- Outstanding tab: the non-compliant requirement is listed,
    //     tagged with the project it belongs to.
    await openComplianceStatusTab(page, "Outstanding", ORG_NAMES.alpha);
    await expect(page.getByText(requirementName)).toBeVisible();
    await expect(page.getByRole("link", { name: PROJECT_NAMES.alpha1 }).first()).toBeVisible();
  });

  /**
   * The By standard tab's default (group-by-standard) expanded row groups its projects by `standard_version_id`
   * first, each version's projects one level deeper. A version with more than one sibling is a collapsible
   * sub-group (with a single version the sub-group pre-expands with no toggle, as the first test shows).
   * Covers a standard with two published versions assigned to two projects: each version's sub-group lists
   * only its own project, and a project link inside the nested structure still navigates.
   */
  test("a standard on two versions groups its expanded row as Standard -> Version -> Project", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-ORG-NEST-${suffix}`;
    const standardName = `E2E Org Nesting Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });
    const standardId = new URL(page.url()).pathname.split("/").pop()!;

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await expect(page.getByRole("button", { name: "v1.0" })).toBeVisible();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    // The exact toast text, not a bare "Published" substring: once a standard has more than one version, an
    // earlier version's nav-rail "Versions" entry also reads "v1.0 (Published)".
    await expect(page.getByText("Version published.")).toBeVisible();

    // A second published version, so the standard has two to assign.
    await page.goto(`/standards/${standardId}/versions`);
    await page.getByRole("button", { name: "New version" }).click();
    await page.getByLabel("Version label").fill("v2.0");
    await page.getByRole("dialog", { name: "New version" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: "v2.0" })).toBeVisible();
    await page.getByRole("button", { name: "v2.0" }).click();
    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    // The exact toast text, not a bare "Published" substring: once a standard has more than one version, an
    // earlier version's nav-rail "Versions" entry also reads "v1.0 (Published)".
    await expect(page.getByText("Version published.")).toBeVisible();

    async function assignStandard(projectName: string, versionLabel: string) {
      await openProject(page, projectName);
      await page.getByRole("link", { name: "Compliance", exact: true }).click();
      await page.getByRole("button", { name: "Assign standard" }).click();
      const dialog = page.getByRole("dialog", { name: "Assign compliance standard" });
      await dialog.getByLabel("Standard", { exact: true }).selectOption({ label: `${reference} — ${standardName}` });
      await dialog.getByLabel("Standard version").selectOption({ label: versionLabel });
      await dialog.getByRole("button", { name: "Assign" }).click();
      await expect(page.getByText(new RegExp(reference))).toBeVisible();
    }

    await assignStandard(PROJECT_NAMES.alpha1, "v1.0");
    await assignStandard(PROJECT_NAMES.alpha2, "v2.0");

    await openComplianceStatusTab(page, "By standard", ORG_NAMES.alpha);
    await page.getByRole("button", { name: new RegExp(`Expand projects for ${reference}`) }).click();

    // With more than one version each is a collapsible sub-group (collapsed by default; a single version
    // pre-expands with no toggle). The pattern matches "Expand" and "Collapse" because the toggle's accessible
    // name flips on click and the locator is reused to find the expanded group.
    const v1Toggle = page.getByRole("button", { name: /^(Expand|Collapse) projects for v1\.0$/ });
    const v2Toggle = page.getByRole("button", { name: /^(Expand|Collapse) projects for v2\.0$/ });
    await expect(v1Toggle).toBeVisible();
    await expect(v2Toggle).toBeVisible();
    await v1Toggle.click();
    await v2Toggle.click();

    // Each version's sub-group lists only its own project. `xpath=..` selects the toggle's parent `<li>`; an
    // `ancestor::` axis chained off another locator would search each matched element's own subtree.
    const v1Group = v1Toggle.locator("xpath=..");
    await expect(v1Group.getByRole("link", { name: PROJECT_NAMES.alpha1 })).toBeVisible();
    await expect(v1Group.getByRole("link", { name: PROJECT_NAMES.alpha2 })).toHaveCount(0);

    const v2Group = v2Toggle.locator("xpath=..");
    await expect(v2Group.getByRole("link", { name: PROJECT_NAMES.alpha2 })).toBeVisible();
    await expect(v2Group.getByRole("link", { name: PROJECT_NAMES.alpha1 })).toHaveCount(0);

    // A project link inside the nested structure still navigates correctly.
    await v2Group.getByRole("link", { name: PROJECT_NAMES.alpha2 }).click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/modules\/compliance$/);
  });

  /**
   * The Outstanding tab has a Standard/Standard version/Sub-section filter set beside the Category/Evidence
   * status pair, and its `FilterPanel` is the right-hand sidebar (`layout="side"`, per the style guide's
   * placement rule), so `.filter-panel-top` does not render. "Sub-section" means "top-level ancestor
   * requirement" (a standard's hierarchy is `parent_requirement_id`-based; there is no section field), so
   * the fixture creates one top-level requirement with a child, assesses the child non-compliantly, and
   * confirms the *other* top-level requirement as the filter hides it while its real parent keeps it.
   */
  test("the Outstanding tab's Standard/Standard version/Sub-section filters narrow rows, and its filter panel renders as a sidebar", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-ORG-FILTER-${suffix}`;
    const standardName = `E2E Org Outstanding Filter Standard ${suffix}`;
    const sectionAName = `E2E Section A ${suffix}`;
    const sectionBName = `E2E Section B ${suffix}`;
    const childRequirementName = `E2E Child Requirement ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await expect(page.getByRole("button", { name: "v1.0" })).toBeVisible();
    await page.getByRole("button", { name: "v1.0" }).click();

    // Two top-level requirements ("sections"), one of which (A) gets a
    // child requirement — the one actually assessed Non-Compliant below.
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
    await expect(page.getByText("Version published.")).toBeVisible();

    // --- Assign to Alpha-1 and assess the child requirement Non-Compliant.
    await page.goto("/projects");
    await openProject(page, PROJECT_NAMES.alpha1);
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
    await page.getByLabel("Justification", { exact: true }).fill("Failed the required E2E filter-fixture inspection.");
    await page.getByRole("button", { name: "Update assessment" }).click();
    await expect(page.getByText("Current state: Assessed")).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();

    // --- Outstanding tab: sidebar layout, then the new filters.
    await openComplianceStatusTab(page, "Outstanding", ORG_NAMES.alpha);
    await expect(page.getByText(childRequirementName)).toBeVisible();

    // 40a: the filter panel is the right-hand sidebar, not a full-width top
    // bar — `.filter-panel-top` must not render here at all.
    await expect(page.locator(".filter-panel-top")).toHaveCount(0);
    await expect(page.locator(".list-page__filter")).toBeVisible();

    // 40b/40c: filtering by this standard narrows to its own rows and
    // reveals the standard-scoped "Standard version"/"Sub-section" fields.
    await selectFilterOption(page, "Standard", `${reference} — ${standardName}`);
    await expect(page.getByText("Sub-section", { exact: true })).toBeVisible();

    // 40d: picking the *other* top-level requirement (Section B) as the
    // sub-section hides the child (it's under Section A), picking its real
    // parent (Section A) brings it back.
    await selectFilterOption(page, "Sub-section", sectionBName);
    await expect(page.getByText(childRequirementName)).toHaveCount(0);
    await selectFilterOption(page, "Sub-section", sectionAName);
    await expect(page.getByText(childRequirementName)).toBeVisible();

    // The Export trigger's report request carries this panel's active Standard/Sub-section filters as query
    // parameters (the export matches what is shown). test_compliance_reports.py pins the server-side
    // filtering; this confirms the wiring from filter state to the outgoing request.
    const reportRequestPromise = page.waitForRequest(
      (req) =>
        req.url().includes("/modules/compliance/reports") &&
        req.url().includes("format=csv") &&
        req.url().includes("standard_id=") &&
        req.url().includes("requirement_id=")
    );
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await page.getByRole("dialog", { name: "Export" }).getByRole("menuitem", { name: "Download CSV report" }).click();
    await reportRequestPromise;
  });

  test("the org dashboard's stat cards are tidy at phone, tablet, laptop and desktop widths", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/org-overview");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click(); // this persona administers two organisations
    await expect(page.locator(".grid-metrics").first()).toBeVisible();
    await expectTidyStatBlocks(page);
  });
});
