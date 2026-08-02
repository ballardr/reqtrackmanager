import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * Job to be done: as a server administrator who is not a member of any
 * organisation, I can see the deployment-wide Server Management console
 * (every org on the system, for oversight/support purposes) but I cannot
 * see or act on any organisation's or project's actual content — server
 * admin is a narrow, cross-tenant management role, not a backdoor into
 * tenant data (see backend/app/services/rbac.py's documented carve-outs).
 *
 * Persona: ServerAdminOnly (zero org memberships — see
 * backend/scripts/seed_e2e_dataset.py for how this was constructed).
 */
test.describe("server admin with zero org memberships", () => {
  test("sees Server Management + all orgs, but no project/org content", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);

    await test.step("Server Management section lists every org on the deployment", async () => {
      await expect(page.getByText("Server Management")).toBeVisible();
      await page.getByRole("link", { name: "Organisations" }).last().click();
      await expect(page).toHaveURL(/\/server\/organisations$/);
      await expect(page.getByText(ORG_NAMES.alpha)).toBeVisible();
      await expect(page.getByText(ORG_NAMES.beta)).toBeVisible();
      await expect(page.getByText(ORG_NAMES.gamma)).toBeVisible();
    });

    await test.step("Global Projects view is empty (no project role anywhere)", async () => {
      await page.getByRole("link", { name: "Projects", exact: true }).click();
      await expect(page.getByText("No projects to show.")).toBeVisible();
    });

    await test.step("opening an org's admin page does not reveal its content", async () => {
      await page.getByRole("link", { name: "Organisations", exact: true }).first().click();
      await page.getByText(ORG_NAMES.alpha).click();
      // Org details alone are server-admin-visible (GET /orgs/{id} has a
      // documented bypass), but users/groups/resources are not — the page
      // fetches all of these together and never renders past the loading
      // spinner once any of them 403s, so Alpha's actual admin content
      // (user list, groups) never appears.
      await expect(page.getByText(ORG_NAMES.alpha, { exact: true })).toHaveCount(0);
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
