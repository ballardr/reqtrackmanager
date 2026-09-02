import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: Phase 5 (docs/decisions.md), rebuilt in Phase D (follow-up
 * UX batch, 2026-08-31) — Org Admin's per-project "Manage users" opens a
 * `Modal` wrapping the exact same `ProjectMembersTable`
 * `ProjectAdminPage.tsx`'s own Members section uses, fed by the same
 * `GET /effective-members`/`GET /pending-invites` endpoints — one real
 * shared implementation, not a parallel reimplementation. This is what
 * actually satisfies "org admin's view should look like project admin's,"
 * precisely.
 *
 * Uses a brand-new, dedicated throwaway project (created via the API under
 * the shared single-admin Gamma org) rather than a shared seeded project —
 * this mutates project role grants, and Gamma-1/Gamma-2/Gamma-3/Gamma-4 are
 * all depended on by project-hierarchy.spec.ts's own exact configuration.
 */
test.describe("org admin: Manage users modal", () => {
  test("shows the identical ProjectMembersTable Project Admin's own Members section uses, and its role controls work", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get("http://localhost:8000/api/v1/orgs", { headers: authHeaders })).json();
    const gammaOrg = orgs.find((o: { name: string }) => o.name === ORG_NAMES.gamma);

    const suffix = Date.now();
    const projectName = `E2E Manage Users Project ${suffix}`;
    const project = await (
      await page.request.post("http://localhost:8000/api/v1/projects", {
        headers: authHeaders,
        data: { organization_id: gammaOrg.id, name: projectName, summary: "" },
      })
    ).json();

    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Projects & workflow");
    // `.last()`, not `.first()`: every ancestor wrapper up to the whole
    // "Projects & workflow" section also matches `.stack:has-text(name)`
    // (the project name is somewhere within all of them too) — document
    // order lists outer wrappers before the specific per-project row, so
    // the *last* match is this project's own row, not the broadest one.
    const projectRow = page.locator(".stack", { hasText: projectName }).last();
    await projectRow.getByRole("button", { name: "Manage users" }).click();

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

    await test.step("shows the project's creator as a direct manager, disabled as the only manager source (C-U-08)", async () => {
      // The project's creator (this org admin) holds their manager role via
      // a direct grant on a brand-new project — no default group exists any
      // more (follow-up UX batch Phase C, 2026-08-31) — and is its only
      // manager source, the same client-side last-manager hint
      // `ProjectAdminPage.tsx`'s own Members section gives.
      const rolesButton = modal.getByRole("button", { name: `${PERSONAS.orgAdminGamma.name}'s roles` });
      await rolesButton.click();
      // Not scoped to `modal`: `MultiSelectDropdown`'s opened checkbox list
      // renders via `Popover`, which portals to `document.body` rather than
      // the modal's own DOM subtree.
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.orgAdminGamma.name}'s roles` });
      const managerCheckbox = rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Project manager from ${PERSONAS.orgAdminGamma.name}`) });
      await expect(managerCheckbox).toBeChecked();
      await expect(managerCheckbox).toBeDisabled();
      await expect(managerCheckbox).toHaveAttribute("title", /only manager source/);
      await page.keyboard.press("Escape");
    });

    await test.step("adding a direct member via the modal's own add control (PR3, members/groups directory rework: 'Add member' opens the control in a second, nested Modal instead of it sitting permanently inside this outer 'Manage users' Modal, per docs/ux-style-guide.md Principle 3)", async () => {
      await modal.getByRole("button", { name: "Add member" }).click();
      const addMemberModal = page.getByRole("dialog", { name: "Add member" });
      await addMemberModal.getByRole("combobox", { name: "Role to grant" }).selectOption("member");
      await addMemberModal.getByPlaceholder("Type a name to add, or an email to invite…").fill(PERSONAS.projectMgrGamma.name);
      await addMemberModal.getByText(PERSONAS.projectMgrGamma.email).click();
      // Selecting a match submits and closes only the nested modal — the
      // outer "Manage users" modal stays open underneath it.
      await expect(addMemberModal).not.toBeVisible();
      await expect(modal).toBeVisible();
      // `exact: true`: Playwright's default substring matching would also
      // match the same row's Role cell, whose `MultiSelectDropdown`
      // trigger button's own accessible name ("<name>'s roles") contains
      // this name as a substring.
      await expect(modal.getByRole("cell", { name: PERSONAS.projectMgrGamma.name, exact: true })).toBeVisible();
    });

    await test.step("toggling that same direct role off calls DELETE .../roles, same as Project Admin's own Members page", async () => {
      const rolesButton = modal.getByRole("button", { name: `${PERSONAS.projectMgrGamma.name}'s roles` });
      await rolesButton.click();
      const rolesGroup = page.getByRole("group", { name: `${PERSONAS.projectMgrGamma.name}'s roles` });
      const checkbox = rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Member from ${PERSONAS.projectMgrGamma.name}`) });
      await expect(checkbox).toBeEnabled();
      await checkbox.click();
      await page.keyboard.press("Escape");
      await expect(modal.getByRole("cell", { name: PERSONAS.projectMgrGamma.name, exact: true })).toHaveCount(0);
    });

    await test.step("closing the modal returns to the plain project list row", async () => {
      await modal.getByRole("button", { name: "Close" }).click();
      await expect(modal).not.toBeVisible();
      await expect(projectRow.getByRole("button", { name: "Manage users" })).toBeVisible();
    });
  });
});
