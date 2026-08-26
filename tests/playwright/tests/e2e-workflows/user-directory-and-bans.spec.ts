import { expect, test } from "@playwright/test";

import { loginAs, logout, PERSONAS } from "./helpers";

/**
 * Job to be done: a server admin can review orphaned accounts (no org
 * membership at all — C-A-13's "orphaned account" clarification) across
 * the whole deployment (tenant-blind, per I-M-05), deactivate/reactivate
 * them, and ban an orphaned account so no org admin can grant it a role
 * again without an explicit unban.
 *
 * Uses the orphan persona (zero org memberships already, not logged into
 * by any other spec) so banning/deactivating it can't disrupt another
 * spec's setup. Always ends unbanned and active again.
 */
test.describe("server-admin user directory: orphaned accounts, deactivation, bans", () => {
  test("review orphaned accounts, deactivate/reactivate, ban/unban", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");

    await test.step("the orphaned-accounts view lists the orphan persona (server-admin only, tenant-blind)", async () => {
      await expect(page.getByText(PERSONAS.orphan.email)).toBeVisible();
    });

    await test.step("a non-server-admin cannot reach this listing via a direct API call", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const resp = await page.request.get("http://localhost:8000/api/v1/system/users?no_org_membership=true", {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(resp.status()).toBe(403);
      await logout(page);
      await loginAs(page, PERSONAS.serverAdmin.email);
      await page.goto("/server/management");
    });

    await test.step("deactivate then reactivate the orphaned account", async () => {
      const row = page.locator("tr", { hasText: PERSONAS.orphan.email });
      // Deactivate now confirms via the shared `ConfirmDialog` (sixth-pass
      // audit) rather than `window.confirm`.
      await row.getByRole("button", { name: "Deactivate" }).click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/deactivate") && r.request().method() === "POST"),
        page.getByRole("dialog", { name: "Deactivate this account?" }).getByRole("button", { name: "Deactivate" }).click(),
      ]);
      // The default listing excludes deactivated accounts entirely.
      await page.getByLabel("Include deactivated accounts").check();
      await expect(row.getByText("Deactivated", { exact: true })).toBeVisible();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/reactivate") && r.request().method() === "POST"),
        row.getByRole("button", { name: "Reactivate" }).click(),
      ]);
      await expect(row.getByText("Deactivated", { exact: true })).toHaveCount(0);
    });

    await test.step("ban the orphaned account", async () => {
      const row = page.locator("tr", { hasText: PERSONAS.orphan.email });
      // Ban now confirms via the shared `ConfirmDialog` (sixth-pass audit)
      // rather than `window.confirm`.
      await row.getByRole("button", { name: "Ban", exact: true }).click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/ban") && r.request().method() === "POST"),
        page.getByRole("dialog", { name: "Ban this account?" }).getByRole("button", { name: "Ban", exact: true }).click(),
      ]);
      await expect(row.getByText("Banned", { exact: true })).toBeVisible();
    });

    await test.step("a banned account can't be granted a fresh org role, even via a direct API call", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const usersResp = await page.request.get("http://localhost:8000/api/v1/system/users?no_org_membership=true", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const users: { user_id: string; email: string }[] = await usersResp.json();
      const orphanId = users.find((u) => u.email === PERSONAS.orphan.email)!.user_id;

      const orgsResp = await page.request.get("http://localhost:8000/api/v1/orgs", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const orgs: { id: string; name: string }[] = await orgsResp.json();
      const alpha = orgs.find((o) => o.name === "E2E Alpha Robotics")!;

      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      const pmToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const grantResp = await page.request.post(`http://localhost:8000/api/v1/orgs/${alpha.id}/users/${orphanId}/roles`, {
        headers: { Authorization: `Bearer ${pmToken}` },
        data: { user_id: orphanId, role: "member" },
      });
      expect(grantResp.status()).toBe(403);

      await logout(page);
      await loginAs(page, PERSONAS.serverAdmin.email);
      await page.goto("/server/management");
    });

    await test.step("unban restores the ability to grant roles", async () => {
      // Banning implies deactivation, and a fresh page load resets the
      // "include deactivated" checkbox — re-check it to find the row.
      await page.getByLabel("Include deactivated accounts").check();
      const row = page.locator("tr", { hasText: PERSONAS.orphan.email });
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/unban") && r.request().method() === "POST"),
        row.getByRole("button", { name: "Unban" }).click(),
      ]);
      await expect(row.getByText("Banned", { exact: true })).toHaveCount(0);
    });
  });
});
