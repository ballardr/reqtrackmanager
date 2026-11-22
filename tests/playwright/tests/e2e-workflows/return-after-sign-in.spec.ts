import { expect, test, type Page } from "@playwright/test";

import { PASSWORD, PERSONAS, deleteOrgOnCleanup, installCleanupHook, loginAs, logout, nextTotpCode } from "./helpers";

// Deletes this file's disposable organisation after the test that created it (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/** A page every signed-in account can open, with a query and a hash to prove both are kept. */
const DEEP_LINK = "/preferences/security?from=email#section";

async function expectOnDeepLink(page: Page): Promise<void> {
  await expect(page).toHaveURL(/\/preferences\/security\?from=email#section$/);
}

async function submitSignIn(page: Page, email: string): Promise<void> {
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/**
 * After sign-in the person arrives at the page they were on: a followed link while signed out, a session that ended
 * on a page, the two-factor step, and the administrator-set password change. A deliberate sign-out forgets the page,
 * and a stored address on another site is ignored.
 */
test.describe("return to the page after signing in", () => {
  test("a followed link while signed out opens that page after sign-in, with its query and hash", async ({ page }) => {
    await page.goto(DEEP_LINK);
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText(/continue to the page you requested/)).toHaveCount(0);

    await submitSignIn(page, PERSONAS.memberAlphaBeta.email);
    await expectOnDeepLink(page);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  });

  test("the page is used once: signing in again afterwards uses the landing preference", async ({ page }) => {
    await page.goto(DEEP_LINK);
    await submitSignIn(page, PERSONAS.memberAlphaBeta.email);
    await expectOnDeepLink(page);

    await logout(page);
    await submitSignIn(page, PERSONAS.memberAlphaBeta.email);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await expect(page).not.toHaveURL(/\/preferences\//);
  });

  test("a session that ends on a page returns to it after signing in again", async ({ page }) => {
    await loginAs(page, PERSONAS.memberAlphaBeta.email);
    await page.goto(DEEP_LINK);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    // The client's own reaction to a refused token (`AUTH_UNAUTHORIZED_EVENT`): the session is dead, the page stays put.
    await page.evaluate(() => window.dispatchEvent(new Event("reqtrack:unauthorized")));
    await expect(page).toHaveURL(/\/login$/);

    await submitSignIn(page, PERSONAS.memberAlphaBeta.email);
    await expectOnDeepLink(page);
  });

  test("a deliberate sign-out does not remember the page", async ({ page }) => {
    await loginAs(page, PERSONAS.memberAlphaBeta.email);
    await page.goto(DEEP_LINK);
    await logout(page);
    await expect(page.getByText(/continue to the page you requested/)).toHaveCount(0);

    await submitSignIn(page, PERSONAS.memberAlphaBeta.email);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await expect(page).not.toHaveURL(/\/preferences\//);
  });

  test("an address on another site left in storage is ignored", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => sessionStorage.setItem("reqtrack:return-to", "//evil.example/phish"));
    await submitSignIn(page, PERSONAS.memberAlphaBeta.email);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    expect(new URL(page.url()).hostname).not.toBe("evil.example");
    await expect(page).not.toHaveURL(/evil\.example/);
  });

  test("the administrator-set password change returns to the page after the next sign-in", async ({ page }) => {
    await loginAs(page, PERSONAS.memberAlphaBeta.email);
    await page.goto(DEEP_LINK);
    // As in forced-password-change.spec.ts the account state is supplied by answering `GET /auth/me`; the change
    // itself is answered here too, so the persona's real password is untouched.
    const meMock = async (route: import("@playwright/test").Route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), must_change_password: true } });
    };
    await page.route("**/api/v1/auth/me", meMock);
    await page.route("**/api/v1/auth/change-password", (route) => route.fulfill({ status: 200, json: {} }));
    await page.reload();
    await expect(page.getByRole("heading", { name: "Choose your own password" })).toBeVisible();

    await page.getByLabel(/^Current password/).fill("Given-By-Admin-1!");
    await page.getByLabel(/^New password/).fill("Chosen-By-Person-7!");
    await page.getByLabel(/^Confirm new password/).fill("Chosen-By-Person-7!");
    await page.getByRole("button", { name: "Change password" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.unroute("**/api/v1/auth/me", meMock);
    await submitSignIn(page, PERSONAS.memberAlphaBeta.email);
    await expectOnDeepLink(page);
  });

  test("a two-factor account returns to the page after the code step", async ({ page }) => {
    const suffix = Date.now();
    const userEmail = `e2e-return-2fa-${suffix}@example.com`;
    let secret = "";

    await test.step("create a disposable organisation and a member enrolled in two-factor (setup, via API)", async () => {
      const adminLogin = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      });
      const serverAdminHeaders = { Authorization: `Bearer ${(await adminLogin.json()).access_token}` };
      const org = await (
        await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
          headers: serverAdminHeaders,
          data: { name: `E2E Return 2FA Org ${suffix}` },
        })
      ).json();
      deleteOrgOnCleanup({ id: org.id });
      await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
        headers: serverAdminHeaders,
        data: { email: userEmail, display_name: "E2E Return 2FA User", password: PASSWORD, role: "member" },
      });
      const userLogin = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: userEmail, password: PASSWORD },
      });
      const userHeaders = { Authorization: `Bearer ${(await userLogin.json()).access_token}` };
      const enrol = await page.request.post(`${apiBaseUrl}/api/v1/auth/2fa/enroll`, { headers: userHeaders });
      ({ secret } = await enrol.json());
      const confirm = await page.request.post(`${apiBaseUrl}/api/v1/auth/2fa/status`, {
        headers: userHeaders,
        data: { action: "confirm", code: await nextTotpCode(secret) },
      });
      expect(confirm.ok()).toBe(true);
    });

    await page.goto(DEEP_LINK);
    await expect(page).toHaveURL(/\/login$/);
    await submitSignIn(page, userEmail);
    await expect(page.getByText("Two-factor verification")).toBeVisible();
    await page.getByLabel("Authentication code").fill(await nextTotpCode(secret));
    await page.getByRole("button", { name: "Sign in" }).click();
    await expectOnDeepLink(page);
  });
});
