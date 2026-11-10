import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: an organisation administrator finds a project they hold no role in on the main project list (the
 * "Include projects I am not a member of" filter, off by default), and its gear opens a "Manage users" dialog wrapping
 * the exact same `ProjectMembersTable` the project's own Members section uses, fed by the same
 * `GET /effective-members`/`GET /pending-invites` endpoints. The row carries identity only and is not a link.
 *
 * Uses a brand-new, dedicated throwaway project (created via the API under the shared single-admin Gamma org, then
 * handed to another manager so the administrator holds no role in it) rather than a shared seeded project: this
 * mutates project role grants, and Gamma-1/Gamma-2/Gamma-3/Gamma-4 are all depended on by other specs.
 */
test.describe("org admin: Manage users from the project list", () => {
  test("lists a project they are not a member of behind a filter, and its gear opens the shared members table", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const api = "http://localhost:8000/api/v1";
    const orgs = await (await page.request.get(`${api}/orgs`, { headers: authHeaders })).json();
    const gammaOrg = orgs.find((o: { name: string }) => o.name === ORG_NAMES.gamma);
    const me = await (await page.request.get(`${api}/auth/me`, { headers: authHeaders })).json();
    const users = await (await page.request.get(`${api}/orgs/${gammaOrg.id}/users?limit=100`, { headers: authHeaders })).json();
    const manager = users.find((u: { email: string }) => u.email === PERSONAS.projectMgrGamma.email);

    const suffix = Date.now();
    const projectName = `E2E Manage Users Project ${suffix}`;
    const project = await (
      await page.request.post(`${api}/projects`, {
        headers: authHeaders,
        data: { organization_id: gammaOrg.id, name: projectName, summary: "" },
      })
    ).json();
    // Hand the project to another manager, then drop the administrator's own role: they now hold none in it.
    await page.request.post(`${api}/projects/${project.id}/roles`, {
      headers: authHeaders, data: { user_id: manager.user_id, role: "project_manager" },
    });
    await page.request.delete(`${api}/projects/${project.id}/roles/${me.id}/project_manager`, { headers: authHeaders });

    await page.goto("/projects");
    const filter = page.getByRole("checkbox", { name: "Include projects I am not a member of" });
    await test.step("the filter is offered to the administrator, off by default, and the project is not listed", async () => {
      await expect(filter).toBeVisible();
      await expect(filter).not.toBeChecked();
      await expect(page.getByText(PROJECT_NAMES.gamma1)).toBeVisible();
      await expect(page.getByText(projectName)).toHaveCount(0);
    });

    await test.step("ticking it adds the project as a muted row that is not a link, with a gear", async () => {
      await filter.check();
      await expect(page.getByText(projectName)).toBeVisible();
      await expect(page.getByRole("link", { name: projectName })).toHaveCount(0);
      await expect(page.getByText("Not a member").first()).toBeVisible();
    });

    await page.getByRole("button", { name: `Manage users of ${projectName}` }).click();
    const modal = page.getByRole("dialog", { name: `Manage users — ${projectName}` });
    await expect(modal).toBeVisible();

    await test.step("the filter panel renders as a full-width bar above the table inside the modal, not a cramped sidebar (follow-up UX fix)", async () => {
      const filterPanel = modal.locator(".filter-panel-top");
      const table = modal.getByRole("table");
      await expect(filterPanel).toBeVisible();
      await expect(table).toBeVisible();
      const panelBox = await filterPanel.boundingBox();
      const tableBox = await table.boundingBox();
      expect(panelBox).not.toBeNull();
      expect(tableBox).not.toBeNull();
      expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(tableBox!.y + 1);
      expect(panelBox!.width).toBeGreaterThanOrEqual(tableBox!.width - 1);
    });

    await test.step("shows the manager as a direct manager, disabled as the only manager source (C-U-08)", async () => {
      // The manager holds their role via a direct grant and is its only
      // manager source, the same client-side last-manager hint
      // `ProjectAdminPage.tsx`'s own Members section gives.
      const rolesButton = modal.getByRole("button", { name: `${PERSONAS.projectMgrGamma.name}'s roles` });
      await rolesButton.click();
      // Not scoped to `modal`: `MultiSelectDropdown`'s opened checkbox list
      // renders via `Popover`, which portals to `document.body` rather than
      // the modal's own DOM subtree.
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.projectMgrGamma.name}'s roles` });
      const managerCheckbox = rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Project manager from ${PERSONAS.projectMgrGamma.name}`) });
      await expect(managerCheckbox).toBeChecked();
      await expect(managerCheckbox).toBeDisabled();
      await expect(managerCheckbox).toHaveAttribute("title", /only manager source/);
      await page.keyboard.press("Escape");
    });

    await test.step("adding a direct member via the modal's own add control (members/groups directory rework: 'Add member' opens the control in a second, nested Modal instead of it sitting permanently inside this outer 'Manage users' Modal, per docs/ux-style-guide.md Principle 3; rebuilt onto the shared `AddMembersModal` staged multi-add — see that component's own module docstring)", async () => {
      await modal.getByRole("button", { name: "Add member" }).click();
      const addMemberModal = page.getByRole("dialog", { name: "Add member" });
      await addMemberModal.getByPlaceholder("Type a name to add, or an email to invite…").fill(PERSONAS.orgAdminGamma.name);
      await addMemberModal.getByRole("option", { name: new RegExp(PERSONAS.orgAdminGamma.name) }).click();

      // Picking a match only stages it — nothing is granted, and both
      // modals stay open, until the commit button is pressed.
      await expect(addMemberModal.getByText(`${PERSONAS.orgAdminGamma.name} (${PERSONAS.orgAdminGamma.email})`)).toBeVisible();
      await expect(modal.getByRole("cell", { name: PERSONAS.orgAdminGamma.name, exact: true })).toHaveCount(0);

      await addMemberModal.getByRole("button", { name: "Add 1 member" }).click();
      // Committing (with no other staged entries pending) closes only the
      // nested modal — the outer "Manage users" modal stays open underneath.
      await expect(addMemberModal).not.toBeVisible();
      await expect(modal).toBeVisible();
      // `exact: true`: Playwright's default substring matching would also
      // match the same row's Role cell, whose `MultiSelectDropdown`
      // trigger button's own accessible name ("<name>'s roles") contains
      // this name as a substring.
      await expect(modal.getByRole("cell", { name: PERSONAS.orgAdminGamma.name, exact: true })).toBeVisible();
    });

    await test.step("toggling that same direct role off calls DELETE .../roles, same as Project Admin's own Members page", async () => {
      const rolesButton = modal.getByRole("button", { name: `${PERSONAS.orgAdminGamma.name}'s roles` });
      await rolesButton.click();
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.orgAdminGamma.name}'s roles` });
      const checkbox = rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Member from ${PERSONAS.orgAdminGamma.name}`) });
      await expect(checkbox).toBeEnabled();
      await checkbox.click();
      // Revoking the user's only role removes their row — and its dropdown
      // with it. An unconditional Escape raced that: if the row had already
      // unmounted, Escape closed the whole modal instead (making the
      // row-gone check pass vacuously and the "Close" step below hang).
      // Wait for the row to go, and only press Escape if the dropdown
      // survived.
      await expect(modal.getByRole("cell", { name: PERSONAS.orgAdminGamma.name, exact: true })).toHaveCount(0);
      if (await rolesGroup.isVisible()) await page.keyboard.press("Escape");
      await expect(modal).toBeVisible();
    });

    await test.step("closing the dialog returns to the list; the project is still not a link", async () => {
      await modal.getByRole("button", { name: "Close" }).click();
      await expect(modal).not.toBeVisible();
      await expect(page.getByRole("button", { name: `Manage users of ${projectName}` })).toBeVisible();
    });

    await test.step("Organisation administration no longer lists projects", async () => {
      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Projects");
      await expect(page.getByRole("button", { name: "Manage users", exact: true })).toHaveCount(0);
      await expect(page.getByText(projectName)).toHaveCount(0);
    });
  });

  test("the filter is not offered to a person who does not administer an organisation", async ({ page }) => {
    await loginAs(page, PERSONAS.projectMgrGamma.email);
    await page.goto("/projects");
    await expect(page.getByRole("checkbox", { name: "Favourites only" })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Include projects I am not a member of" })).toHaveCount(0);
  });
});
