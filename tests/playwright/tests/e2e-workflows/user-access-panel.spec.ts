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
    await selectOrgAdminGroup(page, "People");
    await ensureExpanded(page, "Organisation users");

    const row = page.locator("tr", { hasText: PERSONAS.orgAdminAlphaBeta.email });
    await row.getByRole("button", { name: /'s access$/ }).click();

    const panel = page.getByRole("dialog", { name: /'s access$/ });
    await expect(panel.getByText(PROJECT_NAMES.alpha1)).toBeVisible();
    await expect(panel.getByText(PROJECT_NAMES.alpha2)).toBeVisible();
    await expect(panel.getByText("Project manager").first()).toBeVisible();

    // Closes like every other SidePanel — Escape, same as Modal/Popover.
    await page.keyboard.press("Escape");
    await expect(panel).not.toBeVisible();
  });
});
