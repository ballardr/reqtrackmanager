import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, PERSONAS } from "./helpers";

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
    await ensureExpanded(page, "Organisation groups");
    // Scoped to this section specifically — its "Name" placeholder isn't
    // page-unique (the "Organisation users" section's create-user form has
    // one too), and that section's own expand state can persist from other
    // specs sharing this persona within the same run.
    const groupsSection = page.getByRole("button", { name: "Organisation groups section" }).locator("xpath=..");

    const suffix = Date.now();
    const parentName = `Nesting Parent ${suffix}`;
    const childName = `Nesting Child ${suffix}`;

    await test.step("create two groups", async () => {
      for (const name of [parentName, childName]) {
        // "New group" opens a popover (style guide "Pattern: create panels,
        // popovers, and one door for bulk") rather than exposing an
        // always-visible inline form — the popover itself is portalled to
        // <body>, so it's located from `page`, not scoped to groupsSection.
        await groupsSection.getByRole("button", { name: "New group" }).click();
        const dialog = page.getByRole("dialog", { name: "New group" });
        await dialog.getByPlaceholder("e.g. Engineering").fill(name);
        await dialog.getByRole("button", { name: "Create" }).click();
        await expect(dialog).not.toBeVisible();
        // Scoped to the group-name <span> specifically — once both groups
        // exist, each also appears as an <option> in the other's nesting
        // picker, so a plain text match becomes ambiguous.
        await expect(page.locator("span", { hasText: name })).toBeVisible();
      }
    });

    // Each group renders as its own <div className="stack"><span>{name}</span>...
    // — the span's immediate parent is that specific group's own row, more
    // precise than a class-based ancestor lookup (which would also match
    // outer wrapping .stack containers higher up the page). Scoped to
    // <span> specifically since each group name also appears as an
    // <option> in the *other* group's nesting picker once both exist.
    const parentRow = page.locator("span", { hasText: parentName }).locator("xpath=..");
    const childRow = page.locator("span", { hasText: childName }).locator("xpath=..");

    await test.step("nest the child group inside the parent", async () => {
      const select = parentRow.getByRole("combobox");
      await select.selectOption({ label: childName });
      await select.locator("xpath=../button").click();
      await expect(page.getByText(`${childName} (nested group)`)).toBeVisible();
    });

    await test.step("attempting the reverse nesting (would create a cycle) shows an error", async () => {
      const select = childRow.getByRole("combobox");
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
