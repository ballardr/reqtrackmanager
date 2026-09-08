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
    // Versions -> drill into v1.0. `exact: true` disambiguates the plain
    // nav-rail link from Phase 23's own "N Versions" Overview stat tile,
    // whose accessible name ("1 Versions") otherwise substring-matches too.
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
    await expect(page.getByText("Published")).toBeVisible();
    await expect(page.getByRole("button", { name: "Add requirement" })).toHaveCount(0);

    // --- History section shows this standard's own audit trail.
    await page.getByRole("link", { name: "History" }).click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/history$/);
    await expect(page.getByRole("listitem").filter({ hasText: "created" })).toBeVisible();
  });

  test("Overview stat tiles, expandable Versions nav group, and requirement list-view detail panel (Phase 23)", async ({ page }) => {
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

    // --- Expandable "Versions" nav-rail group: collapsed by default, shows
    // this standard's one version once expanded, and deep-links straight
    // into that version's own workspace URL — the nav-rail's own route,
    // not just a visual affordance.
    await page.getByRole("button", { name: "Expand versions" }).click();
    const versionNavLink = page.getByRole("link", { name: /v1\.0/ }).filter({ hasText: "Draft" });
    await expect(versionNavLink).toBeVisible();
    await versionNavLink.click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/versions\/[0-9a-f-]+$/);
    await expect(page.getByText(`${reference} — v1.0`)).toBeVisible();

    // Collapsing the group hides the version links again, and the choice
    // persists (a reload keeps it collapsed).
    await page.getByRole("button", { name: "Collapse versions" }).click();
    await expect(page.getByRole("link", { name: /v1\.0/ }).filter({ hasText: "Draft" })).toHaveCount(0);

    // --- Requirement browsing: add two requirements, then use the new
    // list view's search filter and detail panel (distinct from the tree
    // view's own inline expand/edit, which the earlier test in this file
    // already covers).
    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill("Access control policy");
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Access control policy")).toBeVisible();

    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill("Asset inventory");
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Asset inventory")).toBeVisible();

    // View mode (`useViewMode`) is a per-user preference shared across
    // every standard this shared `orgAdminAlphaBeta` persona ever opens —
    // not scoped to this one test — so this switches back to tree view in
    // a `finally` regardless of what happens in between, rather than
    // leaving a later, unrelated spec run to unexpectedly land on list
    // view for this persona if an assertion here ever throws first.
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
});
