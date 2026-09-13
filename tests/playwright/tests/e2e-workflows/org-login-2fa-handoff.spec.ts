import { expect, test } from "@playwright/test";

import { PASSWORD, ensureTwoFactorSectionExpanded, generateTotpCode, selectPreferencesGroup } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * OrgLoginPage's own code comment claims a 2FA challenge on an org-branded
 * login page "falls through to the plain /login flow rather than
 * duplicating the code-entry form" — but until this pass the submit handler
 * only ever branched on the non-2FA case, so a 2FA-enrolled user submitting
 * correct credentials on a branded page hit a silent dead end: the button
 * stopped spinning and nothing else happened, no redirect, no error.
 *
 * Fixed by actually navigating to /login with the already-issued challenge
 * token in router state, so LoginPage opens straight on the code-entry step
 * instead of asking for email/password again. This proves the handoff
 * works end to end, not just that the code compiles.
 *
 * Uses a brand-new, disposable organisation + admin + a standalone,
 * zero-org-membership user — created via the API, then immediately left
 * via `DELETE .../membership`, mirroring exactly how
 * backend/scripts/seed_e2e_dataset.py itself constructs PERSONAS.orphan —
 * rather than mutating the shared Alpha org's sso-config/slug in place and
 * reusing the shared orphan persona. Both were previously safe only
 * because this suite ran single-worker/serial; under real concurrency
 * (Phase 1, docs/platform-review-2026-09-plan.md) either could collide
 * with another spec touching Alpha's SSO config or orphan's 2FA/session
 * state (e.g. two-factor-auth.spec.ts). Org-branded login only affects
 * which login method is offered, not which account is reached (see
 * OrgLoginPage.tsx's own docstring), so a disposable org's branded page is
 * exactly as representative of the real scenario as Alpha's would be: any
 * global user can use any org's branded login page.
 */
test.describe("org-branded login: 2FA handoff to /login", () => {
  test("a 2FA-enrolled user submitting on the branded page lands on the code-entry step, not a dead end", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E 2FA Handoff Org ${suffix}`;
    const orgSlug = `e2e-2fa-handoff-org-${suffix}`;
    const orgAdminEmail = `e2e-2fa-handoff-admin-${suffix}@example.com`;
    const userEmail = `e2e-2fa-handoff-user-${suffix}@example.com`;
    let secret = "";

    await test.step("create a disposable, slugged org and a standalone, zero-membership user (setup, via API)", async () => {
      const serverAdminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      });
      const serverAdminToken = (await serverAdminLoginResp.json()).access_token;
      const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };

      const org = await (
        await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverAdminHeaders, data: { name: orgName } })
      ).json();
      await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
        headers: serverAdminHeaders,
        data: { email: orgAdminEmail, display_name: "E2E 2FA Handoff Admin", password: PASSWORD, role: "org_admin" },
      });

      const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: orgAdminEmail, password: PASSWORD },
      });
      const adminToken = (await adminLoginResp.json()).access_token;
      const adminHeaders = { Authorization: `Bearer ${adminToken}` };

      const resp = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/sso-config`, {
        headers: adminHeaders,
        data: { slug: orgSlug, sso_enabled: false, sso_only: false },
      });
      expect(resp.ok()).toBe(true);

      // A standalone user with zero org memberships, created then made to
      // leave immediately — the same recipe seed_e2e_dataset.py itself
      // uses to construct PERSONAS.orphan.
      await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
        headers: adminHeaders,
        data: { email: userEmail, display_name: "E2E 2FA Handoff User", password: PASSWORD, role: "member" },
      });
      const userLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: userEmail, password: PASSWORD },
      });
      const userToken = (await userLoginResp.json()).access_token;
      await page.request.delete(`${apiBaseUrl}/api/v1/orgs/${org.id}/membership`, {
        headers: { Authorization: `Bearer ${userToken}` },
      });
    });

    await test.step("enrol the standalone user in 2FA via the real UI", async () => {
      await page.goto("/login");
      await page.getByLabel("Email").fill(userEmail);
      await page.getByLabel("Password").fill(PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

      await page.goto("/preferences");
      await selectPreferencesGroup(page, "Security");
      await ensureTwoFactorSectionExpanded(page);

      const [enrollResponse] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/2fa/enroll") && r.request().method() === "POST"),
        page.getByRole("switch", { name: "Enable 2FA" }).click(),
      ]);
      ({ secret } = await enrollResponse.json());
      expect(secret).toBeTruthy();

      await page.getByPlaceholder("Confirm code").fill(generateTotpCode(secret));
      await page.getByRole("button", { name: "Confirm code" }).click();
      await expect(page.getByText("Enabled", { exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Sign out" }).click();
      await page.waitForURL(/\/login$/);
    });

    await test.step("submitting credentials on the org-branded page hands off to /login's code-entry step", async () => {
      await page.goto(`/login/${orgSlug}`);
      await expect(page.getByRole("heading", { name: orgName })).toBeVisible();
      await page.getByLabel("Email").fill(userEmail);
      await page.getByLabel("Password").fill(PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();

      // The dead end this test guards against: before the fix, nothing here
      // ever became true — the button just stopped submitting and the
      // branded email/password form stayed on screen with no indication
      // anything was wrong.
      await page.waitForURL(/\/login$/);
      await expect(page.getByText("Two-factor verification")).toBeVisible();

      await page.getByLabel("Authentication code").fill(generateTotpCode(secret));
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    });

    await test.step("disable 2FA again, restoring single-step login for this now-disposable user", async () => {
      await page.goto("/preferences");
      await selectPreferencesGroup(page, "Security");
      await ensureTwoFactorSectionExpanded(page);
      await page.getByPlaceholder("Enter a current code to disable 2FA.").fill(generateTotpCode(secret));
      await page.getByRole("button", { name: "Disable 2FA" }).click();
      await page.waitForURL(/\/login$/);
    });
  });
});
