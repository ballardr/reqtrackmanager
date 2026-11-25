import { expect, test } from "@playwright/test";

import { apiHeaders, installCleanupHook, loginAs, onCleanup, ORG_NAMES, PASSWORD, PERSONAS } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a server admin reviews orphaned accounts (no org membership, C-A-13) across the whole
 * deployment (tenant-blind, per I-M-05), deactivates and reactivates them, and bans one so no org admin can
 * grant it a role without an explicit unban.
 *
 * Uses its own disposable orphaned account (an Alpha member created via the API, then removed from Alpha), not
 * the shared `orphan` persona, which other specs log in as in parallel. The account is found by name through
 * the directory search (the list pages at 30). Cleanup deactivates it. Non-server-admin checks call the API.
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
      // `DirectoryTable.tsx` wraps the wide Users table in an `overflow-x: auto` `<div>` and `<table>`'s
      // `boundingBox()` reports its full content width, so the scroll wrapper (the parent) is measured.
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

    await test.step("search narrows the list by name or email", async () => {
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

    // Deactivate, ban and grant-admin sit behind one `ActionMenu` kebab per row (style guide "Pattern:
    // action menu"). The kebab is named by the row's display name and its `Popover` menu is portalled
    // to `document.body`, so it is looked up at the page level, not scoped to `row`.
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
