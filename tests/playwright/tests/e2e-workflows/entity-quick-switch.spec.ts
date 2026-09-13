import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * Job to be done: compliance-module-plan.md Phase 28 — the "entity
 * quick-switch" chevron next to an entity's name in a page's own `<h1>`,
 * opening a popover that lists every sibling instance of the same entity
 * type the current user can reach. Phase 37 extended this to Org Settings'
 * normal (non-degraded) admin header, whose title renders via
 * `ResourceMenu`'s own `titleAdornment` slot rather than a bespoke `<h1>`.
 *
 * Persona: `orgAdminAlphaBeta` (`org_admin` of both Alpha and Beta, see
 * backend/scripts/seed_e2e_dataset.py) — a genuine multi-org account, so
 * the Organisation Overview and Org Settings chevrons both have a real
 * sibling to offer.
 */
test.describe("entity quick-switch (Phase 28)", () => {
  test("switches organisations from the Organisation Overview page via the chevron popover", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await page.goto("/org-overview");
    // Multi-org account: lands on the org picker first.
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/overview$/);
    await expect(page.getByRole("heading", { name: ORG_NAMES.alpha })).toBeVisible();

    await page.getByRole("button", { name: "Switch organisation" }).click();
    // Clicking a link inside the `Popover` before its own positioning
    // measurement settles can silently miss it — see the identical guard
    // (and its full explanation) in org-rename-and-test-email.spec.ts and
    // org-merge-import.spec.ts.
    const dialog = page.getByRole("dialog", { name: "Switch organisation" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("link", { name: ORG_NAMES.alpha })).not.toBeVisible();

    await dialog.getByRole("link", { name: ORG_NAMES.beta }).click();

    await expect(page).toHaveURL(/\/orgs\/[^/]+\/overview$/);
    await expect(page.getByRole("heading", { name: ORG_NAMES.beta })).toBeVisible();
    await expect(dialog).not.toBeVisible();
  });

  // Phase 37 — the same chevron, now also on Org Settings' normal (non-
  // degraded) admin header, whose title renders via `ResourceMenu`'s own
  // `titleAdornment` slot rather than a bespoke `<h1>` of its own.
  test("switches organisations from Org Settings' admin header via the chevron popover", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await page.goto("/orgs");
    // Multi-org account: lands on the org picker first.
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await expect(page.getByRole("heading", { name: ORG_NAMES.alpha })).toBeVisible();

    await page.getByRole("button", { name: "Switch organisation" }).click();
    const dialog = page.getByRole("dialog", { name: "Switch organisation" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("link", { name: ORG_NAMES.alpha })).not.toBeVisible();

    await dialog.getByRole("link", { name: ORG_NAMES.beta }).click();

    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await expect(page.getByRole("heading", { name: ORG_NAMES.beta })).toBeVisible();
    await expect(dialog).not.toBeVisible();
  });
});
