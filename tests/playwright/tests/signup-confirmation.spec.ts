import { expect, test } from "@playwright/test";

/**
 * A deployment that asks for the email address to be confirmed answers a public sign-up with no session and tells the
 * person to check their email; the link in the email opens the confirmation page. The e2e stack has the requirement
 * off (the suite signs up and uses accounts at once), so the server's answers are supplied for these pages; the
 * server-side behaviour is covered by `backend/tests/test_email_confirmation.py`.
 */
test("sign-up asks the person to check their email, and the link confirms the address", async ({ page }) => {
  await page.route("**/api/v1/system/signup-config", (route) =>
    route.fulfill({ json: { signup_mode: "always_on", self_signup_organizations: [] } }),
  );
  await page.route("**/api/v1/auth/signup", (route) =>
    route.fulfill({ status: 202, json: { confirmation_required: true, message: "Check your email." } }),
  );
  await page.route("**/api/v1/auth/confirm-email", (route) => route.fulfill({ status: 204, body: "" }));

  await page.goto("/signup");
  await page.getByLabel(/^Display name/).fill("Newcomer");
  await page.getByLabel(/^Email/).fill("newcomer@example.com");
  await page.getByLabel(/^Password/).fill("Own-Choice-Password-3!");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();

  await page.goto("/confirm-email#token=abc123abc123abc123abc123");
  await expect(page.getByText("Your email address is confirmed. You can sign in now.")).toBeVisible();
  await expect(page).toHaveURL(/\/confirm-email$/); // the secret is gone from the address bar
});
