import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, openProjectGroupPanel, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: `Pattern: role display` (2026-08 UX audit roadmap row
 * 510) — a compact role-badge list (project list roles, favourites, "my
 * organisations") collapses a user's held `ProjectRole` set to its
 * effective highest tier, per the real precedence
 * `project_manager` > (`project_administrator` = `stakeholder`) > `member`
 * — rather than listing every role a user happens to hold.
 *
 * Uses a brand-new dedicated user on Gamma (single-admin org, avoids
 * interfering with Alpha/Beta specs sharing this suite's run) rather than
 * granting a second role to any shared seeded persona — none of the seed
 * personas hold more than one project-role tier today, and mutating a
 * shared persona's effective permissions for the rest of a suite run risks
 * changing behaviour other specs depend on (e.g. a "stakeholder can't
 * archive" assertion elsewhere). The new user, its two throwaway project
 * groups, and its org membership are all uniquely named per run and never
 * referenced by any other spec, so leaving them behind afterward is
 * harmless (a `DELETE .../groups/{id}` exists as of Phase 5,
 * docs/decisions.md, but this spec doesn't need it — nothing else in the
 * suite ever looks for a project's group *count*).
 */
test.describe("role display collapses to the effective highest tier", () => {
  test("stacked administrator+stakeholder shows both; manager alone outranks a lower tier", async ({ page }) => {
    const suffix = Date.now();
    const email = `e2e-role-collapse-${suffix}@example.com`;
    const password = "E2eRoleCollapse123!";
    const adminGroupName = `E2E Role Collapse Admin ${suffix}`;
    const stakeholderGroupName = `E2E Role Collapse Stake ${suffix}`;

    await test.step("org admin creates a brand-new user, dedicated to this spec", async () => {
      await loginAs(page, PERSONAS.orgAdminGamma.email);
      await page.goto("/orgs");
      await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
      await selectOrgAdminGroup(page, "Users");
      await ensureExpanded(page, "Organisation users");
      // "New user" opens a Modal (style guide "Pattern: modal dialog for
      // entity create/rename") rather than a permanently-visible inline
      // form — its three fields are real `<label>`s, not placeholders.
      await page.getByRole("button", { name: "New user" }).click();
      const dialog = page.getByRole("dialog", { name: "New user" });
      await dialog.getByLabel("Email").fill(email);
      await dialog.getByLabel("Name").fill(`E2E Role Collapse ${suffix}`);
      await dialog.getByLabel("Password").fill(password);
      await dialog.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText(email)).toBeVisible();
    });

    await test.step("grant project_administrator and stakeholder on Gamma-1 via two different project groups", async () => {
      await page.goto("/projects");
      await page.getByText(PROJECT_NAMES.gamma1).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Project groups");

      for (const [groupName, roleLabel] of [
        [adminGroupName, "Project administrator"],
        [stakeholderGroupName, "Stakeholder"],
      ]) {
        await page.getByRole("button", { name: "New group" }).click();
        const dialog = page.getByRole("dialog", { name: "New group" });
        await dialog.getByPlaceholder("e.g. Reviewers").fill(groupName);
        await dialog.getByLabel("Role").selectOption({ label: roleLabel });
        await dialog.getByRole("button", { name: "Create" }).click();
        await expect(dialog).not.toBeVisible();

        // Each group row opens a `SidePanel` (Phase 5, docs/decisions.md)
        // — scoped to this specific group's own panel (its accessible
        // name is "<group> details"), since once more than one of this
        // spec's groups has a member, a page-wide `li`/`getByText` match
        // for the same email would be ambiguous across them.
        const groupPanel = await openProjectGroupPanel(page, groupName);
        await groupPanel.getByPlaceholder("Type a name to add, or an email to invite…").fill(email);
        await page.getByRole("option", { name: new RegExp(email) }).click();
        await expect(groupPanel.locator("li", { hasText: email })).toBeVisible();
        await page.getByRole("button", { name: "Close" }).click();
      }
    });

    await test.step("the new user's own project list shows both tier-2 roles together, not a full unordered list", async () => {
      await page.getByRole("button", { name: "Sign out" }).click();
      await page.waitForURL(/\/login$/);
      await loginAs(page, email, password);
      await page.goto("/projects");

      const gammaCard = page.locator(".card", { hasText: PROJECT_NAMES.gamma1 });
      await expect(gammaCard).toBeVisible();
      // Both tied tier-2 roles are shown — order between them isn't
      // specified (they aren't ranked relative to each other), so accept
      // either.
      await expect(
        gammaCard.getByText(/^Your roles: (Project administrator, Stakeholder|Stakeholder, Project administrator)$/)
      ).toBeVisible();
      // Neither role dropped, and no bare "Member" floor shown once a
      // higher tier is held.
      await expect(gammaCard.getByText("Your roles: Member", { exact: true })).toHaveCount(0);
    });

    await test.step("adding project_manager on top collapses the display to manager alone", async () => {
      await page.getByRole("button", { name: "Sign out" }).click();
      await page.waitForURL(/\/login$/);
      await loginAs(page, PERSONAS.orgAdminGamma.email);
      await page.goto("/projects");
      await page.getByText(PROJECT_NAMES.gamma1).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Project groups");

      const managerGroupName = `E2E Role Collapse Manager ${suffix}`;
      await page.getByRole("button", { name: "New group" }).click();
      const dialog = page.getByRole("dialog", { name: "New group" });
      await dialog.getByPlaceholder("e.g. Reviewers").fill(managerGroupName);
      await dialog.getByLabel("Role").selectOption({ label: "Project manager" });
      await dialog.getByRole("button", { name: "Create" }).click();
      await expect(dialog).not.toBeVisible();
      const managerGroupPanel = await openProjectGroupPanel(page, managerGroupName);
      await managerGroupPanel.getByPlaceholder("Type a name to add, or an email to invite…").fill(email);
      await page.getByRole("option", { name: new RegExp(email) }).click();
      await expect(managerGroupPanel.locator("li", { hasText: email })).toBeVisible();
      await page.getByRole("button", { name: "Close" }).click();

      await page.getByRole("button", { name: "Sign out" }).click();
      await page.waitForURL(/\/login$/);
      await loginAs(page, email, password);
      await page.goto("/projects");

      const gammaCard = page.locator(".card", { hasText: PROJECT_NAMES.gamma1 });
      await expect(gammaCard).toBeVisible();
      await expect(gammaCard.getByText("Your roles: Project manager", { exact: true })).toBeVisible();
      await expect(gammaCard.getByText(/Stakeholder/)).toHaveCount(0);
    });

    await test.step("Org Admin's 'View access' panel shows the collapsed summary by default, with every role available via its expand toggle", async () => {
      // 2026-08-30 reversal (see docs/decisions.md and docs/ux-style-guide
      // .md's "Pattern: role display" section): this panel used to always
      // show every held role uncollapsed; it now defaults to the same
      // collapsed summary compact lists use, with a per-row "Show all N
      // roles" toggle that reveals the full set on demand — the audit
      // detail is still reachable, just not the default view.
      await page.getByRole("button", { name: "Sign out" }).click();
      await page.waitForURL(/\/login$/);
      await loginAs(page, PERSONAS.orgAdminGamma.email);
      await page.goto("/orgs");
      await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
      await selectOrgAdminGroup(page, "Users");
      await ensureExpanded(page, "Organisation users");

      const row = page.locator("tr", { hasText: email });
      await row.getByRole("button", { name: /'s access$/ }).click();

      const panel = page.getByRole("dialog", { name: /'s access$/ });
      // Collapsed by default: `project_manager` is the sole top tier, so
      // it alone shows, hiding the lower-tier `project_administrator`/
      // `stakeholder`/`member` roles also held on Gamma-1 — held roles
      // total 4, not 3: `_normalize` (`backend/app/services/rbac.py`)
      // implicitly adds `project_administrator`+`stakeholder`+`member`
      // alongside a directly-granted `project_manager`, on top of the two
      // directly granted via the earlier admin/stakeholder groups.
      await expect(panel.getByText("Project manager")).toBeVisible();
      await expect(panel.getByText("Project administrator")).toHaveCount(0);
      await expect(panel.getByText("Stakeholder")).toHaveCount(0);

      const toggle = panel.getByRole("button", { name: "Show all 4 roles" });
      await expect(toggle).toBeVisible();
      await toggle.click();

      // Expanded: every held role now visible.
      await expect(panel.getByText("Project manager")).toBeVisible();
      await expect(panel.getByText("Project administrator")).toBeVisible();
      await expect(panel.getByText("Stakeholder")).toBeVisible();
      // `exact: true` — a bare "Member" substring-matches the panel's own
      // "Not a member of any organisation group." empty-state copy above.
      await expect(panel.getByText("Member", { exact: true })).toBeVisible();
      await expect(panel.getByRole("button", { name: "Show fewer" })).toBeVisible();

      await page.keyboard.press("Escape");
      await expect(panel).not.toBeVisible();
    });
  });
});
