import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureTwoFactorSectionExpanded, nextTotpCode, installCleanupHook, PASSWORD, selectPreferencesGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/**
 * A 2FA challenge on an org-branded login page falls through to the plain /login flow rather than duplicating the
 * code-entry form. The submit handler navigates to /login with the issued challenge token in router state, so
 * LoginPage opens on the code-entry step instead of asking for email and password again. This proves the handoff
 * end to end.
 *
 * Uses a disposable organisation and admin plus a standalone zero-membership user (created through the API, then
 * left via `DELETE .../membership`, as backend/scripts/seed_e2e_dataset.py constructs PERSONAS.orphan). Mutating
 * Alpha's sso-config/slug or reusing the shared orphan persona could collide with other specs under concurrency
 * (e.g. two-factor-auth.spec.ts). Org-branded login only affects which login method is offered, not which account
 * is reached (see OrgLoginPage.tsx), so a disposable organisation's branded page is as representative as Alpha's.
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
      deleteOrgOnCleanup({ id: org.id });
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

      await page.getByLabel("Confirm code").fill(await nextTotpCode(secret));
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

      // Without the handoff nothing here becomes true: the button stops submitting and the branded email/password form
      // stays on screen with no error.
      await page.waitForURL(/\/login$/);
      await expect(page.getByText("Two-factor verification")).toBeVisible();

      await page.getByLabel("Authentication code").fill(await nextTotpCode(secret));
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    });

    await test.step("disable 2FA again, restoring single-step login for this now-disposable user", async () => {
      await page.goto("/preferences");
      await selectPreferencesGroup(page, "Security");
      await ensureTwoFactorSectionExpanded(page);
      await page.getByLabel("Authenticator code").fill(await nextTotpCode(secret));
      await page.getByRole("button", { name: "Disable 2FA" }).click();
      await page.waitForURL(/\/login$/);
    });
  });
});
