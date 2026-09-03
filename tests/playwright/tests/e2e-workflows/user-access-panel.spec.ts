import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: an org admin can see what a single user actually has
 * access to — which projects, which role(s) on each, and which org groups
 * they directly belong to — without reconstructing the answer by hand
 * from every project's own membership list (2026-08 UX audit, sixth pass:
 * "No way to view a user's access").
 *
 * Views the logged-in org admin's own row rather than a second persona's,
 * to avoid depending on exactly which orgs/projects a shared seed persona
 * (e.g. memberAlphaBeta) is a member of beyond what's already documented
 * for this one: OrgAdminAlphaBeta is org_admin of Alpha, PM on both of
 * Alpha's projects.
 */
test.describe("view a user's access", () => {
  test("shows their projects/roles and org groups in a read-only side panel", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/orgs");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Users");
    await ensureExpanded(page, "Organisation users");

    await test.step("the filter panel renders as a full-width bar above the table, not a cramped sidebar (follow-up UX fix — the Users table's 6 columns crowded the old 240px side sidebar)", async () => {
      const filterPanel = page.locator(".filter-panel-top");
      const table = page.getByRole("table", { name: /users/i });
      await expect(filterPanel).toBeVisible();
      await expect(table).toBeVisible();
      const panelBox = await filterPanel.boundingBox();
      const tableBox = await table.boundingBox();
      expect(panelBox).not.toBeNull();
      expect(tableBox).not.toBeNull();
      // Top layout: the panel sits above the table, not beside it — its
      // bottom edge is at or above the table's top edge.
      expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(tableBox!.y + 1);
      // Full width, not squeezed into a 240px `.side-grid` sidebar — the
      // panel spans at least as wide as the table it sits above.
      expect(panelBox!.width).toBeGreaterThanOrEqual(tableBox!.width - 1);
    });

    // PR6 of the members/groups directory rework plan (docs/decisions.md)
    // consolidated the Users table's previously-bare "View {name}'s access"
    // button into the row's `ActionMenu` — reachable via its kebab trigger
    // (`${display name}'s actions`), then the `menuitem` inside the
    // `Popover` it opens (waiting for the menu itself before clicking an
    // item, same pattern org-merge-import.spec.ts's own `ActionMenu` call
    // site uses, since the popover repositions after mount).
    const row = page.locator("tr", { hasText: PERSONAS.orgAdminAlphaBeta.email });
    const menuTriggerName = `${PERSONAS.orgAdminAlphaBeta.name}'s actions`;
    await row.getByRole("button", { name: menuTriggerName }).click();
    await expect(page.getByRole("menu", { name: menuTriggerName })).toBeVisible();
    await page.getByRole("menuitem", { name: /'s access$/ }).click();

    const panel = page.getByRole("dialog", { name: /'s access$/ });
    await expect(panel.getByText(PROJECT_NAMES.alpha1)).toBeVisible();
    await expect(panel.getByText(PROJECT_NAMES.alpha2)).toBeVisible();
    await expect(panel.getByText("Project manager").first()).toBeVisible();

    // Closes like every other SidePanel — Escape, same as Modal/Popover.
    await page.keyboard.press("Escape");
    await expect(panel).not.toBeVisible();
  });
});

/**
 * Column-header sorting (2026-08 UX audit roadmap, "Column-header sorting
 * on data tables") — the Users table is backend-paginated (search + `limit`/
 * `offset` shipped in an earlier roadmap pass), so a header click has to
 * refetch with `sort`/`order` query params rather than reordering just the
 * loaded page. Same "Users" section this file already reaches for the
 * access-panel test above, so it lives alongside it rather than in a new
 * file.
 */
test.describe("org admin users table sorting", () => {
  test("sort by email ascending and descending via the column header", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/orgs");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Users");
    await ensureExpanded(page, "Organisation users");
    await expect(page.getByText(PERSONAS.orgAdminAlphaBeta.email)).toBeVisible();
    // `visibleEmails()` below asserts every visible row's first cell forms
    // a sorted sequence — true for real user rows (server-sorted) but not
    // for a `kind: "invited"` row merged in ahead of them (Phase A,
    // follow-up UX batch), which isn't part of that server-side sort.
    // Unchecking "Show invited" keeps this an apples-to-apples comparison
    // regardless of whether this org happens to have a pending invite.
    await page.getByRole("checkbox", { name: "Show invited" }).uncheck();

    const emailHeader = page.getByRole("button", { name: "Email" });
    const emailHeaderCell = page.locator("th", { has: emailHeader });

    async function visibleEmails(): Promise<string[]> {
      return page.locator("table tbody tr").evaluateAll((rows) =>
        rows.map((row) => row.querySelector("td")?.textContent?.trim() ?? "")
      );
    }

    const [ascResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/users?") && r.url().includes("sort=email") && r.url().includes("order=asc")),
      emailHeader.click(),
    ]);
    expect(ascResponse.ok()).toBe(true);
    await expect(emailHeaderCell).toHaveAttribute("aria-sort", "ascending");
    const ascending = await visibleEmails();
    expect(ascending.length).toBeGreaterThan(0);
    expect(ascending).toEqual([...ascending].sort());

    const [descResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/users?") && r.url().includes("sort=email") && r.url().includes("order=desc")),
      emailHeader.click(),
    ]);
    expect(descResponse.ok()).toBe(true);
    await expect(emailHeaderCell).toHaveAttribute("aria-sort", "descending");
    const descending = await visibleEmails();
    expect(descending).toEqual([...descending].sort().reverse());

    await emailHeader.click();
    await expect(emailHeaderCell).toHaveAttribute("aria-sort", "none");
  });
});
