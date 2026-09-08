import { expect, test } from "@playwright/test";

import { loginAs, logout, ORG_NAMES, PERSONAS } from "./helpers";

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
    // compliance" stat card, which this org has (Alpha has standards
    // assigned from other specs' fixtures).
    const memberProjectsCard = page.locator(".card").filter({ hasText: /^Projects\d+$/ });
    const memberProjectCountText = (await memberProjectsCard.innerText()).replace("Projects", "");
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
    const adminProjectsCard = page.locator(".card").filter({ hasText: /^Projects\d+$/ });
    const adminProjectCountText = (await adminProjectsCard.innerText()).replace("Projects", "");
    expect(Number(adminProjectCountText)).toBeGreaterThan(memberProjectCount);
  });

  test("nav rail link is always visible, unlike the compliance-gated Compliance Standards tab", async ({ page }) => {
    await loginAs(page, PERSONAS.stakeholderAlpha.email);
    await expect(page.getByRole("link", { name: "Organisation overview" })).toBeVisible();
  });
});
