import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: Phase D (follow-up UX batch, 2026-08-31, docs/decisions.md)
 * — the unified "Members" section (`ProjectMembersTable`, built on top of
 * `GET /effective-members`'s provenance) that replaced the old
 * `MemberRoleTable` (direct users + groups editable table) and the separate
 * effective-members audit table. Covers: adding a direct member with a
 * role, toggling a `direct_role`-kind role off, the C-U-08 last-manager
 * guard, a group-sourced role showing checked-and-disabled with an
 * explanatory title (the core Phase D fix — `DELETE /roles` would silently
 * no-op against it), and filtering by role. Pending-invite display/resend
 * and the "Show invited" toggle are covered by
 * `external-project-invite.spec.ts`, which already sets up an org that
 * permits external invites; no need to duplicate that org setup here.
 *
 * Uses a brand-new, dedicated throwaway project (created via the API under
 * the shared Beta org) rather than a shared seeded project — the
 * last-manager scenario specifically needs a project whose *only* manager
 * source is knowable and won't have been mutated by another spec sharing
 * this suite's run.
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

    await test.step("add a direct member with a role via the Members page's own add control", async () => {
      await page.getByRole("combobox", { name: "Role to grant" }).selectOption("stakeholder");
      await page.getByPlaceholder("Type a name to add, or an email to invite…").fill(PERSONAS.memberAlphaBeta.name);
      await page.getByText(PERSONAS.memberAlphaBeta.email).click();
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

    await test.step("toggling that same direct role off calls DELETE .../roles and the checkbox unchecks", async () => {
      const rolesButton = page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
      await rolesButton.click();
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
      const checkbox = rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Stakeholder from ${PERSONAS.memberAlphaBeta.name}`) });
      await expect(checkbox).toBeEnabled();
      await checkbox.click();
      await page.keyboard.press("Escape");
      // Re-fetches effective-members after the toggle — the row drops out
      // entirely once its only role/source is gone.
      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toHaveCount(0);
    });

    await test.step("C-U-08 last-manager guard: the fresh project's creator holds their only manager grant directly (no default group exists any more, follow-up UX batch Phase C, 2026-08-31), so that role checkbox is disabled", async () => {
      const rolesButton = page.getByRole("button", { name: `${PERSONAS.orgAdminAlphaBeta.name}'s roles` });
      await rolesButton.click();
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.orgAdminAlphaBeta.name}'s roles` });
      const managerCheckbox = rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Project manager from ${PERSONAS.orgAdminAlphaBeta.name}`) });
      await expect(managerCheckbox).toBeChecked();
      await expect(managerCheckbox).toBeDisabled();
      await expect(managerCheckbox).toHaveAttribute("title", /only manager source/);
      await page.keyboard.press("Escape");
    });

    await test.step("a role sourced from a group (not a direct grant) shows checked-and-disabled with an explanatory title", async () => {
      const orgUsers: { user_id: string; email: string }[] = await (
        await page.request.get(`http://localhost:8000/api/v1/orgs/${betaOrg.id}/users`, { headers: authHeaders })
      ).json();
      const memberUserId = orgUsers.find((u) => u.email === PERSONAS.memberAlphaBeta.email)!.user_id;

      const groupName = `E2E Members Group Source ${suffix}`;
      const group = await (
        await page.request.post(`http://localhost:8000/api/v1/projects/${project.id}/groups`, {
          headers: authHeaders,
          data: { name: groupName, role: "stakeholder" },
        })
      ).json();
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
      await expect(checkbox).toHaveAttribute("title", /isn't a direct grant/);
      await page.keyboard.press("Escape");
    });

    await test.step("filtering by role narrows the table to only members holding it", async () => {
      // Not `getByLabel`: `FilterField` wraps the `<select>` in a plain
      // `<label>` (text + control together), so the *label's own*
      // `textContent` a browser/Playwright's `getByLabel` reads includes
      // every rendered `<option>` text too ("RoleAll rolesProject
      // manager…"), which `{ exact: true }` can never equal literally
      // "Role" against. `getByRole`'s `name` instead uses the real
      // computed accessible name (which correctly excludes the select's
      // own option text), matching how every other `<select>`-inside-a-
      // `FilterField` locator elsewhere in this suite already does it.
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
