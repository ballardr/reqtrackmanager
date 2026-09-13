import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES, selectOrgOverviewGroup } from "../../e2e-workflows/helpers";
import { createStandardWithVersion, selectFilterOption } from "./helpers";

/**
 * Job to be done: Compliance Module Phase 14 (docs/compliance-module-plan.md)
 * — the org-level Organisation Compliance View + Dashboard (§22/§23),
 * mounted as three flat `ResourceMenu` groups ("Compliance dashboard" /
 * "Compliance by standard" / "Outstanding compliance items") on the core
 * "Organisation Overview" page (Phase 19, `/orgs/:orgId/overview`) — see
 * `frontend/src/modules/compliance/module.ts`'s `orgOverviewSections` for
 * how these moved off `OrgAdminPage.tsx` (where they originally lived, as
 * one combined "Compliance overview" group), and Phase 25b's own notes for
 * why that group's internal `Tabs` were later collapsed into three flat
 * top-level groups instead (one navigation layer too many). This spec also
 * covers Phase 25b's headline gauges (`ComplianceOrgOverviewTiles.tsx`),
 * which surface directly in the page's own always-visible stats header —
 * no click into any group required.
 *
 * Covers the read/drill-down path: author and publish a standard (Phase 12
 * UI), assign it to a project and assess a requirement Non-Compliant
 * (Phase 13 UI), then confirm the headline gauges, the org-wide Dashboard
 * group, the "Compliance by standard" table (with its project filter), and
 * the "Outstanding" group all surface that project/requirement, and that
 * the standard table's drill-down link actually opens the underlying
 * project's own Compliance page.
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

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await expect(page.getByRole("button", { name: "v1.0" })).toBeVisible();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill(requirementName);
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(requirementName)).toBeVisible();

    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    // The exact toast text, not a bare "Published" substring match — once
    // this standard has more than one version, an earlier one's own nav-
    // rail "Versions" entry also reads "v1.0 (Published)", which a plain
    // substring match resolves to ambiguously alongside this toast.
    await expect(page.getByText("Version published.")).toBeVisible();

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

    // --- Phase 25b: headline gauges surface directly in the Organisation
    //     Overview's own always-visible stats header, no group click needed.
    //     Labelled distinctly from the Dashboard group's own same-numbers
    //     StatCards below (both render at once — the Dashboard group is
    //     `OrgOverviewPage.tsx`'s default section).
    await page.goto("/org-overview");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page.getByText("Overall org compliance")).toBeVisible();
    await expect(page.getByText("Compliance standards in use")).toBeVisible();
    await expect(page.getByText("Projects out of compliance")).toBeVisible();

    // --- Org-wide Dashboard: the non-compliant project count is a headline
    //     tile (Phase 36) that drills through to "Compliance by standard"
    //     pre-filtered/pre-pivoted to exactly the projects it counted,
    //     rather than listing them inline on the tile itself.
    await selectOrgOverviewGroup(page, "Compliance dashboard");
    await expect(page.getByText("Active compliance standards")).toBeVisible();
    const nonCompliantTile = page.getByRole("link", { name: /Non-compliant projects/ });
    await expect(nonCompliantTile).toBeVisible();
    await nonCompliantTile.click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/overview\/compliance-by-standard\?groupBy=project&state=non_compliant/);
    const expandProjectButton = page.getByRole("button", { name: new RegExp(`Expand standards for ${PROJECT_NAMES.alpha1}`) });
    await expect(expandProjectButton).toBeVisible();
    await expandProjectButton.click();
    // `getByText` alone would also match this standard's own <option> in the
    // "Standard"/"Standard version" filter selects — scope to the expanded
    // row's own link.
    await expect(page.getByRole("link", { name: new RegExp(reference) })).toBeVisible();

    // --- Phase 15/25b: download the organisation-wide compliance report,
    //     now behind the "Export" popover trigger (Principle 11).
    await selectOrgOverviewGroup(page, "Compliance dashboard");
    await page.getByRole("button", { name: "Export" }).click();
    const pdfDownloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download PDF report" }).click();
    const pdfDownload = await pdfDownloadPromise;
    expect(pdfDownload.suggestedFilename()).toContain("compliance-report.pdf");

    // --- "Compliance by standard" group: the standard groups the project,
    //     and drilling down opens the project's own Compliance page.
    await selectOrgOverviewGroup(page, "Compliance by standard");

    // Phase 43: this panel's own Export trigger carries its active Standard
    // filter as a query param too — "export what I'm looking at" applies
    // here the same way it does to the Outstanding group (covered in the
    // dedicated filter test below).
    await selectFilterOption(page, "Standard", `${reference} — ${standardName}`);
    const standardsReportRequestPromise = page.waitForRequest(
      (req) => req.url().includes("/modules/compliance/reports/csv") && req.url().includes("standard_id=")
    );
    await page.getByRole("button", { name: "Export" }).click();
    await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Download CSV report" }).click();
    await standardsReportRequestPromise;
    await selectFilterOption(page, "Standard", "All standards");

    const expandButton = page.getByRole("button", { name: new RegExp(`Expand projects for ${reference}`) });
    await expect(expandButton).toBeVisible();
    await expandButton.click();
    const projectLink = page.getByRole("link", { name: PROJECT_NAMES.alpha1 });
    await expect(projectLink).toBeVisible();
    await projectLink.click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/modules\/compliance$/);

    // --- Outstanding group: the non-compliant requirement is listed,
    //     tagged with the project it belongs to.
    await page.goto("/org-overview");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await selectOrgOverviewGroup(page, "Outstanding compliance items");
    await expect(page.getByText(requirementName)).toBeVisible();
    await expect(page.getByRole("link", { name: PROJECT_NAMES.alpha1 }).first()).toBeVisible();
  });

  /**
   * Phase 39 (docs/compliance-module-plan.md) — "Compliance by standard"'s
   * default (group-by-standard) expanded row now groups its projects by
   * `standard_version_id` first (39d), each version's projects indented a
   * level deeper (39c), rather than one flat list of projects each
   * carrying its own version suffix — each version with more than one
   * sibling is its own collapsible sub-group (a live follow-up during this
   * phase: with only one version, per the first test in this file, that
   * sub-group instead pre-expands with no toggle at all, since there's
   * nothing left to disambiguate). Covers a standard with two published
   * versions assigned to two different projects, confirming each version's
   * sub-group lists only its own project — not the other version's — and
   * that a project link inside the nested structure still navigates.
   */
  test("a standard on two versions groups its expanded row as Standard -> Version -> Project (Phase 39d)", async ({ page }) => {
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
    // The exact toast text, not a bare "Published" substring match — once
    // this standard has more than one version, an earlier one's own nav-
    // rail "Versions" entry also reads "v1.0 (Published)", which a plain
    // substring match resolves to ambiguously alongside this toast.
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
    // The exact toast text, not a bare "Published" substring match — once
    // this standard has more than one version, an earlier one's own nav-
    // rail "Versions" entry also reads "v1.0 (Published)", which a plain
    // substring match resolves to ambiguously alongside this toast.
    await expect(page.getByText("Version published.")).toBeVisible();

    async function assignStandard(projectName: string, versionLabel: string) {
      await page.goto("/projects");
      await page.getByRole("link", { name: projectName }).click();
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

    await page.goto("/org-overview");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await selectOrgOverviewGroup(page, "Compliance by standard");
    await page.getByRole("button", { name: new RegExp(`Expand projects for ${reference}`) }).click();

    // More than one version behind this standard — each is its own
    // collapsible sub-group (collapsed by default), unlike the single-
    // version case which pre-expands with no toggle at all. Matches both
    // "Expand"/"Collapse" — the toggle's own accessible name flips once
    // clicked, and this same locator is reused afterwards to find the
    // (now-expanded) group.
    const v1Toggle = page.getByRole("button", { name: /^(Expand|Collapse) projects for v1\.0$/ });
    const v2Toggle = page.getByRole("button", { name: /^(Expand|Collapse) projects for v2\.0$/ });
    await expect(v1Toggle).toBeVisible();
    await expect(v2Toggle).toBeVisible();
    await v1Toggle.click();
    await v2Toggle.click();

    // Each version's sub-group lists only its own project. `xpath=..`
    // walks to the immediate parent (the toggle button's own `<li>`) —
    // chaining an `ancestor::` axis off another locator instead scopes the
    // search to each matched element's own subtree, which can't find a
    // node "above" it.
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
   * Phase 40 (docs/compliance-module-plan.md) — the "Outstanding compliance
   * items" group gets a real Standard/Standard version/Sub-section filter
   * set (on top of the pre-existing Category/Evidence status pair), and
   * moves its `FilterPanel` from a full-width top bar to the standard
   * right-hand sidebar (`layout="side"`), per the style guide's own
   * placement rule (`.filter-panel-top` should no longer render here at
   * all, matching `.side-grid`'s own already-used-by-"Compliance by
   * standard" shape). "Sub-section" means "top-level ancestor requirement"
   * — a standard's hierarchy is purely `parent_requirement_id`-based, no
   * dedicated section field exists — so this fixture creates one top-level
   * requirement with a child, non-compliantly assesses the child, and
   * confirms picking the *other* top-level requirement as the sub-section
   * filter hides it while picking its real parent keeps it.
   */
  test("the Outstanding group's Standard/Standard version/Sub-section filters narrow rows, and its filter panel renders as a sidebar", async ({ page }) => {
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

    // --- Outstanding group: sidebar layout, then the new filters.
    await page.goto("/org-overview");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await selectOrgOverviewGroup(page, "Outstanding compliance items");
    await expect(page.getByText(childRequirementName)).toBeVisible();

    // 40a: the filter panel is the right-hand sidebar, not a full-width top
    // bar — `.filter-panel-top` must not render here at all.
    await expect(page.locator(".filter-panel-top")).toHaveCount(0);
    await expect(page.locator(".side-grid")).toBeVisible();

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

    // Phase 43: the Export trigger's report request carries this panel's
    // active Standard/Sub-section filters as query params — "export what
    // I'm looking at," not an unfiltered organisation-wide dump. Exact
    // filtering correctness is pinned server-side
    // (test_compliance_reports.py); this only confirms the wiring from live
    // filter state to the actual outgoing request.
    const reportRequestPromise = page.waitForRequest(
      (req) =>
        req.url().includes("/modules/compliance/reports/csv") &&
        req.url().includes("standard_id=") &&
        req.url().includes("requirement_id=")
    );
    await page.getByRole("button", { name: "Export" }).click();
    await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Download CSV report" }).click();
    await reportRequestPromise;
  });
});
