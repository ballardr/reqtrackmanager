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

/**
 * "My organisations" is a *personal* membership list, not the server-admin
 * platform-wide directory `GET /server/organisations` already covers
 * separately — a real bug found during a first-pass UX review: this page
 * called the bare `GET /orgs`, which deliberately returns every org on the
 * deployment for a server admin (I-M-05's platform-wide console view), so
 * a server admin saw the entire server's org list here regardless of their
 * own membership. Fixed by switching to `GET /orgs?mine=true`, the same
 * membership-scoped opt-out `ProjectListPage`'s own org filter already
 * uses. `e2e-serveradmin@example.com` is seeded specifically as a server
 * admin with zero real org memberships (`seed_e2e_dataset.py`), so the
 * correct behaviour here is the empty state, not the full org list.
 */
test("a server admin with no org memberships sees an empty 'My organisations', not every org on the server", async ({
  page,
}) => {
  await loginAs(page, PERSONAS.serverAdmin.email);
  await page.getByRole("link", { name: "My organisations" }).click();
  await expect(page).toHaveURL(/\/orgs$/);
  await expect(page.getByText("You don't belong to any organisations yet.")).toBeVisible();
  await expect(page.getByRole("link", { name: ORG_NAMES.alpha })).not.toBeVisible();
  await expect(page.getByRole("link", { name: ORG_NAMES.beta })).not.toBeVisible();
  await expect(page.getByRole("link", { name: ORG_NAMES.gamma })).not.toBeVisible();
});
