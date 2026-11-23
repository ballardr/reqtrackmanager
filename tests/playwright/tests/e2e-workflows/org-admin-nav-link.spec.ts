import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * /orgs (the only path to organisation administration) has an "Organisation settings" nav-rail link for every
 * organisation admin. This persona belongs to two organisations (Alpha, Beta), so /orgs shows the directory list
 * rather than redirecting to a single organisation's admin page.
 */
test("the nav rail links to /orgs, showing every org the user belongs to", async ({ page }) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.getByRole("link", { name: "Organisation settings" }).click();
  await expect(page).toHaveURL(/\/orgs$/);
  await expect(page.getByRole("link", { name: ORG_NAMES.alpha })).toBeVisible();
  await expect(page.getByRole("link", { name: ORG_NAMES.beta })).toBeVisible();
});

/**
 * "Organisation settings" is a personal membership list, not the server-admin platform-wide directory
 * (`GET /server/organisations`). The page calls `GET /orgs?mine=true`, because the bare `GET /orgs` returns every
 * organisation for a server admin. `e2e-serveradmin@example.com` is seeded as a server admin with no organisation
 * memberships (`seed_e2e_dataset.py`), so the expected result is the empty state.
 */
test("a server admin with no org memberships sees an empty 'Organisation settings', not every org on the server", async ({
  page,
}) => {
  await loginAs(page, PERSONAS.serverAdmin.email);
  await page.getByRole("link", { name: "Organisation settings" }).click();
  await expect(page).toHaveURL(/\/orgs$/);
  await expect(page.getByText("You do not belong to any organisations yet.")).toBeVisible();
  await expect(page.getByRole("link", { name: ORG_NAMES.alpha })).not.toBeVisible();
  await expect(page.getByRole("link", { name: ORG_NAMES.beta })).not.toBeVisible();
  await expect(page.getByRole("link", { name: ORG_NAMES.gamma })).not.toBeVisible();
});
