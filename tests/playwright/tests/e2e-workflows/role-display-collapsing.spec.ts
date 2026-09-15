import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, logout, openProjectGroupPanel, ORG_NAMES, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

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
 * archive" assertion elsewhere).
 *
 * Cleans up its own three throwaway project groups and its throwaway user's
 * org membership at the end — an earlier version of this spec assumed
 * "leaving them behind afterward is harmless... nothing else in the suite
 * ever looks for a project's group count", but that's false in practice:
 * Gamma-1's "Project groups" table paginates at 20 rows ("Load more"), and
 * after enough unclean runs accumulated more than 20 groups, a *newly
 * created* group's row landed past the default page, so `row.getByRole(...)`
 * on it waited forever for an element that existed but was never rendered —
 * looked exactly like flakiness/a timeout under load, but reproduced
 * deterministically once the table had enough leftover rows, regardless of
 * contention. See docs/decisions.md.
 */
test.describe("role display collapses to the effective highest tier", () => {
  test("stacked administrator+stakeholder shows both; manager alone outranks a lower tier", async ({ page }) => {
    const suffix = Date.now();
    const email = `e2e-role-collapse-${suffix}@example.com`;
    const password = "E2eRoleCollapse123!";
    const adminGroupName = `E2E Role Collapse Admin ${suffix}`;
    const stakeholderGroupName = `E2E Role Collapse Stake ${suffix}`;
    const managerGroupName = `E2E Role Collapse Manager ${suffix}`;
    let gamma1Id = "";

    try {
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
        gamma1Id = page.url().match(/projects\/([0-9a-f-]+)/)![1];
        await page.getByRole("link", { name: "Project admin", exact: true }).click();
        await selectProjectAdminGroup(page, "Project groups");

        for (const [groupName, roleLabel] of [
          [adminGroupName, "Project administrator"],
          [stakeholderGroupName, "Stakeholder"],
        ]) {
          // PR7 of the members/groups directory rework plan (docs/decisions.md):
          // "New group" no longer has a role picker — a group is created
          // bare and a role is a separate grant, made afterward via the
          // group's own row `MultiSelectDropdown`.
          await page.getByRole("button", { name: "New group" }).click();
          const dialog = page.getByRole("dialog", { name: "New group" });
          await dialog.getByPlaceholder("e.g. Reviewers").fill(groupName);
          await dialog.getByRole("button", { name: "Create" }).click();
          await expect(dialog).not.toBeVisible();

          // The table paginates ("Load more") and shows only its first page
          // by default — a just-created row isn't guaranteed to land on it
          // once enough other groups already exist project-wide (reproduced
          // this deterministically once Gamma-1 had 20+ groups from earlier
          // runs: the new row existed but was never rendered, so the plain
          // row lookup below waited forever). The panel's own "Search by
          // name" filter (`FilterPanel`, `handleGroupSearchChange`) issues a
          // server-side search instead of paging through the client-side
          // list, so it finds this exact group regardless of how many others
          // exist or what page they'd fall on — the correct fix, not a
          // bigger timeout or a promise to clean up afterward. See
          // docs/decisions.md.
          await page.getByPlaceholder("Search by name").fill(groupName);

          const row = page.getByRole("button", { name: new RegExp(`^${groupName}`) }).locator("xpath=ancestor::tr[1]");
          await row.getByRole("button", { name: `${groupName}'s roles` }).click();
          const roleGroup = page.getByRole("group", { name: `${groupName}'s roles` });
          // `.click()`, not `.check()`: the checkbox's own accessible name
          // flips from "Grant X to Y" to "Revoke X from Y" the moment the
          // toggle succeeds (`ProjectMembersTable`'s pre-existing pattern,
          // reused by PR7's group-role `MultiSelectDropdown`), so
          // `.check()`'s built-in re-verification against that same
          // original locator can never resolve — verify via the `row`
          // assertion below instead, a freshly resolved locator, the same
          // working pattern project-admin-members.spec.ts already uses.
          await roleGroup.getByRole("checkbox", { name: `Grant ${roleLabel} to ${groupName}` }).click();
          await expect(row).toContainText(roleLabel);

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

        await page.getByRole("button", { name: "New group" }).click();
        const dialog = page.getByRole("dialog", { name: "New group" });
        await dialog.getByPlaceholder("e.g. Reviewers").fill(managerGroupName);
        await dialog.getByRole("button", { name: "Create" }).click();
        await expect(dialog).not.toBeVisible();

        // See the identical comment on the first two groups above — search
        // rather than assume the new row is on the table's default page.
        await page.getByPlaceholder("Search by name").fill(managerGroupName);

        const managerRow = page.getByRole("button", { name: new RegExp(`^${managerGroupName}`) }).locator("xpath=ancestor::tr[1]");
        await managerRow.getByRole("button", { name: `${managerGroupName}'s roles` }).click();
        // `.click()`, not `.check()` — see the identical comment above.
        await page.getByRole("group", { name: `${managerGroupName}'s roles` })
          .getByRole("checkbox", { name: `Grant Project manager to ${managerGroupName}` }).click();
        await expect(managerRow).toContainText("Project manager");

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

        // PR6 of the members/groups directory rework plan (docs/decisions.md)
        // consolidated the Users table's previously-bare "View {name}'s
        // access" button into the row's `ActionMenu` — reachable via its
        // kebab trigger (`${display name}'s actions`), then the `menuitem`
        // inside the `Popover` it opens (waiting for the menu itself before
        // clicking an item, same pattern other `ActionMenu` call sites in
        // this suite use, since the popover repositions after mount).
        const row = page.locator("tr", { hasText: email });
        const menuTriggerName = `E2E Role Collapse ${suffix}'s actions`;
        await row.getByRole("button", { name: menuTriggerName }).click();
        await expect(page.getByRole("menu", { name: menuTriggerName })).toBeVisible();
        await page.getByRole("menuitem", { name: /'s access$/ }).click();

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
    } finally {
      await test.step("clean up: delete this run's three throwaway project groups and remove the throwaway user from Gamma, best-effort so an earlier failure isn't masked", async () => {
        if (!gamma1Id) return;
        try {
          await logout(page);
          await loginAs(page, PERSONAS.orgAdminGamma.email);
          const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
          const adminHeaders = { Authorization: `Bearer ${adminToken}` };

          const groups: { id: string; name: string }[] = await page
            .request.get(`${apiBaseUrl}/api/v1/projects/${gamma1Id}/groups`, { headers: adminHeaders })
            .then((r) => r.json());
          for (const name of [adminGroupName, stakeholderGroupName, managerGroupName]) {
            const group = groups.find((g) => g.name === name);
            if (group) {
              await page.request.delete(`${apiBaseUrl}/api/v1/projects/${gamma1Id}/groups/${group.id}`, {
                headers: adminHeaders,
              });
            }
          }

          const orgsResp = await page.request.get(`${apiBaseUrl}/api/v1/orgs`, { headers: adminHeaders });
          const orgs: { id: string; name: string }[] = await orgsResp.json();
          const gammaOrgId = orgs.find((o) => o.name === ORG_NAMES.gamma)?.id;
          if (gammaOrgId) {
            const usersResp = await page.request.get(`${apiBaseUrl}/api/v1/orgs/${gammaOrgId}/users`, {
              headers: adminHeaders,
            });
            const users: { user_id: string; email: string }[] = await usersResp.json();
            const newUserId = users.find((u) => u.email === email)?.user_id;
            if (newUserId) {
              await page.request.delete(`${apiBaseUrl}/api/v1/orgs/${gammaOrgId}/users/${newUserId}/membership`, {
                headers: adminHeaders,
              });
            }
          }
        } catch {
          // Best-effort: a failure here must not replace/mask whatever the
          // `try` block above actually failed with.
        }
      });
    }
  });
});
