import { expect, test } from "@playwright/test";

import { PASSWORD, PERSONAS, ensureTwoFactorSectionExpanded, generateTotpCode } from "./helpers";

/**
 * Job to be done: a user can enrol in TOTP two-factor authentication
 * (C-U-14), scanning a real QR-code-backed secret (captured from the
 * enroll response rather than parsing the rendered QR image) and
 * confirming with a live computed code; login then requires a second
 * step; and 2FA can be disabled again with a fresh code.
 *
 * Uses the orphan persona (zero org memberships, not logged into by any
 * other spec's shared setup) specifically so enabling/disabling 2FA here
 * can't leave a later spec's plain `loginAs()` broken. The test always
 * ends with 2FA disabled again, restoring single-step login for this
 * persona regardless of run order.
 */
test.describe("two-factor authentication enrollment", () => {
  test("enrol, log in with a code, then disable", async ({ page }) => {
    let secret = "";

    await test.step("enrol via the real UI, capturing the secret from the enroll response", async () => {
      await page.goto("/login");
      await page.getByLabel("Email").fill(PERSONAS.orphan.email);
      await page.getByLabel("Password").fill(PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

      await page.goto("/preferences");
      await page.getByRole("tab", { name: "Security", exact: true }).click();
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

      await page.getByLabel("Email").fill(PERSONAS.orphan.email);
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
      await page.getByRole("tab", { name: "Security", exact: true }).click();
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
      await page.getByLabel("Email").fill(PERSONAS.orphan.email);
      await page.getByLabel("Password").fill(PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    });
  });
});
