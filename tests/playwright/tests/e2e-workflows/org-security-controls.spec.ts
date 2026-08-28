import { expect, test } from "@playwright/test";

import { ensureExpanded, ensureTwoFactorSectionExpanded, generateTotpCode, loginAs, logout, openGroupCard, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup, selectPreferencesGroup, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: an org admin can require 2FA org-wide (blocking every
 * member, including admins, from org/project access until they enrol —
 * the "28-item batch" round in docs/decisions.md), lock a user's display
 * name, filter the member directory (stale / no-2FA / no-project-access),
 * and control whether external, not-yet-member accounts can be added to
 * projects.
 *
 * Uses Gamma so the org-wide 2FA requirement (which blocks every member of
 * the org, including its own admin, from project access until 2FA is
 * enabled) doesn't interfere with Alpha/Beta specs sharing this suite's
 * single-worker run.
 */
test.describe("org security controls: 2FA requirement, display-name lock, member filters", () => {
  test("org-wide 2FA requirement blocks access until enabled; display-name lock; member filters", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);

    await test.step("member directory filters: stale, no-2FA, no-project-access", async () => {
      // Users is its own top-level resource-menu group (2026-08 UX audit's
      // Org Admin restructure; split out of the combined "People" group in
      // a later pass) — a real navigation, so it must be selected before
      // the section is reachable at all.
      await selectOrgAdminGroup(page, "Users");
      await ensureExpanded(page, "Organisation users");
      await page.getByRole("button", { name: "No 2FA" }).click();
      await expect(page.getByText(PERSONAS.orgAdminGamma.email)).toBeVisible();
      await page.getByRole("button", { name: "No 2FA" }).click();

      await page.getByRole("button", { name: "Stale (180+ days)" }).click();
      await page.getByRole("button", { name: "Clear filters" }).click();
    });

    await test.step("lock then unlock a display name", async () => {
      const row = page.locator("tr", { hasText: PERSONAS.orgAdminGamma.email });
      await row.getByRole("button", { name: "Lock display name" }).click();
      await expect(row.getByRole("button", { name: "Unlock display name" })).toBeVisible();
      await row.getByRole("button", { name: "Unlock display name" }).click();
      await expect(row.getByRole("button", { name: "Lock display name" })).toBeVisible();
    });

    let gamma1Id = "";
    await test.step("enabling org-wide 2FA blocks the admin's own project/settings access until they enrol", async () => {
      // 2FA/self-signup/external-user-policy live in the "Security"
      // top-level resource-menu group (2026-08 UX audit's Org Admin
      // restructure, later split further from a combined "Integrations &
      // security" group) — a real navigation, so it must be selected
      // before the card is reachable at all.
      await selectOrgAdminGroup(page, "Security");
      await ensureExpanded(page, "Security");
      await page.getByRole("switch", { name: "Require two-factor authentication" }).click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save security settings" }).click(),
      ]);

      await page.goto("/projects");
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const projectsResp = await page.request.get("http://localhost:8000/api/v1/projects?archived=false", {
        headers: { Authorization: `Bearer ${token}` },
      });
      // The cross-org project *list* deliberately isn't gated per-org (a
      // user could belong to other, non-2FA-required orgs too) — only
      // project-*specific* endpoints enforce a single org's requirement.
      gamma1Id = (await projectsResp.json()).find((p: { name: string }) => p.name === PROJECT_NAMES.gamma1).id;

      // Wait for the project-detail fetch this click triggers (which
      // resolves 403, driving the "2FA required" UI) before asserting on
      // its result — a bare click() plus an immediate expect() relies
      // purely on the assertion's own timeout to outlast the navigation +
      // network round trip, the same race already found and fixed twice
      // elsewhere in this pass (project-history.spec.ts,
      // requirements-and-cr-filters.spec.ts).
      await Promise.all([
        page.waitForResponse((r) => r.url().includes(`/api/v1/projects/${gamma1Id}`) && r.request().method() === "GET"),
        page.getByText(PROJECT_NAMES.gamma1).click(),
      ]);
      // This step (via toggleDisplayNameLock's own reload()) is exactly
      // what surfaced a real OrgAdminPage.tsx race, not a test-timing
      // issue — see docs/decisions.md: a slow, unawaited reload() from
      // the *previous* test.step could still be in flight here and
      // clobber this toggle's local state back to its last-saved value
      // right before Save is clicked, so the PUT below silently sent
      // require_2fa: false. Fixed at the source (advancedDirtyRef); this
      // assertion needs no special timeout now that the underlying race
      // is closed.
      await expect(page.getByText(/2FA|two-factor/i).first()).toBeVisible();
    });

    await test.step("a direct API call against the specific project is also blocked, not just the UI", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const resp = await page.request.get(`http://localhost:8000/api/v1/projects/${gamma1Id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(resp.status()).toBe(403);
    });

    let recoverySecret = "";
    await test.step("the blocked admin's self-service way out: /auth/2fa isn't org-scoped, so they can still enrol themselves", async () => {
      await page.goto("/preferences");
      await selectPreferencesGroup(page, "Security");
      await ensureTwoFactorSectionExpanded(page);
      const [enrollResponse] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/2fa/enroll") && r.request().method() === "POST"),
        page.getByRole("switch", { name: "Enable 2FA" }).click(),
      ]);
      ({ secret: recoverySecret } = await enrollResponse.json());
      await page.getByPlaceholder("Confirm code").fill(generateTotpCode(recoverySecret));
      await page.getByRole("button", { name: "Confirm code" }).click();
      await expect(page.getByText("Enabled", { exact: true })).toBeVisible();
    });

    await test.step("2FA now enabled, access is restored and the org-wide requirement can be turned back off, cleaning up for later specs", async () => {
      await page.goto("/projects");
      await page.getByText(PROJECT_NAMES.gamma1).click();
      await expect(page.getByText(PROJECT_NAMES.gamma1)).toBeVisible();

      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Security");
      await ensureExpanded(page, "Security");
      await page.getByRole("switch", { name: "Require two-factor authentication" }).click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save security settings" }).click(),
      ]);

      // Also disable this admin's own personal 2FA again, since it was
      // only enrolled to demonstrate/exercise the self-service recovery
      // path above — leaving it on would break this persona's plain
      // loginAs() in any spec that runs after this one.
      await page.goto("/preferences");
      await selectPreferencesGroup(page, "Security");
      await ensureTwoFactorSectionExpanded(page);
      await page.getByPlaceholder("Enter a current code to disable 2FA.").fill(generateTotpCode(recoverySecret));
      await page.getByRole("button", { name: "Disable 2FA" }).click();
      // Disabling 2FA bumps token_version server-side (same as a password
      // change) to invalidate the current session's token immediately —
      // the frontend's AUTH_UNAUTHORIZED_EVENT handling logs this session
      // out on its very next request rather than showing "Not enabled" in
      // place, so log back in (with a plain password now — 2FA is off)
      // before continuing.
      await page.waitForURL(/\/login$/);
      await loginAs(page, PERSONAS.orgAdminGamma.email);
    });

    await test.step("external-user-on-project policy: 'anyone' allows adding a not-yet-member by email", async () => {
      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Security");
      await ensureExpanded(page, "Security");
      await page.getByLabel("External users on projects").selectOption("anyone");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save security settings" }).click(),
      ]);

      await page.goto("/projects");
      await page.getByText(PROJECT_NAMES.gamma1).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Project groups");
      // Groups now render collapsed by default (2026-08 UX audit
      // "Directories at scale") — expand "Members" specifically before its
      // own add-member input is reachable at all.
      await openGroupCard(page, "Members");
      const outsideEmail = `e2e-external-${Date.now()}@example.com`;
      await page.getByPlaceholder("Type a name to add, or an email to invite…").last().fill(outsideEmail);
      // A brand-new email with no account anywhere shows an "Invite"
      // option (not "Add"), per UserAutocomplete's existing/new distinction.
      await page.getByText(`Invite ${outsideEmail}`, { exact: true }).click();
      await expect(page.getByText(/invite email was sent/i).first()).toBeVisible();
    });
  });
});
