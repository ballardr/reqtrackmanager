import { expect, test } from "@playwright/test";

import { addDefinition, apiHeaders, installCleanupHook, loginAs, onCleanup, ORG_NAMES, PERSONAS } from "../../e2e-workflows/helpers";
import { chooseListAction } from "../../listActions";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: "Compliance Standards" is its own top-level, cross-org nav-rail tab. Covers tab visibility
 * (absent for a plain member with no relevant role and no standards, present once granted), one-step standard
 * and version creation from `/standards`, Standard workspace navigation (Overview/Details, Versions, History)
 * and org compliance settings (`/standards/settings/:orgId`, Action types / Mapping types via `ResourceMenu`).
 *
 * `orgAdminAlphaBeta` is used rather than a `compliance_manager` persona: `require_module_role("compliance",
 * "compliance_manager")` composes with `OrgRole.ORG_ADMIN`. It manages two orgs, so "New standard" exercises
 * its organisation picker (`StandardFormModal.tsx`). Fixtures carry a per-run timestamp suffix.
 */
test.describe("Compliance Module: \"Compliance Standards\" top-level nav-rail tab", () => {
  installCleanupHook();
  test("tab is hidden for a user with no org memberships, and visible for a compliance manager", async ({ page }) => {
    // `orphan` has no org memberships, so `nav-visibility` is false for it whatever Alpha/Beta hold. A plain
    // member such as `memberAlphaBeta` is not used: this suite adds standards to Alpha, which flips their visibility.
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

    // --- Org compliance settings: create an action type, needed for the required action below
    // (`/standards/settings/:orgId`). Compliance settings is a row of the page's actions menu, one per organisation.
    await page.goto("/standards");
    await chooseListAction(page, ORG_NAMES.alpha);
    await expect(page).toHaveURL(/\/standards\/settings\/[^/]+$/);
    await addDefinition(page, "Add action type", { "Action type name": actionTypeName });
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

    // Standards: create one, with its mandatory first (draft) version, in the combined "New standard" dialog
    // (a standard always has a version). `orgAdminAlphaBeta` manages two orgs, so this exercises the dialog's
    // organisation picker.
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    // Standard workspace navigation: Overview -> Versions -> drill into v1.0. `exact: true` disambiguates the
    // nav-rail link from the "N Versions" Overview stat tile ("1 Versions").
    await page.getByRole("link", { name: "Versions", exact: true }).click();
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
    await expect(page.getByText("Published", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Add requirement" })).toHaveCount(0);

    // --- History section shows this standard's own audit trail.
    await page.getByRole("link", { name: "History" }).click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/history$/);
    await expect(page.getByRole("listitem").filter({ hasText: "created" })).toBeVisible();
  });

  test("Overview stat tiles, expandable Versions nav group, and requirement list-view detail panel", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-23-${suffix}`;
    const standardName = `E2E Workspace UX Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    // --- Overview: freshly created standard has one (draft) version, zero
    // requirements, and no assigned projects yet — each stat is its own
    // clickable tile, not a plain number.
    const versionsTile = page.getByRole("link", { name: /Versions/ }).filter({ hasText: "1" });
    await expect(versionsTile).toBeVisible();
    const requirementsTile = page.getByRole("link", { name: /Requirements/ }).filter({ hasText: "0" });
    await expect(requirementsTile).toBeVisible();
    await expect(page.getByRole("link", { name: /^0 Projects$/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Compliant/ }).filter({ hasText: "0" })).toBeVisible();

    // The "Requirements" tile jumps straight into the version workspace
    // (the same place the "Versions" tile's own list would drill into),
    // not just the plain version list.
    await requirementsTile.click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/versions\/[0-9a-f-]+$/);
    await expect(page.getByText(`${reference} — v1.0`)).toBeVisible();

    // Expandable "Versions" nav-rail group: this version's own route is already open, so the group auto-expands
    // showing the standard's one version without a click on the disclosure toggle, and the link deep-links
    // into the version's workspace URL.
    const versionNavLink = page.getByRole("link", { name: /v1\.0/ }).filter({ hasText: "Draft" });
    await expect(versionNavLink).toBeVisible();
    await expect(page.getByRole("button", { name: "Collapse versions" })).toBeVisible();
    await versionNavLink.click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/versions\/[0-9a-f-]+$/);
    await expect(page.getByText(`${reference} — v1.0`)).toBeVisible();

    // Collapsing the group hides the version links again, and the choice
    // persists (a reload keeps it collapsed).
    await page.getByRole("button", { name: "Collapse versions" }).click();
    await expect(page.getByRole("link", { name: /v1\.0/ }).filter({ hasText: "Draft" })).toHaveCount(0);

    // Requirement browsing: add two requirements, then use the list view's search filter and detail panel
    // (the tree view's inline expand/edit is covered by the earlier test in this file).
    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill("Access control policy");
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Access control policy")).toBeVisible();

    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill("Asset inventory");
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Asset inventory")).toBeVisible();

    // View mode (`useViewMode`) is a per-user preference shared across every standard this persona opens, so
    // a `finally` switches back to tree view even when an assertion throws first.
    await page.getByRole("button", { name: "List view" }).click();
    try {
      await page.getByPlaceholder("Search requirements…").fill("access");
      await expect(page.getByText("Asset inventory")).toHaveCount(0);
      await expect(page.getByText("Access control policy")).toBeVisible();

      await page.getByText("Access control policy").click();
      const detailPanel = page.getByRole("dialog", { name: "Access control policy" });
      await expect(detailPanel).toBeVisible();
      await detailPanel.getByLabel("Description").fill("Who may access what, and how it's reviewed.");
      await detailPanel.getByRole("button", { name: "Save" }).click();
      // The panel stays open after a successful save (showing the saved
      // value, not forcing a re-open to confirm it stuck) — closed
      // explicitly here via its own ✕ control.
      await expect(detailPanel.getByLabel("Description")).toHaveValue("Who may access what, and how it's reviewed.");
      await detailPanel.getByRole("button", { name: "Close" }).click();
      await expect(detailPanel).toHaveCount(0);
    } finally {
      // Switching back to tree view shows the same edit — one requirement,
      // two views onto it.
      await page.getByRole("button", { name: "Tree view" }).click();
    }
    await expect(page.getByText("Who may access what, and how it's reviewed.")).toBeVisible();
  });

  test("Standards list page offers a tiles/list view toggle", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-35A-${suffix}`;
    const standardName = `E2E View Toggle Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    // `view_mode:standards` is a per-user preference shared by every run of this persona, so the test starts
    // from tiles explicitly and resets the preference in an `onCleanup` that runs even on timeout. The tiles
    // default is covered by StandardListPage's TogglesBetweenTilesAndListView story.
    onCleanup(async (request) => {
      await request.patch("http://localhost:8000/api/v1/auth/me/preferences", {
        headers: await apiHeaders(request, PERSONAS.orgAdminAlphaBeta.email),
        data: { ui_preferences: { "view_mode:standards": "tiles" } },
      });
    });
    await page.goto("/standards");
    await page.getByRole("button", { name: "Tile view" }).click();
    // Tiles: the standard renders as a card link, not a table row.
    await expect(page.getByRole("link", { name: new RegExp(standardName) })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);

    await page.getByRole("button", { name: "List view" }).click();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("cell", { name: standardName })).toBeVisible();
  });
});
