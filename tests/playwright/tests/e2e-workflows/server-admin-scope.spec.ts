import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * Job to be done: as a server administrator who is not a member of any organisation, I can see the deployment-wide
 * Server Management console (every org, for oversight and support) but cannot see or act on any organisation's or
 * project's content: server admin is a narrow, cross-tenant management role, not a backdoor into tenant data (see
 * backend/app/services/rbac.py's documented carve-outs).
 *
 * Persona: ServerAdminOnly (zero org memberships; see backend/scripts/seed_e2e_dataset.py).
 */
test.describe("server admin with zero org memberships", () => {
  test("sees Server Management + all orgs, but no project/org content", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);

    await test.step("Administration section lists every org on the deployment", async () => {
      await expect(page.getByText("Administration")).toBeVisible();
      await page.getByRole("link", { name: "Organisations", exact: true }).click();
      await expect(page).toHaveURL(/\/server\/organisations$/);
      await expect(page.getByText(ORG_NAMES.alpha)).toBeVisible();
      await expect(page.getByText(ORG_NAMES.beta)).toBeVisible();
      await expect(page.getByText(ORG_NAMES.gamma)).toBeVisible();
    });

    await test.step("Global Projects view is empty (no project role anywhere)", async () => {
      await page.getByRole("link", { name: "Projects", exact: true }).click();
      await expect(page.getByText("No projects to show.")).toBeVisible();
    });

    await test.step("opening an org's admin page shows a degraded view, not its content", async () => {
      // Reached via the server-wide org directory (`/server/organisations`), the nav-linked path for a server admin to any
      // org's admin page regardless of membership, not `/orgs`: that page backs the nav rail's personal "My organisations"
      // link and is scoped to the caller's memberships (`GET /orgs?mine=true`), so a zero-membership server admin sees the
      // same empty state as anyone else with no organisations.
      await page.getByRole("link", { name: "Organisations", exact: true }).click();
      // Style guide "Pattern: action menu" — the row's Edit/Disable-Enable/
      // Delete buttons now live behind one `ActionMenu` kebab trigger
      // (ServerOrganisationsPage.tsx), not a standalone link.
      await page.getByRole("button", { name: `${ORG_NAMES.alpha} actions` }).click();
      await expect(page.getByRole("menu", { name: `${ORG_NAMES.alpha} actions` })).toBeVisible();
      await page.getByRole("menuitem", { name: "Administration" }).click();
      // Org details alone are server-admin-visible (GET /orgs/{id} has a documented bypass): the degraded view shows the
      // org's name so the admin knows which org it is before deciding to join/bootstrap it. Users, groups and resources
      // are not: the full page's bundle of those calls returns 403 as a whole, so Alpha's admin content never appears,
      // only the "not a member" carve-out actions (see docs/decisions.md's "Organisation disable and hard delete").
      await expect(page.getByRole("heading", { name: ORG_NAMES.alpha, exact: true })).toBeVisible();
      await expect(page.getByText("You are not a member of this organisation")).toBeVisible();
      await expect(page.getByRole("heading", { name: "Users" })).toHaveCount(0);
    });

    await test.step("a raw API call against org content still 403s (not just a hidden UI element)", async () => {
      const orgsResp = await page.request.get("http://localhost:8000/api/v1/orgs", {
        headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("reqtrack_token"))}` },
      });
      const orgs = await orgsResp.json();
      const alpha = orgs.find((o: { name: string }) => o.name === ORG_NAMES.alpha);
      const usersResp = await page.request.get(`http://localhost:8000/api/v1/orgs/${alpha.id}/users`, {
        headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("reqtrack_token"))}` },
      });
      expect(usersResp.status()).toBe(403);
    });
  });
});
