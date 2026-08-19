import { expect, test } from "@playwright/test";

import { ORG_NAMES, PASSWORD, PERSONAS, ensureTwoFactorSectionExpanded, generateTotpCode } from "./helpers";

const apiBaseUrl = "http://localhost:8000";
const ORG_SLUG = "e2e-2fa-handoff-org";

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
 * Uses the orphan persona (zero org memberships) for the same reason
 * two-factor-auth.spec.ts does — enabling/disabling 2FA here can't leave a
 * later spec's plain loginAs() broken for a shared persona. Org-branded
 * login only affects which login method is offered, not which account is
 * reached (see OrgLoginPage.tsx's own docstring), so the orphan persona
 * logging in via another org's branded page is exactly the real scenario:
 * any global user can use any org's branded login page.
 */
test.describe("org-branded login: 2FA handoff to /login", () => {
  test("a 2FA-enrolled user submitting on the branded page lands on the code-entry step, not a dead end", async ({ page }) => {
    let secret = "";

    await test.step("give an org a slug (setup, via API as its org admin)", async () => {
      await page.goto("/login");
      await page.getByLabel("Email").fill(PERSONAS.orgAdminAlphaBeta.email);
      await page.getByLabel("Password").fill(PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const authHeaders = { Authorization: `Bearer ${token}` };
      const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: authHeaders })).json();
      const alphaOrgId = orgs.find((o: { name: string }) => o.name === ORG_NAMES.alpha).id;

      const resp = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/sso-config`, {
        headers: authHeaders,
        data: { slug: ORG_SLUG, sso_enabled: false, sso_only: false },
      });
      expect(resp.ok()).toBe(true);

      await page.getByRole("button", { name: "Sign out" }).click();
      await page.waitForURL(/\/login$/);
    });

    await test.step("enrol the orphan persona in 2FA via the real UI", async () => {
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

      await page.getByRole("button", { name: "Sign out" }).click();
      await page.waitForURL(/\/login$/);
    });

    await test.step("submitting credentials on the org-branded page hands off to /login's code-entry step", async () => {
      await page.goto(`/login/${ORG_SLUG}`);
      await expect(page.getByRole("heading", { name: ORG_NAMES.alpha })).toBeVisible();
      await page.getByLabel("Email").fill(PERSONAS.orphan.email);
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

    await test.step("disable 2FA again, restoring single-step login for this persona", async () => {
      await page.goto("/preferences");
      await page.getByRole("tab", { name: "Security", exact: true }).click();
      await ensureTwoFactorSectionExpanded(page);
      await page.getByPlaceholder("Enter a current code to disable 2FA.").fill(generateTotpCode(secret));
      await page.getByRole("button", { name: "Disable 2FA" }).click();
      await page.waitForURL(/\/login$/);
    });
  });
});
