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

    await test.step("the filter panel renders as a full-width bar above the table, not a cramped sidebar (follow-up UX fix)", async () => {
      const filterPanel = page.locator(".filter-panel-top");
      const table = page.getByRole("table");
      await expect(filterPanel).toBeVisible();
      await expect(table).toBeVisible();
      const panelBox = await filterPanel.boundingBox();
      // Pre-existing bug found running the full suite together (unrelated
      // to any of the follow-up UX batch's 7 PRs — this file and
      // `DirectoryTable.tsx`/`ServerManagementPage.tsx` are all untouched
      // by that batch): the server admin's Users table has enough columns
      // that at the suite's default 1280px viewport it needs its own
      // internal horizontal scroll (`DirectoryTable.tsx` wraps every
      // `<table>` in an unnamed `overflow-x: auto` `<div>`). `<table>`'s
      // own `boundingBox()` reports its full, unclipped *content* width
      // (wider than the panel above it) rather than the visible width of
      // that scroll wrapper — a false positive for "narrower than the
      // panel" that has nothing to do with the actual page layout, which
      // is correct (this table's own scroll wrapper is exactly as wide as
      // the filter panel, confirmed live). Measuring the scroll wrapper
      // (the table's immediate parent) instead of the table element
      // itself matches what a viewer actually sees.
      const tableBox = await table.locator("xpath=..").boundingBox();
      expect(panelBox).not.toBeNull();
      expect(tableBox).not.toBeNull();
      // Top layout: the panel sits above the table, not beside it — its
      // bottom edge is at or above the table's top edge.
      expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(tableBox!.y + 1);
      // Full width, not squeezed into a 240px `.side-grid` sidebar — the
      // panel spans at least as wide as the table it sits above.
      expect(panelBox!.width).toBeGreaterThanOrEqual(tableBox!.width - 1);
    });

    await test.step("search narrows the list by name or email (Phase E, follow-up UX batch)", async () => {
      const searchBox = page.getByPlaceholder("Search by name or email");
      await searchBox.fill("no-such-user-xyz");
      await expect(page.getByText(PERSONAS.orphan.email)).toHaveCount(0);

      // Matches via the display name fragment, not just the email itself.
      await searchBox.fill("Orphan Candidate");
      await expect(page.getByText(PERSONAS.orphan.email)).toBeVisible();

      await searchBox.fill("");
      await expect(page.getByText(PERSONAS.orphan.email)).toBeVisible();
    });

    await test.step("Email/Name/Last login/Created columns are sortable (DirectoryTable)", async () => {
      const emailHeader = page.locator("th[aria-sort]", { hasText: "Email" });
      await expect(emailHeader).toHaveAttribute("aria-sort", "none");
      await emailHeader.getByRole("button", { name: "Email" }).click();
      await expect(emailHeader).toHaveAttribute("aria-sort", "ascending");
      await expect(page.getByText(PERSONAS.orphan.email)).toBeVisible();
      await emailHeader.getByRole("button", { name: "Email" }).click();
      await expect(emailHeader).toHaveAttribute("aria-sort", "descending");
      await expect(page.getByText(PERSONAS.orphan.email)).toBeVisible();
      // Third click returns to unsorted, leaving the rest of this spec's
      // steps unaffected by sort order.
      await emailHeader.getByRole("button", { name: "Email" }).click();
      await expect(emailHeader).toHaveAttribute("aria-sort", "none");
    });

    await test.step("the migrated 'Show' (view) and 'Include deactivated' filters still narrow results as before", async () => {
      await page.getByLabel("Show").selectOption("server_admins");
      await expect(page.getByText(PERSONAS.serverAdmin.email)).toBeVisible();
      await expect(page.getByText(PERSONAS.orphan.email)).toHaveCount(0);
      // Back to the default "orphaned" view for the rest of this spec.
      await page.getByLabel("Show").selectOption("orphaned");
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

    // Deactivate/ban/grant-admin now sit behind one `ActionMenu` kebab per
    // row instead of separate always-visible buttons (style guide "Pattern:
    // action menu", same consolidation as OrgAdminPage.tsx's Users table).
    // The kebab's accessible name is the row's own display name, and the
    // `Popover` menu it opens is portalled to `document.body`, so it's
    // looked up at the page level, not scoped to `row`.
    async function openOrphanActionsMenu() {
      await page.getByRole("button", { name: `${PERSONAS.orphan.name}'s actions` }).click();
      const menu = page.getByRole("menu", { name: `${PERSONAS.orphan.name}'s actions` });
      // Clicking a menuitem before the Popover-based menu finishes
      // positioning can silently miss it — see the identical fix in
      // org-rename-and-test-email.spec.ts / org-merge-import.spec.ts.
      await expect(menu).toBeVisible();
      return menu;
    }

    await test.step("deactivate then reactivate the orphaned account", async () => {
      const row = page.locator("tr", { hasText: PERSONAS.orphan.email });
      // Deactivate now confirms via the shared `ConfirmDialog` (sixth-pass
      // audit) rather than `window.confirm`.
      let menu = await openOrphanActionsMenu();
      await menu.getByRole("menuitem", { name: "Deactivate" }).click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/deactivate") && r.request().method() === "POST"),
        page.getByRole("dialog", { name: "Deactivate this account?" }).getByRole("button", { name: "Deactivate" }).click(),
      ]);
      // The default listing excludes deactivated accounts entirely.
      await page.getByLabel("Include deactivated accounts").check();
      await expect(row.getByText("Deactivated", { exact: true })).toBeVisible();
      menu = await openOrphanActionsMenu();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/reactivate") && r.request().method() === "POST"),
        menu.getByRole("menuitem", { name: "Reactivate" }).click(),
      ]);
      await expect(row.getByText("Deactivated", { exact: true })).toHaveCount(0);
    });

    await test.step("ban the orphaned account", async () => {
      const row = page.locator("tr", { hasText: PERSONAS.orphan.email });
      // Ban now confirms via the shared `ConfirmDialog` (sixth-pass audit)
      // rather than `window.confirm`.
      const menu = await openOrphanActionsMenu();
      await menu.getByRole("menuitem", { name: "Ban", exact: true }).click();
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
      const menu = await openOrphanActionsMenu();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/unban") && r.request().method() === "POST"),
        menu.getByRole("menuitem", { name: "Unban" }).click(),
      ]);
      await expect(row.getByText("Banned", { exact: true })).toHaveCount(0);
    });

    await test.step("reactivate afterward — restoring this shared, read-only-reused persona to fully active, not just unbanned", async () => {
      // `unban_orphaned_user` (backend/app/routers/system.py) deliberately
      // does *not* also reactivate the account: unban and reactivate are a
      // distinct pair of decisions by design ("may be granted org roles
      // again" vs. "may log in again"), so this test's own ban step left
      // the account genuinely deactivated even after the unban step above.
      // Left that way, the orphan persona — reused *read-only* by
      // two-factor-auth.spec.ts/org-login-2fa-handoff.spec.ts/this file
      // itself specifically because it's supposed to be always available —
      // can no longer log in at all on any later run in the same suite
      // execution, and would fail this file's own very first step (it's
      // deactivated, so it drops out of the default, non-"include
      // deactivated" orphaned-accounts view) on a re-run against the same
      // database. A real instance of this was found running the full
      // suite together: this file's own docstring already promised
      // "Always ends unbanned and active again," but this step was
      // missing, so it never actually delivered the "active" half.
      const row = page.locator("tr", { hasText: PERSONAS.orphan.email });
      const menu = await openOrphanActionsMenu();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/reactivate") && r.request().method() === "POST"),
        menu.getByRole("menuitem", { name: "Reactivate" }).click(),
      ]);
      await expect(row.getByText("Deactivated", { exact: true })).toHaveCount(0);
    });
  });
});
