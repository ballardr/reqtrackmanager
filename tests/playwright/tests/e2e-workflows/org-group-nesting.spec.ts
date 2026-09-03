import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, openOrgGroupPanel, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: an org admin can nest one organisation group inside
 * another (transitively resolved for project-access purposes — see
 * backend/tests/test_org_group_nesting.py for the RBAC-level coverage),
 * and the UI surfaces a clear error rather than silently failing when an
 * attempted nesting would create a cycle.
 *
 * Org Groups moved off the old `CollapsibleSection`-of-`CollapsibleSection`s
 * accordion onto `DirectoryTable` + a per-row `SidePanel` (Phase B,
 * follow-up UX batch, 2026-08-31, docs/decisions.md) — this spec was
 * rewritten for that shape rather than patched in place, since the old
 * `openGroupCard`/`ensureExpanded`-per-card flow no longer applies (a row
 * now opens a real `SidePanel`, not an inline expand).
 *
 * Uses Gamma (orgAdminGamma is its sole admin, single-org so `/orgs` auto-
 * navigates straight to its admin page) — same choice org-security-
 * controls.spec.ts makes, to avoid interfering with Alpha/Beta specs
 * sharing this suite's single-worker run.
 */
test.describe("org group nesting", () => {
  test("nest a group, see it listed, remove it, and get a clear error on a cycle attempt", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    // Groups is its own top-level resource-menu group (2026-08 UX audit's
    // Org Admin restructure; split out of the combined "People" group in a
    // later pass) — a real navigation, so it must be selected before the
    // section is reachable at all.
    await selectOrgAdminGroup(page, "Groups");
    // The "Organisation groups" `CollapsibleSection` now wraps a
    // `DirectoryTable` + `SidePanel` (Phase B) rather than an accordion of
    // per-group cards, but it's still itself a `CollapsibleSection` whose
    // collapse state persists server-side per user across specs sharing
    // this persona.
    await ensureExpanded(page, "Organisation groups");

    const suffix = Date.now();
    const parentName = `Nesting Parent ${suffix}`;
    const childName = `Nesting Child ${suffix}`;

    await test.step("create two groups", async () => {
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
    });
  });
});
