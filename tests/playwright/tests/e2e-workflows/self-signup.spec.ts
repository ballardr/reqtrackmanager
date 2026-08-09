import { expect, test } from "@playwright/test";

/**
 * End-to-end proof of public self-signup (`ServerSettings.signup_mode`,
 * `routers/auth.py::signup`): the `/signup` form is unreachable when
 * disabled, works with no organisation joined under `always_on`, and
 * auto-joins a matching organisation under `org_specified` — only when
 * that organisation has actually opted in (`allow_self_signup`), not from
 * a configured domain alone. See docs/decisions.md's "Self-signup,
 * invites, and SSO" entry.
 *
 * Configures the server-wide mode and org settings via API first (setup),
 * then drives the actual signup form through the browser.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";
const apiBaseUrl = "http://localhost:8000";

async function adminToken(page: import("@playwright/test").Page): Promise<string> {
  const resp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  return (await resp.json()).access_token;
}

async function setSignupMode(page: import("@playwright/test").Page, token: string, mode: string) {
  const resp = await page.request.put(`${apiBaseUrl}/api/v1/system/signup-config`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { signup_mode: mode },
  });
  expect(resp.ok()).toBeTruthy();
}

test.describe("public self-signup", () => {
  test.afterAll(async ({ browser }) => {
    // Global setting — reset it so later specs in the same run see the
    // default (disabled) sign-up page, not whatever this file left behind.
    const page = await browser.newPage();
    const token = await adminToken(page);
    await setSignupMode(page, token, "disabled");
    await page.close();
  });

  test("signup form is unreachable when disabled", async ({ page }) => {
    const token = await adminToken(page);
    await setSignupMode(page, token, "disabled");

    await page.goto("/login");
    await expect(page.getByRole("link", { name: "Sign up" })).toHaveCount(0);

    await page.goto("/signup");
    await expect(page.getByText("Public sign-up is not available")).toBeVisible();
  });

  test("always_on mode creates an account with no organisation", async ({ page }) => {
    const token = await adminToken(page);
    await setSignupMode(page, token, "always_on");

    const email = `e2e-selfsignup-${Date.now()}@example.com`;
    await page.goto("/login");
    await page.getByRole("link", { name: "Sign up" }).click();
    await expect(page).toHaveURL(/\/signup$/);

    await page.getByLabel("Display name").fill("Self Signup Test");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("SelfSignup123!");
    await page.getByRole("button", { name: "Create account" }).click();

    // No org membership yet -> lands on the project list with nothing to
    // show, not an error — confirms the account was created and logged in.
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    const newToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const orgsResp = await page.request.get(`${apiBaseUrl}/api/v1/orgs`, {
      headers: { Authorization: `Bearer ${newToken}` },
    });
    expect(await orgsResp.json()).toEqual([]);
  });

  test("org_specified mode joins only an org that opted in with a matching domain", async ({ page }) => {
    const adminTok = await adminToken(page);
    const orgName = `E2E Signup Domain Org ${Date.now()}`;
    const domain = `e2esignup${Date.now()}.example.com`;

    const orgResp = await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: { Authorization: `Bearer ${adminTok}` },
      data: { name: orgName },
    });
    const org = await orgResp.json();
    const orgAdminEmail = `orgadmin-${Date.now()}@example.com`;
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: { Authorization: `Bearer ${adminTok}` },
      data: { email: orgAdminEmail, display_name: "Org Admin", password: "OrgAdmin123!", role: "org_admin" },
    });
    const orgAdminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: orgAdminEmail, password: "OrgAdmin123!" },
    });
    const orgAdminToken = (await orgAdminLoginResp.json()).access_token;
    const settingsResp = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/advanced-settings`, {
      headers: { Authorization: `Bearer ${orgAdminToken}` },
      data: { allow_self_signup: true, auto_accept_email_domain: domain },
    });
    expect(settingsResp.ok()).toBeTruthy();

    await setSignupMode(page, adminTok, "org_specified");

    const newUserEmail = `newbie@${domain}`;
    await page.goto("/signup");
    await page.getByLabel("Display name").fill("New Domain User");
    await page.getByLabel("Email").fill(newUserEmail);
    await page.getByLabel("Password").fill("NewDomain123!");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    const newToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const orgsResp = await page.request.get(`${apiBaseUrl}/api/v1/orgs`, {
      headers: { Authorization: `Bearer ${newToken}` },
    });
    const orgs = await orgsResp.json();
    expect(orgs.some((o: { id: string }) => o.id === org.id)).toBe(true);
  });
});
