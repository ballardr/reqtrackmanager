import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * /orgs (the only path to org administration) previously had no nav-rail
 * entry point for anyone but a server admin — an ordinary org admin had no
 * way there beyond a bookmark or a stale link they'd clicked once (2026-08
 * UX audit finding, corrected from an earlier draft that misdiagnosed this
 * as a missing "org switcher" — see docs/decisions.md). Fixed with a plain
 * "My organisations" nav-rail link. This persona belongs to two orgs
 * (Alpha, Beta), so /orgs shows the directory list rather than
 * auto-redirecting straight to a single org's admin page.
 */
test("the nav rail links to /orgs, showing every org the user belongs to", async ({ page }) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.getByRole("link", { name: "My organisations" }).click();
  await expect(page).toHaveURL(/\/orgs$/);
  await expect(page.getByRole("link", { name: ORG_NAMES.alpha })).toBeVisible();
  await expect(page.getByRole("link", { name: ORG_NAMES.beta })).toBeVisible();
});
