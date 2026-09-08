import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: Compliance Module Phase 22 (docs/compliance-module-plan.md)
 * — a standard's own "Members" section (`standards_manager`/
 * `standards_contributor`, scoped to just this one standard). Covers:
 *
 * - Creating a standard auto-grants the creator a direct `standards_manager`
 *   role, visible on the new "Members" nav-rail section.
 * - The last remaining `standards_manager`'s own checkbox is disabled (with
 *   an explanatory title) when no fallback compliance-managers group is
 *   configured for the organisation.
 * - Adding another org member as `standards_contributor` via the "Add
 *   member" picker, and revoking that grant again — a contributor's own
 *   checkbox is never disabled (there's always at least one manager
 *   already, this add/revoke doesn't touch the floor).
 *
 * `orgAdminAlphaBeta` creates the standard (compliance_manager-via-
 * ORG_ADMIN override, per `compliance-standards-management.spec.ts`'s own
 * precedent for why no dedicated persona is needed); `memberAlphaBeta` (a
 * genuine plain member of Alpha, seed_e2e_dataset.py) is the org member
 * added as a contributor. The standard itself is dynamically named with a
 * per-run timestamp suffix, per this repo's standing test-idempotency rule.
 */
test.describe("Compliance Module: standard-scoped RBAC — Members section (Phase 22)", () => {
  test("standard creation auto-grants the creator, the last manager checkbox is disabled, and a contributor can be added and revoked", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-RBAC-${suffix}`;
    const standardName = `E2E RBAC Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName });

    await page.getByRole("link", { name: "Members" }).click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/members$/);

    // The creator is auto-granted `standards_manager` (Phase 22).
    await expect(page.getByText(PERSONAS.orgAdminAlphaBeta.name)).toBeVisible();
    await page.getByRole("button", { name: `Roles for ${PERSONAS.orgAdminAlphaBeta.name}` }).click();
    const creatorGroup = page.getByRole("group", { name: `Roles for ${PERSONAS.orgAdminAlphaBeta.name}` });
    const managerCheckbox = creatorGroup.getByRole("checkbox", {
      name: `Revoke Standards Manager from ${PERSONAS.orgAdminAlphaBeta.name}`,
    });
    await expect(managerCheckbox).toBeChecked();
    // Last remaining manager, no fallback group configured for this org ->
    // disabled, with an explanatory title (§3's manager floor).
    await expect(managerCheckbox).toBeDisabled();
    await expect(managerCheckbox).toHaveAttribute("title", /must always have at least one/);
    await page.keyboard.press("Escape");

    // Add `memberAlphaBeta` as a Standards Contributor.
    await page.getByRole("button", { name: "Add member" }).click();
    const addDialog = page.getByRole("dialog", { name: "Add a member" });
    await addDialog.getByLabel("User").selectOption({ label: new RegExp(PERSONAS.memberAlphaBeta.name) });
    await addDialog.getByLabel("Role").selectOption({ label: "Standards Contributor" });
    await addDialog.getByRole("button", { name: "Add" }).click();

    await expect(page.getByText(PERSONAS.memberAlphaBeta.name)).toBeVisible();
    await page.getByRole("button", { name: `Roles for ${PERSONAS.memberAlphaBeta.name}` }).click();
    const memberGroup = page.getByRole("group", { name: `Roles for ${PERSONAS.memberAlphaBeta.name}` });
    const contributorCheckbox = memberGroup.getByRole("checkbox", {
      name: `Revoke Standards Contributor from ${PERSONAS.memberAlphaBeta.name}`,
    });
    await expect(contributorCheckbox).toBeChecked();
    // A contributor grant never touches the manager floor -> always freely revocable.
    await expect(contributorCheckbox).toBeEnabled();

    // Revoke it — the row disappears (no roles left on this standard).
    await contributorCheckbox.uncheck();
    await expect(page.getByText(PERSONAS.memberAlphaBeta.name)).toHaveCount(0);
  });
});
