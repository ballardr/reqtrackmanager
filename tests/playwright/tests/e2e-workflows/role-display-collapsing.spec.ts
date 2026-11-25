import { type APIRequestContext, expect, test } from "@playwright/test";

import { ensureExpanded, installCleanupHook, loginAs, logout, onCleanup, openProject, ORG_NAMES, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: `Pattern: role display`: a compact role-badge list (project list roles, favourites, "my
 * organisations") collapses a user's held `ProjectRole` set to its effective highest tier, per the precedence
 * `project_manager` > (`project_administrator` = `stakeholder`) > `member`, rather than listing every held role.
 *
 * Uses a new dedicated user on Gamma (single-admin org, avoiding interference with Alpha/Beta specs) rather than
 * granting a second role to a shared seeded persona: none hold more than one project-role tier, and changing a
 * shared persona's effective permissions risks other specs (e.g. a "stakeholder can't archive" assertion).
 *
 * Cleans up its three throwaway project groups and its throwaway user's org membership at the end: Gamma-1's
 * "Project groups" table paginates at 20 rows ("Load more"), so once leftover groups exceed 20 a newly created
 * group's row lands past the default page and `row.getByRole(...)` waits for an element that exists but is not
 * rendered, which looks like a timeout under load. See docs/decisions.md.
 *
 * Setup (user, groups, role grants, memberships) goes through the API, not the Project Admin UI (covered by
 * project-admin-groups-and-fields.spec.ts), to stay within the 30s test budget so a timeout cannot skip cleanup.
 * Any "E2E Role Collapse" groups/users left on Gamma by an interrupted run are swept before starting.
 */
test.describe("role display collapses to the effective highest tier", () => {
  installCleanupHook();

  test("stacked administrator+stakeholder shows both; manager alone outranks a lower tier", async ({ page }) => {
    const suffix = Date.now();
    const email = `e2e-role-collapse-${suffix}@example.com`;
    const password = "E2eRoleCollapse123!";
    const groupPrefix = "E2E Role Collapse";
    let userId = "";

    await loginAs(page, PERSONAS.orgAdminGamma.email);
    const adminHeaders = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("reqtrack_token"))}` };
    const orgs: { id: string; name: string }[] = await (
      await page.request.get(`${apiBaseUrl}/api/v1/orgs`, { headers: adminHeaders })
    ).json();
    const gammaOrgId = orgs.find((o) => o.name === ORG_NAMES.gamma)!.id;
    await page.goto("/projects");
    await openProject(page, PROJECT_NAMES.gamma1);
    const gamma1Id = page.url().match(/projects\/([0-9a-f-]+)/)![1];

    /** Creates a project group on Gamma-1, grants it `role`, and adds the user. */
    async function grantViaGroup(label: string, role: string) {
      const group = await (await page.request.post(`${apiBaseUrl}/api/v1/projects/${gamma1Id}/groups`, {
        headers: adminHeaders, data: { name: `${groupPrefix} ${label} ${suffix}` },
      })).json();
      const granted = await page.request.post(`${apiBaseUrl}/api/v1/projects/${gamma1Id}/groups/${group.id}/roles`, {
        headers: adminHeaders, data: { role },
      });
      expect(granted.ok()).toBeTruthy();
      const added = await page.request.post(`${apiBaseUrl}/api/v1/projects/${gamma1Id}/groups/${group.id}/members`, {
        headers: adminHeaders, data: { user_id: userId },
      });
      expect(added.ok()).toBeTruthy();
    }

    /** Deletes every "E2E Role Collapse" group on Gamma-1 and every
     * throwaway role-collapse user's Gamma membership — this run's and any
     * an earlier interrupted run left behind. */
    async function sweep(api: APIRequestContext) {
      const groups: { id: string; name: string }[] = await (
        await api.get(
          `${apiBaseUrl}/api/v1/projects/${gamma1Id}/groups?search=${encodeURIComponent(groupPrefix)}`,
          { headers: adminHeaders },
        )
      ).json();
      for (const group of groups.filter((g) => g.name.startsWith(groupPrefix))) {
        await api.delete(`${apiBaseUrl}/api/v1/projects/${gamma1Id}/groups/${group.id}`, { headers: adminHeaders });
      }
      const users: { user_id: string; email: string }[] = await (
        await api.get(`${apiBaseUrl}/api/v1/orgs/${gammaOrgId}/users`, { headers: adminHeaders })
      ).json();
      for (const user of users.filter((u) => u.email.startsWith("e2e-role-collapse-"))) {
        await api.delete(`${apiBaseUrl}/api/v1/orgs/${gammaOrgId}/users/${user.user_id}/membership`, {
          headers: adminHeaders,
        });
      }
    }

    await sweep(page.request);
    // Runs again after the test even if it fails or times out (afterEach).
    onCleanup((request) => sweep(request));

    await test.step("set up a dedicated user holding project_administrator and stakeholder via two groups", async () => {
      const created = await page.request.post(`${apiBaseUrl}/api/v1/orgs/${gammaOrgId}/users`, {
        headers: adminHeaders,
        data: { email, display_name: `E2E Role Collapse ${suffix}`, password, role: "member" },
      });
      expect(created.ok()).toBeTruthy();
      userId = (await created.json()).user_id;
      await grantViaGroup("Admin", "project_administrator");
      await grantViaGroup("Stake", "stakeholder");
    });

    await test.step("the new user's own project list shows both tier-2 roles together, not a full unordered list", async () => {
      await logout(page);
      await loginAs(page, email, password);
      await page.goto("/projects");

      const gammaCard = page.locator(".card", { hasText: PROJECT_NAMES.gamma1 });
      await expect(gammaCard).toBeVisible();
      // Both tied tier-2 roles are shown; their order isn't specified.
      await expect(
        gammaCard.getByText(/^Your roles: (Project administrator, Stakeholder|Stakeholder, Project administrator)$/)
      ).toBeVisible();
      await expect(gammaCard.getByText("Your roles: Member", { exact: true })).toHaveCount(0);
    });

    await test.step("adding project_manager on top collapses the display to manager alone", async () => {
      await grantViaGroup("Manager", "project_manager");
      await page.reload();
      const gammaCard = page.locator(".card", { hasText: PROJECT_NAMES.gamma1 });
      await expect(gammaCard.getByText("Your roles: Project manager", { exact: true })).toBeVisible();
      await expect(gammaCard.getByText(/Stakeholder/)).toHaveCount(0);
    });


    await test.step("Org Admin's 'View access' panel shows the collapsed summary by default, with every role available via its expand toggle", async () => {
      // The panel defaults to the same collapsed summary compact lists use (docs/decisions.md and docs/ux-style-guide.md's
      // "Pattern: role display"), with a per-row "Show all N roles" toggle that reveals the full set on demand.
      await page.getByRole("button", { name: "Sign out" }).click();
      await page.waitForURL(/\/login$/);
      await loginAs(page, PERSONAS.orgAdminGamma.email);
      await page.goto("/orgs");
      await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
      await selectOrgAdminGroup(page, "Users");
      await ensureExpanded(page, "Organisation users");

      // The row's `ActionMenu` holds "View {name}'s access": open it through its kebab trigger (`${display name}'s
      // actions`), then the `menuitem` in the `Popover` (waiting for the menu itself, since the popover repositions after
      // mount), as other `ActionMenu` call sites in this suite do.
      const row = page.locator("tr", { hasText: email });
      const menuTriggerName = `E2E Role Collapse ${suffix}'s actions`;
      await row.getByRole("button", { name: menuTriggerName }).click();
      await expect(page.getByRole("menu", { name: menuTriggerName })).toBeVisible();
      await page.getByRole("menuitem", { name: /'s access$/ }).click();

      const panel = page.getByRole("dialog", { name: /'s access$/ });
      // Collapsed by default: `project_manager` is the sole top tier, so it alone shows, hiding the lower-tier
      // `project_administrator`/`stakeholder`/`member` roles also held on Gamma-1. Held roles total 4, not 3: `_normalize`
      // (`backend/app/services/rbac.py`) implicitly adds `project_administrator`+`stakeholder`+`member` alongside a
      // directly granted `project_manager`, on top of the two directly granted via the admin/stakeholder groups.
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
