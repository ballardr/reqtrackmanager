import { expect, test } from "@playwright/test";

import { apiHeaders, installCleanupHook, loginAs, onCleanup, ORG_NAMES, PASSWORD, PERSONAS } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a server admin can review orphaned accounts (no org
 * membership at all — C-A-13's "orphaned account" clarification) across
 * the whole deployment (tenant-blind, per I-M-05), deactivate/reactivate
 * them, and ban an orphaned account so no org admin can grant it a role
 * again without an explicit unban.
 *
 * Uses its own disposable orphaned account (created as an Alpha member via
 * the API, then removed from Alpha), not the shared `orphan` persona:
 * no-org-user, two-factor-auth, org-login-2fa-handoff and
 * compliance-standards-management all log in as that persona in parallel,
 * and this spec's deactivate/ban steps made their logins 401 (2026-10-04).
 * The account is looked up by its unique name via the directory's search,
 * so it's found however many orphans earlier runs left (the list pages at
 * 30). Cleanup deactivates it, dropping it from the default view. The
 * non-server-admin checks go straight to the API rather than logging the
 * page out and back in.
 */
test.describe("server-admin user directory: orphaned accounts, deactivation, bans", () => {
  installCleanupHook();

  test("review orphaned accounts, deactivate/reactivate, ban/unban", async ({ page, request }) => {
    const suffix = Date.now();
    const orphan = { email: `e2e-dir-orphan-${suffix}@example.com`, name: `E2E Directory Orphan ${suffix}` };
    const orgAdminHeaders = await apiHeaders(request, PERSONAS.orgAdminAlphaBeta.email);
    const orgs: { id: string; name: string }[] = await (await request.get(`${API}/orgs`, { headers: orgAdminHeaders })).json();
    const alphaId = orgs.find((o) => o.name === ORG_NAMES.alpha)!.id;
    const created = await request.post(`${API}/orgs/${alphaId}/users`, {
      headers: orgAdminHeaders, data: { email: orphan.email, display_name: orphan.name, password: PASSWORD, role: "member" },
    });
    expect(created.ok()).toBeTruthy();
    const orphanId: string = (await created.json()).user_id;
    expect((await request.delete(`${API}/orgs/${alphaId}/users/${orphanId}/membership`, { headers: orgAdminHeaders })).ok()).toBeTruthy();
    onCleanup(async (cleanupRequest) => {
      const headers = await apiHeaders(cleanupRequest, PERSONAS.serverAdmin.email);
      await cleanupRequest.post(`${API}/system/users/${orphanId}/status`, { headers, data: { action: "unban" } });
      await cleanupRequest.post(`${API}/system/users/${orphanId}/status`, { headers, data: { action: "deactivate" } });
    });

    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    const searchBox = page.getByPlaceholder("Search by name or email");
    await searchBox.fill(orphan.name);

    await test.step("the orphaned-accounts view lists the orphaned account (server-admin only, tenant-blind)", async () => {
      await expect(page.getByText(orphan.email)).toBeVisible();
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
      await searchBox.fill("no-such-user-xyz");
      await expect(page.getByText(orphan.email)).toHaveCount(0);

      // Matches via the email too, not just the display name searched above;
      // left on this account's own name for the remaining steps.
      await searchBox.fill(orphan.email);
      await expect(page.getByText(orphan.email)).toBeVisible();

      await searchBox.fill(orphan.name);
      await expect(page.getByText(orphan.email)).toBeVisible();
    });

    await test.step("Email/Name/Last login/Created columns are sortable (DirectoryTable)", async () => {
      const emailHeader = page.locator("th[aria-sort]", { hasText: "Email" });
      await expect(emailHeader).toHaveAttribute("aria-sort", "none");
      await emailHeader.getByRole("button", { name: "Email" }).click();
      await expect(emailHeader).toHaveAttribute("aria-sort", "ascending");
      await expect(page.getByText(orphan.email)).toBeVisible();
      await emailHeader.getByRole("button", { name: "Email" }).click();
      await expect(emailHeader).toHaveAttribute("aria-sort", "descending");
      await expect(page.getByText(orphan.email)).toBeVisible();
      // Third click returns to unsorted, leaving the rest of this spec's
      // steps unaffected by sort order.
      await emailHeader.getByRole("button", { name: "Email" }).click();
      await expect(emailHeader).toHaveAttribute("aria-sort", "none");
    });

    await test.step("the migrated 'Show' (view) and 'Include deactivated' filters still narrow results as before", async () => {
      await searchBox.fill("");
      await page.getByLabel("Show").selectOption("server_admins");
      await expect(page.getByText(PERSONAS.serverAdmin.email)).toBeVisible();
      await expect(page.getByText(orphan.email)).toHaveCount(0);
      // Back to the default "orphaned" view for the rest of this spec.
      await page.getByLabel("Show").selectOption("orphaned");
      await searchBox.fill(orphan.name);
      await expect(page.getByText(orphan.email)).toBeVisible();
    });

    await test.step("a non-server-admin cannot reach this listing via a direct API call", async () => {
      const resp = await request.get(`${API}/system/users?no_org_membership=true`, { headers: orgAdminHeaders });
      expect(resp.status()).toBe(403);
    });

    // Deactivate/ban/grant-admin now sit behind one `ActionMenu` kebab per
    // row instead of separate always-visible buttons (style guide "Pattern:
    // action menu", same consolidation as OrgAdminPage.tsx's Users table).
    // The kebab's accessible name is the row's own display name, and the
    // `Popover` menu it opens is portalled to `document.body`, so it's
    // looked up at the page level, not scoped to `row`.
    async function openOrphanActionsMenu() {
      await page.getByRole("button", { name: `${orphan.name}'s actions` }).click();
      const menu = page.getByRole("menu", { name: `${orphan.name}'s actions` });
      // Clicking a menuitem before the Popover-based menu finishes
      // positioning can silently miss it — see the identical fix in
      // org-rename-and-test-email.spec.ts / org-merge-import.spec.ts.
      await expect(menu).toBeVisible();
      return menu;
    }

    await test.step("deactivate then reactivate the orphaned account", async () => {
      const row = page.locator("tr", { hasText: orphan.email });
      // Deactivate now confirms via the shared `ConfirmDialog` (sixth-pass
      // audit) rather than `window.confirm`.
      let menu = await openOrphanActionsMenu();
      await menu.getByRole("menuitem", { name: "Deactivate" }).click();
      await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes("/status") && r.request().method() === "POST" && r.request().postDataJSON()?.action === "deactivate"
        ),
        page.getByRole("dialog", { name: "Deactivate this account?" }).getByRole("button", { name: "Deactivate" }).click(),
      ]);
      // The default listing excludes deactivated accounts entirely.
      await page.getByLabel("Include deactivated accounts").check();
      await expect(row.getByText("Deactivated", { exact: true })).toBeVisible();
      menu = await openOrphanActionsMenu();
      await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes("/status") && r.request().method() === "POST" && r.request().postDataJSON()?.action === "reactivate"
        ),
        menu.getByRole("menuitem", { name: "Reactivate" }).click(),
      ]);
      await expect(row.getByText("Deactivated", { exact: true })).toHaveCount(0);
    });

    await test.step("ban the orphaned account", async () => {
      const row = page.locator("tr", { hasText: orphan.email });
      // Ban now confirms via the shared `ConfirmDialog` (sixth-pass audit)
      // rather than `window.confirm`.
      const menu = await openOrphanActionsMenu();
      await menu.getByRole("menuitem", { name: "Ban", exact: true }).click();
      await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes("/status") && r.request().method() === "POST" && r.request().postDataJSON()?.action === "ban"
        ),
        page.getByRole("dialog", { name: "Ban this account?" }).getByRole("button", { name: "Ban", exact: true }).click(),
      ]);
      await expect(row.getByText("Banned", { exact: true })).toBeVisible();
    });

    await test.step("a banned account can't be granted a fresh org role, even via a direct API call", async () => {
      const grantResp = await request.post(`${API}/orgs/${alphaId}/users/${orphanId}/roles`, {
        headers: orgAdminHeaders, data: { user_id: orphanId, role: "member" },
      });
      expect(grantResp.status()).toBe(403);
    });

    await test.step("unban restores the ability to grant roles", async () => {
      // Banning implies deactivation; "include deactivated" is still
      // checked from the deactivate step, so the row is still listed.
      const row = page.locator("tr", { hasText: orphan.email });
      const menu = await openOrphanActionsMenu();
      await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes("/status") && r.request().method() === "POST" && r.request().postDataJSON()?.action === "unban"
        ),
        menu.getByRole("menuitem", { name: "Unban" }).click(),
      ]);
      await expect(row.getByText("Banned", { exact: true })).toHaveCount(0);
      await expect(row.getByText("Deactivated", { exact: true })).toBeVisible();
    });

    await test.step("unban leaves the account deactivated; reactivating it is a separate decision", async () => {
      // `unban_orphaned_user` deliberately doesn't reactivate: "may be
      // granted org roles again" and "may log in again" are distinct
      // decisions, so the row still reads Deactivated until this step.
      const row = page.locator("tr", { hasText: orphan.email });
      const menu = await openOrphanActionsMenu();
      await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes("/status") && r.request().method() === "POST" && r.request().postDataJSON()?.action === "reactivate"
        ),
        menu.getByRole("menuitem", { name: "Reactivate" }).click(),
      ]);
      await expect(row.getByText("Deactivated", { exact: true })).toHaveCount(0);
    });
  });
});
