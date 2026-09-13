import { expect, test } from "@playwright/test";

import { loginAs, logout, ORG_NAMES, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: compliance-module-plan.md Phase 19 — the new
 * "Organisation Overview" nav-rail page, reachable regardless of whether
 * compliance applies to the org (unlike Phase 18's "Compliance Standards"
 * tab). Covers reaching the page via `/org-overview`'s single-org/multi-org
 * auto-redirect, and the core scoping rule from `docs/decisions.md`'s
 * "Compliance module, human review follow-ups" entry: an org admin sees
 * the organisation's real totals, while a plain member with only partial
 * project access sees counts scoped to what they can actually see.
 *
 * Persona: `stakeholderAlpha` (org role `member` of Alpha only, but a
 * project-level `stakeholder` on Alpha-1 alone — never assigned any role
 * on Alpha-2, see backend/scripts/seed_e2e_dataset.py) vs `orgAdminAlphaBeta`
 * (`org_admin` of Alpha, sees both Alpha-1 and Alpha-2).
 */
test.describe("Organisation Overview page (Phase 19)", () => {
  test("a single-org member with partial project access sees scoped totals; the org admin sees the real totals", async ({ page }) => {
    await loginAs(page, PERSONAS.stakeholderAlpha.email);

    // Single-org account: `/org-overview` redirects straight in, mirroring
    // `/orgs`'s own existing single-org/multi-org auto-redirect.
    await page.goto("/org-overview");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/overview$/);
    await expect(page.getByRole("heading", { name: ORG_NAMES.alpha })).toBeVisible();

    await expect(
      page.getByText("These figures are scoped to what you can see, not this organisation's full totals.")
    ).toBeVisible();
    // Matched by exact "Projects<digits>" text (label immediately followed
    // by the value, no separator) — a plain substring match on "Projects"
    // would also catch the compliance dashboard's own "Projects subject to
    // compliance" stat, which this org has (Alpha has standards assigned
    // from other specs' fixtures). Stat items render inside `.stat-bar`
    // (compliance-module-plan.md Phase 27b), not `.card`.
    const memberProjectsItem = page.locator(".stat-bar-item").filter({ hasText: /^Projects\d+$/ });
    const memberProjectCountText = (await memberProjectsItem.innerText()).replace("Projects", "");
    const memberProjectCount = Number(memberProjectCountText);
    // Alpha-2 is never granted to this persona (see this file's own
    // docstring) — exactly Alpha-1 is visible to them, regardless of how
    // many other Alpha projects other specs' own fixtures may have added.
    expect(memberProjectCount).toBe(1);

    await logout(page);

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/org-overview");
    // Multi-org account: a picker, not an auto-redirect.
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/overview$/);

    await expect(
      page.getByText("These figures are scoped to what you can see, not this organisation's full totals.")
    ).not.toBeVisible();
    const adminProjectsItem = page.locator(".stat-bar-item").filter({ hasText: /^Projects\d+$/ });
    const adminProjectCountText = (await adminProjectsItem.innerText()).replace("Projects", "");
    expect(Number(adminProjectCountText)).toBeGreaterThan(memberProjectCount);
  });

  test("nav rail link is always visible, unlike the compliance-gated Compliance Standards tab", async ({ page }) => {
    await loginAs(page, PERSONAS.stakeholderAlpha.email);
    await expect(page.getByRole("link", { name: "Organisation overview" })).toBeVisible();
  });

  /**
   * Phase 27c — the stats header is folded into a real, always-present
   * "Overview" `ResourceMenu` group, and `ResourceMenu` itself hides its own
   * menu-strip chrome whenever there's nothing to switch between. Every org
   * in the seed dataset has Compliance entitled and enabled by default (see
   * `org-admin-modules.spec.ts`), so this test toggles it off itself
   * (single-org `orgAdminGamma`, mirroring that spec's own toggle-then-
   * restore pattern) rather than relying on a persona that happens to have
   * it disabled — no such persona exists in the seed dataset.
   */
  test("ResourceMenu chrome is hidden with compliance disabled, shown with it enabled", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    const toggle = page.locator("tr", { hasText: "Compliance" }).getByRole("switch");
    await expect(toggle).toHaveAttribute("aria-checked", "true");

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");

    await page.goto("/org-overview");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/overview$/);
    // Scoped to `.resource-menu-nav` and matched `exact` — a bare `getByRole
    // ("link", { name: "Overview" })` also matches `Layout.tsx`'s persistent
    // "Organisation overview" nav-rail link (case-insensitive substring),
    // which is unrelated to the `ResourceMenu` group chrome this asserts on.
    await expect(page.locator(".resource-menu-nav")).toHaveCount(0);
    await expect(page.locator(".stat-bar")).toBeVisible();

    // Restore the org's own enablement state to what this test found it in,
    // per this repo's standing test-idempotency rule — no shared-fixture
    // mutation survives the test.
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");

    await page.goto("/org-overview");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/overview$/);
    const overviewLink = page.locator(".resource-menu-nav").getByRole("link", { name: "Overview", exact: true });
    await expect(overviewLink).toBeVisible();
    await expect(overviewLink).toHaveAttribute("aria-current", "page");
    await expect(page.locator(".stat-bar")).toBeVisible();
  });
});
