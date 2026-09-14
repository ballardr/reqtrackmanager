import { expect, test } from "@playwright/test";

import { PASSWORD, ensureTwoFactorSectionExpanded, generateTotpCode, selectPreferencesGroup } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: a user can enrol in TOTP two-factor authentication
 * (C-U-14), scanning a real QR-code-backed secret (captured from the
 * enroll response rather than parsing the rendered QR image) and
 * confirming with a live computed code; login then requires a second
 * step; and 2FA can be disabled again with a fresh code.
 *
 * Uses a fresh, disposable, zero-org-membership user — created via the API
 * then immediately made to leave via `DELETE .../membership`, the same
 * recipe backend/scripts/seed_e2e_dataset.py itself uses to construct
 * PERSONAS.orphan — rather than the orphan persona itself, so
 * enabling/disabling 2FA here can't collide with org-login-2fa-handoff.
 * spec.ts or user-directory-and-bans.spec.ts also touching orphan's
 * session/account state concurrently (Phase 1, docs/platform-review-2026-
 * 09-plan.md). The test always ends with 2FA disabled again, but that's
 * now for tidiness rather than to avoid breaking a shared persona's later
 * plain `loginAs()`.
 */
test.describe("two-factor authentication enrollment", () => {
  test("enrol, log in with a code, then disable", async ({ page }) => {
    let secret = "";
    const suffix = Date.now();
    const userEmail = `e2e-2fa-standalone-${suffix}@example.com`;

    await test.step("create a fresh, disposable, zero-org-membership user (setup, via API)", async () => {
      const serverAdminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      });
      const serverAdminToken = (await serverAdminLoginResp.json()).access_token;
      const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };

      const org = await (
        await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
          headers: serverAdminHeaders, data: { name: `E2E 2FA Setup Org ${suffix}` },
        })
      ).json();
      await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
        headers: serverAdminHeaders,
        data: { email: userEmail, display_name: "E2E 2FA Standalone User", password: PASSWORD, role: "member" },
      });
      const userLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: userEmail, password: PASSWORD },
      });
      const userToken = (await userLoginResp.json()).access_token;
      await page.request.delete(`${apiBaseUrl}/api/v1/orgs/${org.id}/membership`, {
        headers: { Authorization: `Bearer ${userToken}` },
      });
    });

    await test.step("enrol via the real UI, capturing the secret from the enroll response", async () => {
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
    });

    await test.step("logging out and back in now requires a second, code-entry step", async () => {
      await page.getByRole("button", { name: "Sign out" }).click();
      await page.waitForURL(/\/login$/);

      await page.getByLabel("Email").fill(userEmail);
      await page.getByLabel("Password").fill(PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByText("Two-factor verification")).toBeVisible();
      // A stale/wrong code is rejected.
      await page.getByLabel("Authentication code").fill("000000");
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByText("Two-factor verification")).toBeVisible();

      await page.getByLabel("Authentication code").fill(generateTotpCode(secret));
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    });

    await test.step("disable 2FA again with a fresh code, restoring single-step login", async () => {
      await page.goto("/preferences");
      await selectPreferencesGroup(page, "Security");
      await ensureTwoFactorSectionExpanded(page);
      await page.getByPlaceholder("Enter a current code to disable 2FA.").fill(generateTotpCode(secret));
      await page.getByRole("button", { name: "Disable 2FA" }).click();
      // Disabling 2FA bumps token_version server-side (same as a password
      // change) to invalidate the current session's token immediately —
      // the frontend's AUTH_UNAUTHORIZED_EVENT handling then logs this
      // session out on its very next request, rather than the page just
      // showing "Not enabled" in place.
      await page.waitForURL(/\/login$/);
    });

    await test.step("logging in again now only takes a single step, confirming 2FA is really off", async () => {
      await page.getByLabel("Email").fill(userEmail);
      await page.getByLabel("Password").fill(PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    });
  });
});
