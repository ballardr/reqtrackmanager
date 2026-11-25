import { expect, test } from "@playwright/test";

import { expectReasonTooltip, loginAs, ORG_NAMES, PERSONAS, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done (docs/decisions.md): the unified "Members" section (`ProjectMembersTable`, built on
 * `GET /effective-members`'s provenance). Covers: adding a direct member with a role, toggling a `direct_role`-kind
 * role off, the C-U-08 last-manager guard, a group-sourced role showing checked-and-disabled with an explanatory
 * title (`DELETE /roles` would silently no-op against it), and filtering by role. Pending-invite display/resend and
 * the "Show invited" toggle are covered by `external-project-invite.spec.ts`, which sets up an org that permits
 * external invites.
 *
 * Uses a dedicated throwaway project (created through the API under the shared Beta org): the last-manager scenario
 * needs a project whose only manager source is known and not mutated by another spec.
 */
test.describe("project admin: Members section", () => {
  test("add a direct member, toggle a role off, last-manager guard, group-sourced role disabled, and role filter", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get("http://localhost:8000/api/v1/orgs", { headers: authHeaders })).json();
    const betaOrg = orgs.find((o: { name: string }) => o.name === ORG_NAMES.beta);

    const suffix = Date.now();
    const project = await (
      await page.request.post("http://localhost:8000/api/v1/projects", {
        headers: authHeaders,
        data: { organization_id: betaOrg.id, name: `E2E Members Project ${suffix}`, summary: "" },
      })
    ).json();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Members");

    await test.step("the filter panel renders as a full-width bar above the table, not a cramped sidebar (follow-up UX fix — ProjectMembersTable's Role/Source columns crowded the old 240px side sidebar)", async () => {
      const filterPanel = page.locator(".filter-panel-top");
      const table = page.getByRole("table");
      await expect(filterPanel).toBeVisible();
      await expect(table).toBeVisible();
      const panelBox = await filterPanel.boundingBox();
      const tableBox = await table.boundingBox();
      expect(panelBox).not.toBeNull();
      expect(tableBox).not.toBeNull();
      expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(tableBox!.y + 1);
      expect(panelBox!.width).toBeGreaterThanOrEqual(tableBox!.width - 1);
    });

    await test.step("add a direct member with a role via the Members page's own add control ('Add member' opens the control in a Modal on the shared `AddMembersModal` staged multi-add)", async () => {
      await page.getByRole("button", { name: "Add member" }).click();
      const modal = page.getByRole("dialog", { name: "Add member" });
      await modal.getByPlaceholder("Type a name to add, or an email to invite…").fill(PERSONAS.memberAlphaBeta.name);
      await modal.getByRole("option", { name: new RegExp(PERSONAS.memberAlphaBeta.name) }).click();

      // Staged, not yet granted — set this row's own role before
      // committing (defaults to "member").
      const stagedRoleSelect = modal.getByRole("combobox", {
        name: `Role for ${PERSONAS.memberAlphaBeta.name} (${PERSONAS.memberAlphaBeta.email})`,
      });
      await stagedRoleSelect.selectOption("stakeholder");
      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toHaveCount(0);

      await modal.getByRole("button", { name: "Add 1 member" }).click();
      // Every staged entry succeeded — the modal closes itself.
      await expect(modal).not.toBeVisible();
      // `exact: true`: Playwright's default substring matching would also
      // match the same row's Role cell, whose `MultiSelectDropdown`
      // trigger button's own accessible name ("<name>'s roles") contains
      // this name as a substring.
      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toBeVisible();
      const rolesButton = page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
      await expect(rolesButton).toBeVisible();
      await rolesButton.click();
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
      await expect(rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Stakeholder from ${PERSONAS.memberAlphaBeta.name}`) })).toBeChecked();
      await page.keyboard.press("Escape");
    });

    await test.step("the member's only role cannot be cleared (it would remove the member at once); Remove all access is the explicit way", async () => {
      const rolesButton = page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
      await rolesButton.click();
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
      const checkbox = rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Stakeholder from ${PERSONAS.memberAlphaBeta.name}`) });
      await expect(checkbox).toBeChecked();
      await expect(checkbox).toBeDisabled();
      await expectReasonTooltip(page, checkbox, /only role/);

      // Granting another role first makes the original clearable, and the member stays listed throughout.
      await rolesGroup.getByRole("checkbox", { name: new RegExp(`Grant Member to ${PERSONAS.memberAlphaBeta.name}`) }).click();
      await expect(checkbox).toBeEnabled();
      await checkbox.click();
      await expect(rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Stakeholder from`) })).toHaveCount(0);
      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toBeVisible();
      await page.keyboard.press("Escape");

      await page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s actions` }).click();
      await page.getByRole("menuitem", { name: "Remove all access" }).click();
      await page.getByRole("button", { name: "Remove access" }).click();
      // Re-fetches effective-members after the removal: the row drops out once its only role/source is gone.
      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toHaveCount(0);
    });

    await test.step("C-U-08 last-manager guard: the fresh project's creator holds their only manager grant directly (no default group exists any more, 2026-08-31), so that role checkbox is disabled", async () => {
      const rolesButton = page.getByRole("button", { name: `${PERSONAS.orgAdminAlphaBeta.name}'s roles` });
      await rolesButton.click();
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.orgAdminAlphaBeta.name}'s roles` });
      const managerCheckbox = rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Project manager from ${PERSONAS.orgAdminAlphaBeta.name}`) });
      await expect(managerCheckbox).toBeChecked();
      await expect(managerCheckbox).toBeDisabled();
      await expectReasonTooltip(page, managerCheckbox, /only manager source/);
      await page.keyboard.press("Escape");
    });

    await test.step("a role sourced from a group (not a direct grant) shows checked-and-disabled with an explanatory title", async () => {
      const orgUsers: { user_id: string; email: string }[] = await (
        await page.request.get(`http://localhost:8000/api/v1/orgs/${betaOrg.id}/users`, { headers: authHeaders })
      ).json();
      const memberUserId = orgUsers.find((u) => u.email === PERSONAS.memberAlphaBeta.email)!.user_id;

      const groupName = `E2E Members Group Source ${suffix}`;
      // A group takes no role: create bare, then grant it separately.
      const group = await (
        await page.request.post(`http://localhost:8000/api/v1/projects/${project.id}/groups`, {
          headers: authHeaders,
          data: { name: groupName },
        })
      ).json();
      await page.request.post(`http://localhost:8000/api/v1/projects/${project.id}/groups/${group.id}/roles`, {
        headers: authHeaders,
        data: { role: "stakeholder" },
      });
      await page.request.post(`http://localhost:8000/api/v1/projects/${project.id}/groups/${group.id}/members`, {
        headers: authHeaders,
        data: { user_id: memberUserId },
      });
      await page.reload();

      const rolesButton = page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
      await expect(rolesButton).toBeVisible();
      await rolesButton.click();
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
      const checkbox = rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Stakeholder from ${PERSONAS.memberAlphaBeta.name}`) });
      await expect(checkbox).toBeChecked();
      await expect(checkbox).toBeDisabled();
      await expectReasonTooltip(page, checkbox, /is not a direct grant/);
      await page.keyboard.press("Escape");
    });

    await test.step("filtering by role narrows the table to only members holding it", async () => {
      // Not `getByLabel`: `FilterField` wraps the `<select>` in a plain `<label>`, so the label's `textContent` includes
      // every rendered `<option>` text ("RoleAll rolesProject manager…") and `{ exact: true }` never equals "Role".
      // `getByRole`'s `name` uses the computed accessible name, which excludes the option text, as every other
      // `FilterField` `<select>` locator in this suite does.
      const roleFilter = page.getByRole("combobox", { name: "Role", exact: true });
      await roleFilter.selectOption("stakeholder");
      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toBeVisible();
      await expect(page.getByRole("cell", { name: PERSONAS.orgAdminAlphaBeta.name, exact: true })).toHaveCount(0);

      await roleFilter.selectOption("project_manager");
      await expect(page.getByRole("cell", { name: PERSONAS.orgAdminAlphaBeta.name, exact: true })).toBeVisible();
      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toHaveCount(0);

      await roleFilter.selectOption("");
    });
  });
});
