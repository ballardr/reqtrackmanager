import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: module system Phase 1 (docs/compliance-module-plan.md) —
 * Org Admin's "Modules" resource-menu group (`GET /orgs/{id}/modules`).
 *
 * Updated for Compliance Module Phase 12 (see docs/compliance-module-plan.md's
 * Phase 12 notes): this spec's own docstring originally flagged itself as
 * scoped to "no real module yet" and explicitly said to revisit once Phase 5
 * shipped a real first-party module. Phase 5 shipped Compliance
 * (`default_enabled=True`, `implemented=True`) well before this session, but
 * nothing had actually run this spec against a live, freshly-rebuilt
 * backend container since — `backend/app/modules/registry.py`'s
 * `INSTALLED_MODULES` list only reflects what's actually running, and the
 * container this repo's Playwright suite runs against had gone stale
 * (pre-Phase-5) until this session rebuilt it while verifying Phase 12's own
 * new e2e spec. This is that overdue revisit, not a Phase-12-specific
 * feature test.
 */
test.describe("org admin: Modules section", () => {
  test("shows the Compliance module, entitled and enabled by default, and its toggle works", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");

    const complianceRow = page.locator("tr", { hasText: "Compliance" });
    await expect(complianceRow).toBeVisible();
    const toggle = complianceRow.getByRole("switch");
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect(toggle).toBeEnabled();

    // Toggle off then back on — leaves the org's own enablement state
    // exactly as this spec found it (default-enabled), per this repo's
    // standing test-idempotency rule (no shared-fixture mutation survives
    // the test).
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
  });
});
