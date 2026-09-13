import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: Compliance Module Phase 24 (docs/compliance-module-plan.md)
 * — post-publish clarification edits to a requirement, and a standard
 * version's always-editable `summary` field.
 *
 * `orgAdminAlphaBeta` is used for the same reason
 * `compliance-standards-management.spec.ts` uses it: `require_module_role
 * ("compliance", "standards_manager")` composes with `OrgRole.ORG_ADMIN` by
 * design, so no dedicated `standards_manager` persona/grant is needed for
 * this spec's own "manager can" coverage. Every fixture is dynamically
 * named with a per-run timestamp suffix, per this repo's standing test-
 * idempotency rule.
 */
test.describe("Compliance Module: post-publish clarification + version summary (Phase 24)", () => {
  test("clarify a requirement on a published version, and edit the version summary at every lifecycle stage", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-24-${suffix}`;
    const standardName = `E2E Clarification Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await page.getByRole("button", { name: "v1.0" }).click();

    // --- Version summary is editable on a draft version too.
    await page.getByPlaceholder(/This version's current standing/).fill("Initial draft summary.");
    await page.getByRole("button", { name: "Save summary" }).click();
    await expect(page.getByRole("button", { name: "Save summary" })).toBeDisabled();

    // --- Add a requirement, then publish — requirements become immutable,
    // but "Clarify" is offered in place of the ordinary edit controls.
    await page.getByRole("button", { name: "Add requirement" }).click();
    await page.getByLabel("Requirement name").fill("Access control policy");
    await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Access control policy")).toBeVisible();

    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("Published")).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit Access control policy" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Clarify Access control policy" })).toBeVisible();

    // --- Version summary stays editable once published — the motivating
    // "current standing" field, distinct from the draft-only content below.
    await expect(page.getByRole("button", { name: "Save summary" })).toBeDisabled();
    await page.getByPlaceholder(/This version's current standing/).fill("Published; superseded by nothing yet.");
    await page.getByRole("button", { name: "Save summary" }).click();
    await expect(page.getByRole("button", { name: "Save summary" })).toBeDisabled();
    await page.reload();
    await expect(page.getByPlaceholder(/This version's current standing/)).toHaveValue("Published; superseded by nothing yet.");

    // --- Clarify the requirement: mandatory note gates Save, and the
    // clarification badge appears afterward.
    await page.getByRole("button", { name: "Clarify Access control policy" }).click();
    const clarifyDialog = page.getByRole("dialog", { name: 'Clarify "Access control policy"' });
    await expect(clarifyDialog.getByRole("button", { name: "Save clarification" })).toBeDisabled();
    await clarifyDialog.getByLabel("Clarification note (required)").fill("Fixed a typo in the description.");
    await clarifyDialog.getByLabel("Description", { exact: true }).fill("Restrict access to information on a need-to-know basis.");
    await expect(clarifyDialog.getByRole("button", { name: "Save clarification" })).toBeEnabled();
    await clarifyDialog.getByRole("button", { name: "Save clarification" }).click();
    await expect(clarifyDialog).toHaveCount(0);

    await expect(page.getByText("Clarified", { exact: true })).toBeVisible();
    await expect(page.getByText("Restrict access to information on a need-to-know basis.")).toBeVisible();
  });
});
