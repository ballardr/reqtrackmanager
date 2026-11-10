import { expect, test } from "@playwright/test";

import { PERSONAS, loginAs } from "./e2e-workflows/helpers";

/**
 * An account whose password an administrator typed (`must_change_password`) sees only the change screen. The e2e
 * stack runs with the deployment setting off (its seeds sign in as typed-password accounts), so the account state is
 * supplied by answering `GET /auth/me` for this page; the server-side refusal of every other request is covered by the
 * backend tests (`test_forced_password_change.py`).
 */
test("an account that must change its password sees only the change screen, and can sign out", async ({ page }) => {
  await loginAs(page, PERSONAS.memberAlphaBeta.email);
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), must_change_password: true } });
  });
  await page.reload();

  await expect(page.getByRole("heading", { name: "Choose your own password" })).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);

  await page.getByLabel(/^Current password/).fill("Given-By-Admin-1!");
  await page.getByLabel(/^New password/).fill("Chosen-By-Person-7!");
  await page.getByLabel(/^Confirm new password/).fill("Different-Password-8!");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByRole("alert")).toContainText("The two passwords do not match.");

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
});
