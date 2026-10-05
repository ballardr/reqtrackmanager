import { expect, test } from "@playwright/test";

import {
  apiHeaders,
  installCleanupHook,
  loginAs,
  logout,
  onCleanup,
  ORG_NAMES,
  PASSWORD,
  PERSONAS,
  PROJECT_NAMES,
  selectOrgAdminGroup,
  setOrgModuleAvailability,
} from "./helpers";

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
 * Personas: a disposable Alpha member created per run with a `stakeholder`
 * role on Alpha-1 alone (removed afterwards) vs `orgAdminAlphaBeta`
 * (`org_admin` of Alpha, sees every Alpha project). The counts cover
 * active (non-archived) projects only.
 */
test.describe("Organisation Overview page (Phase 19)", () => {
  installCleanupHook();

  test("a single-org member with partial project access sees scoped totals; the org admin sees the real totals", async ({ page, request }) => {
    // A disposable Alpha member with a role on Alpha-1 only (2026-10-04),
    // not the shared stakeholderAlpha persona: other specs running in
    // parallel temporarily grant that persona roles on their own projects,
    // which made this exact count race them.
    const memberEmail = `e2e-overview-member-${Date.now()}@example.com`;
    const adminHeaders = await apiHeaders(request, PERSONAS.orgAdminAlphaBeta.email);
    const api = "http://localhost:8000/api/v1";
    const orgs: { id: string; name: string }[] = await (await request.get(`${api}/orgs`, { headers: adminHeaders })).json();
    const alphaId = orgs.find((o) => o.name === ORG_NAMES.alpha)!.id;
    const created = await request.post(`${api}/orgs/${alphaId}/users`, {
      headers: adminHeaders, data: { email: memberEmail, display_name: "E2E Overview Member", password: PASSWORD, role: "member" },
    });
    expect(created.ok()).toBeTruthy();
    const memberId: string = (await created.json()).user_id;
    onCleanup(async (cleanupRequest) => {
      const headers = await apiHeaders(cleanupRequest, PERSONAS.orgAdminAlphaBeta.email);
      await cleanupRequest.delete(`${api}/orgs/${alphaId}/users/${memberId}/membership`, { headers });
    });
    const alpha1 = (await (await request.get(`${api}/projects?archived=false&search=${encodeURIComponent(PROJECT_NAMES.alpha1)}`, {
      headers: adminHeaders,
    })).json() as { id: string; name: string }[]).find((p) => p.name === PROJECT_NAMES.alpha1)!;
    const granted = await request.post(`${api}/projects/${alpha1.id}/roles`, {
      headers: adminHeaders, data: { user_id: memberId, role: "stakeholder" },
    });
    expect(granted.ok()).toBeTruthy();

    await loginAs(page, memberEmail);

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
    // Only Alpha-1 was granted — exactly one project is visible to them,
    // regardless of how many other Alpha projects other specs have added
    // (org-wide-visibility projects now live in their specs' own orgs).
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
    // Record the starting availability (either "on" state) to restore it
    // exactly afterwards — shared seed org, so don't assume which one.
    const select = page.getByRole("combobox", { name: "Compliance availability", exact: true });
    const initial = (await select.inputValue()) as "opt_in" | "default_on";
    expect(["opt_in", "default_on"]).toContain(initial);
    await setOrgModuleAvailability(page, "Compliance", "off");

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
    await setOrgModuleAvailability(page, "Compliance", initial);

    await page.goto("/org-overview");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/overview$/);
    const overviewLink = page.locator(".resource-menu-nav").getByRole("link", { name: "Overview", exact: true });
    await expect(overviewLink).toBeVisible();
    await expect(overviewLink).toHaveAttribute("aria-current", "page");
    await expect(page.locator(".stat-bar")).toBeVisible();
  });
});
