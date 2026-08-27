import { expect, test } from "@playwright/test";

/**
 * UX review: the platform login page (no org slug) showed no branding
 * logo/title above the login form, unlike OrgLoginPage which already had
 * one. Both now render `LoginBrandHeader` — assert the title is visible
 * above the "Sign in" heading on the plain /login page.
 */
test("login page shows branding title above the sign-in form", async ({ page }) => {
  await page.goto("/login");
  const card = page.locator("form.card");
  await expect(card.getByText("ReqTrackManager")).toBeVisible();
  await expect(card.getByRole("heading", { name: "Sign in" })).toBeVisible();
});
