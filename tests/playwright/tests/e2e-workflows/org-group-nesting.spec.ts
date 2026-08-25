import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, openGroupCard, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: an org admin can nest one organisation group inside
 * another (transitively resolved for project-access purposes — see
 * backend/tests/test_org_group_nesting.py for the RBAC-level coverage),
 * and the UI surfaces a clear error rather than silently failing when an
 * attempted nesting would create a cycle.
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
    await ensureExpanded(page, "Organisation groups");
    // Scoped to this section specifically — its own expand state can
    // persist from other specs sharing this persona within the same run.
    const groupsSection = page.getByRole("button", { name: "Organisation groups section" }).locator("xpath=..");

    const suffix = Date.now();
    const parentName = `Nesting Parent ${suffix}`;
    const childName = `Nesting Child ${suffix}`;

    await test.step("create two groups", async () => {
      for (const name of [parentName, childName]) {
        // "New group" opens a Modal (style guide "Pattern: modal dialog for
        // entity create/rename") rather than exposing an always-visible
        // inline form — the dialog itself is portalled to <body>, so it's
        // located from `page`, not scoped to groupsSection.
        await groupsSection.getByRole("button", { name: "New group" }).click();
        const dialog = page.getByRole("dialog", { name: "New group" });
        await dialog.getByPlaceholder("e.g. Engineering").fill(name);
        await dialog.getByRole("button", { name: "Create" }).click();
        await expect(dialog).not.toBeVisible();
        // Each group now renders collapsed behind its own
        // `CollapsibleSection` (2026-08 UX audit "Directories at scale") —
        // its title (which includes the group's name) is still visible
        // either way, so this proves the group was actually created
        // without needing to expand it yet. Scoped to the title <strong>
        // specifically — once both groups exist, each also appears as an
        // <option> in the other's nesting picker, so a plain text match
        // becomes ambiguous.
        await expect(page.locator("strong", { hasText: name })).toBeVisible();
      }
    });

    // Each group's title <strong> sits inside its own row div, inside its
    // own outer card div (`CollapsibleSection`, `variant="plain"`) — two
    // levels up from the title reaches that specific group's whole card,
    // more precise than a class-based ancestor lookup (which would also
    // match outer wrapping .stack containers higher up the page).
    const parentRow = page.locator("strong", { hasText: parentName }).locator("xpath=../..");
    const childRow = page.locator("strong", { hasText: childName }).locator("xpath=../..");

    // Each row also has its own "add member" `UserAutocomplete`, whose text
    // input is `role="combobox"` too (WAI-ARIA combobox pattern) — `select`
    // here specifically means the nesting picker's `<select>`. Both are
    // unreachable until the group's own card is expanded.
    await test.step("nest the child group inside the parent", async () => {
      await openGroupCard(page, parentName);
      const select = parentRow.locator("select");
      await select.selectOption({ label: childName });
      await select.locator("xpath=../button").click();
      await expect(page.getByText(`${childName} (nested group)`)).toBeVisible();
    });

    await test.step("attempting the reverse nesting (would create a cycle) shows an error", async () => {
      await openGroupCard(page, childName);
      const select = childRow.locator("select");
      await select.selectOption({ label: parentName });
      await select.locator("xpath=../button").click();
      await expect(page.getByText(/cycle/i)).toBeVisible();
      await expect(page.getByText(`${parentName} (nested group)`)).toHaveCount(0);
    });

    await test.step("remove the nested group", async () => {
      await parentRow.getByText(`${childName} (nested group)`).locator("xpath=ancestor::li[1]").getByRole("button").click();
      await expect(page.getByText(`${childName} (nested group)`)).toHaveCount(0);
    });
  });
});
