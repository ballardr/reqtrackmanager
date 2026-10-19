import { expect, test } from "@playwright/test";

import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";
import { installCleanupHook, loginAs, logout, openOrgGroupPanel, PASSWORD, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: users and groups on parity — the core records name groups too. A
 * Requirement's owner and reviewer, an Action's assignee and a record's watchers can
 * each be an organisation or project group; a member of the reviewer group sees the
 * review on their own due list; and deleting a group that still owns Requirements makes
 * the admin choose a replacement owner.
 *
 * Disposable org, admin and project via `setUpOrg`; the groups, Requirement and member are
 * created through the API, the assignments, watching and the group deletion through the UI.
 */
test.describe("Core records: groups as owners, reviewers, assignees and watchers", () => {
  test("a group owns and reviews a Requirement, takes an Action, watches it, and deleting it asks for a replacement owner", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "CoreGroups");
    const boardName = `Core Board ${suffix}`;
    const squadName = `Core Squad ${suffix}`;
    const memberEmail = `e2e-core-member-${suffix}@example.com`;
    const api = `${API_BASE_URL}/api/v1`;
    const post = async (path: string, data: unknown) => {
      const resp = await page.request.post(`${api}${path}`, { headers: adminHeaders, data });
      expect(resp.ok(), await resp.text()).toBeTruthy();
      const body = await resp.text();
      return body ? JSON.parse(body) : null;
    };

    const member = await post(`/orgs/${org.id}/users`, {
      email: memberEmail, display_name: `E2E Core Member ${suffix}`, password: PASSWORD, role: "member",
    });
    await post(`/projects/${project.id}/roles`, { user_id: member.user_id, role: "stakeholder" });
    const board = await post(`/orgs/${org.id}/groups`, { name: boardName });
    await post(`/orgs/${org.id}/groups/${board.id}/members`, { user_id: member.user_id });
    const squad = await post(`/projects/${project.id}/groups`, { name: squadName });
    const component = await post(`/projects/${project.id}/components`, { name: "Core", prefix: "CG" });
    const category = await post(`/projects/${project.id}/categories`, { name: "Safety", prefix: "SAF", component_id: component.id });
    const requirement = await post(`/projects/${project.id}/requirements`, {
      name: `Group owned ${suffix}`, component_id: component.id, category_id: category.id,
      owner: { type: "org_group", id: board.id }, reviewer: { type: "project_group", id: squad.id },
    });

    // --- The Requirement page names both groups with their kind.
    await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);
    await expect(page.getByRole("heading", { name: new RegExp(`Group owned ${suffix}`) })).toBeVisible();
    await expect(page.getByText(boardName).first()).toBeVisible();
    await expect(page.getByText(/^Org group/).first()).toBeVisible();
    await expect(page.getByText(squadName).first()).toBeVisible();

    // --- The board watches it; the panel lists it and lets the manager remove it again.
    const watchers = page.getByRole("region", { name: "Watching groups" });
    await watchers.getByRole("combobox", { name: "Add watching group" }).fill("Core Board");
    await page.getByRole("option", { name: new RegExp(boardName) }).click();
    await expect(page.getByText("Watching group added.")).toBeVisible();
    await expect(watchers.getByText(boardName)).toBeVisible();
    await page.reload();
    await expect(page.getByRole("region", { name: "Watching groups" }).getByText(boardName)).toBeVisible();

    // --- An Action can be assigned to the squad from the Actions page.
    await page.goto(`/projects/${project.id}/actions`);
    await page.getByRole("button", { name: /New action/ }).click();
    await page.getByLabel("Title").fill(`Squad action ${suffix}`);
    await page.getByRole("combobox", { name: "Assignee" }).fill("Core Squad");
    await page.getByRole("option", { name: new RegExp(squadName) }).click();
    await page.getByRole("button", { name: "Create", exact: true }).click();
    const row = page.locator("tr", { hasText: `Squad action ${suffix}` });
    await expect(row.getByText(squadName)).toBeVisible();
    await expect(row.getByText(/^Project group/)).toBeVisible();

    // --- A member of the reviewer group sees the review on their own "my reviews" list once its date has passed.
    await post(`/projects/${project.id}/groups/${squad.id}/members`, { user_id: member.user_id });
    await post(`/projects/${project.id}/requirements`, {
      name: `Due for the squad ${suffix}`, component_id: component.id, category_id: category.id,
      reviewer: { type: "project_group", id: squad.id }, review_date: "2024-01-01",
    });
    await logout(page);
    await loginAs(page, memberEmail, PASSWORD);
    await page.goto("/my-reviews");
    await expect(page.getByRole("link", { name: `Due for the squad ${suffix}` })).toBeVisible();

    // --- Deleting the board is blocked while it owns a Requirement (a mandatory owner): the admin picks a replacement.
    await logout(page);
    await loginAs(page, `e2e-coregroups-admin-${suffix}@example.com`, PASSWORD);
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Groups");
    const panel = await openOrgGroupPanel(page, boardName);
    await panel.getByRole("button", { name: "Delete group" }).click();
    await page.getByRole("dialog", { name: `Delete "${boardName}"?` }).getByRole("button", { name: "Delete group" }).click();

    const inUse = page.getByRole("dialog", { name: `Delete “${boardName}”?` });
    await expect(inUse.getByText(/1 requirement owners/)).toBeVisible();
    await expect(inUse.getByText("Some of these fields are required, so a replacement is needed.")).toBeVisible();
    await inUse.getByRole("combobox", { name: "New owner" }).fill("E2E CoreGroups Admin");
    await inUse.getByRole("option", { name: /E2E CoreGroups Admin/ }).click();
    await inUse.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.getByText("Group deleted", { exact: true })).toBeVisible();

    await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);
    await expect(page.getByText(/E2E CoreGroups Admin/).first()).toBeVisible();
    await expect(page.getByText(boardName)).toHaveCount(0);
  });
});
