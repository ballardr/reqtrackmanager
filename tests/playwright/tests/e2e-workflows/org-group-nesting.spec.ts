import { expect, test } from "@playwright/test";

import { apiHeaders, ensureExpanded, installCleanupHook, loginAs, onCleanup, openOrgGroupPanel, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: an org admin can nest one organisation group inside another (resolved transitively for project
 * access; RBAC coverage is in backend/tests/test_org_group_nesting.py), and the UI shows a clear error rather than
 * failing silently when a nesting would create a cycle.
 *
 * Groups are a `DirectoryTable` with a per-row `SidePanel` (docs/decisions.md).
 *
 * Uses Gamma (orgAdminGamma is its sole admin and `/orgs` redirects straight to its admin page), as
 * org-security-controls.spec.ts does, to avoid interfering with Alpha/Beta specs.
 *
 * Ends by deleting both groups through the panel's "Delete group", with an API cleanup as a backstop if the test
 * stops early, so groups do not accumulate in Gamma.
 */
test.describe("org group nesting", () => {
  installCleanupHook();

  test("nest a group, see it listed, remove it, and get a clear error on a cycle attempt", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    // Groups is its own top-level resource-menu group — a real navigation, so it must be selected before the
    // section is reachable at all.
    await selectOrgAdminGroup(page, "Groups");
    // The "Organisation groups" `CollapsibleSection` wraps a `DirectoryTable` + `SidePanel`; its collapse state
    // persists server-side per user across specs sharing this persona.
    await ensureExpanded(page, "Organisation groups");

    const suffix = Date.now();
    const parentName = `Nesting Parent ${suffix}`;
    const childName = `Nesting Child ${suffix}`;
    onCleanup(async (request) => {
      const api = "http://localhost:8000/api/v1";
      const headers = await apiHeaders(request, PERSONAS.orgAdminGamma.email);
      const orgs: { id: string }[] = await (await request.get(`${api}/orgs`, { headers })).json();
      const groups: { id: string; name: string }[] = await (
        await request.get(`${api}/orgs/${orgs[0].id}/groups?search=${suffix}`, { headers })
      ).json();
      for (const g of groups.filter((x) => x.name.endsWith(String(suffix)))) {
        await request.delete(`${api}/orgs/${orgs[0].id}/groups/${g.id}`, { headers });
      }
    });

    await test.step("create two groups", async () => {
      // Narrow the (server-paginated, 20 per page) groups table to this
      // run's pair first: there is no endpoint to delete an org group, so
      // each run's groups accumulate in Gamma and new ones can land past the
      // first page. The search survives the table's post-create reload.
      await page.getByPlaceholder("Search by name", { exact: true }).fill(String(suffix));
      for (const name of [parentName, childName]) {
        // "New group" opens a Modal (style guide "Pattern: modal dialog for
        // entity create/rename") rather than exposing an always-visible
        // inline form — the dialog itself is portalled to <body>.
        await page.getByRole("button", { name: "New group" }).click();
        const dialog = page.getByRole("dialog", { name: "New group" });
        await dialog.getByPlaceholder("e.g. Engineering").fill(name);
        await dialog.getByRole("button", { name: "Create" }).click();
        await expect(dialog).not.toBeVisible();
        // Each group is now a `DirectoryTable` row — its Name cell (a real
        // `<button>`, `onRowClick`) is visible without opening anything,
        // proving the group was actually created.
        await expect(page.getByRole("button", { name })).toBeVisible();
      }
    });

    await test.step("nest the child group inside the parent", async () => {
      const parentPanel = await openOrgGroupPanel(page, parentName);
      await parentPanel.locator("select").selectOption({ label: childName });
      await parentPanel.locator("select").locator("xpath=../button").click();
      await expect(parentPanel.getByText(`${childName} (nested group)`)).toBeVisible();
      await parentPanel.getByRole("button", { name: "Close" }).click();
    });

    await test.step("attempting the reverse nesting (would create a cycle) shows an error", async () => {
      const childPanel = await openOrgGroupPanel(page, childName);
      await childPanel.locator("select").selectOption({ label: parentName });
      await childPanel.locator("select").locator("xpath=../button").click();
      await expect(childPanel.getByText(/cycle/i)).toBeVisible();
      await expect(childPanel.getByText(`${parentName} (nested group)`)).toHaveCount(0);
      await childPanel.getByRole("button", { name: "Close" }).click();
    });

    await test.step("remove the nested group", async () => {
      const parentPanel = await openOrgGroupPanel(page, parentName);
      await parentPanel.getByText(`${childName} (nested group)`).locator("xpath=ancestor::li[1]").getByRole("button").click();
      await expect(parentPanel.getByText(`${childName} (nested group)`)).toHaveCount(0);
      await parentPanel.getByRole("button", { name: "Close" }).click();
    });

    await test.step("delete both groups (Tier 1 confirmation, toast)", async () => {
      for (const name of [childName, parentName]) {
        const panel = await openOrgGroupPanel(page, name);
        await panel.getByRole("button", { name: "Delete group" }).click();
        await page.getByRole("dialog", { name: `Delete "${name}"?` }).getByRole("button", { name: "Delete group" }).click();
        await expect(page.getByText("Group deleted").last()).toBeVisible();
        await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
      }
    });
  });
});
