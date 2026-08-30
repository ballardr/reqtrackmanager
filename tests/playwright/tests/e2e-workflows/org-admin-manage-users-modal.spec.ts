import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: Phase 5 (docs/decisions.md) — Org Admin's per-project
 * "Manage users" now opens a `Modal` wrapping the exact same
 * `MemberRoleTable` `ProjectAdminPage.tsx`'s own Members section uses,
 * replacing the old inline expand-in-place that duplicated a worse version
 * of the project admin page. No prior Playwright coverage existed for this
 * flow at all (grep confirms zero "Manage users" hits before this spec).
 *
 * Uses a brand-new, dedicated throwaway project (created via the API under
 * the shared single-admin Gamma org) rather than a shared seeded project —
 * this mutates a project group's role, and Gamma-1/Gamma-2/Gamma-3/Gamma-4
 * are all depended on by project-hierarchy.spec.ts's own exact
 * configuration.
 */
test.describe("org admin: Manage users modal", () => {
  test("opens the same MemberRoleTable as Project Admin's Members section, and its role controls work", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get("http://localhost:8000/api/v1/orgs", { headers: authHeaders })).json();
    const gammaOrg = orgs.find((o: { name: string }) => o.name === ORG_NAMES.gamma);

    const suffix = Date.now();
    const projectName = `E2E Manage Users Project ${suffix}`;
    await page.request.post("http://localhost:8000/api/v1/projects", {
      headers: authHeaders,
      data: { organization_id: gammaOrg.id, name: projectName, summary: "" },
    });

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

    await test.step("shows the project's default groups, each with an editable role control", async () => {
      const managerRoleSelect = modal.getByRole("combobox", { name: "Role for Project Managers" });
      await expect(managerRoleSelect).toHaveValue("project_manager");
      // C-U-08: the project's creator (this org admin, via the default
      // Project Managers group) is its only manager source on a
      // brand-new project — the same client-side last-manager hint
      // `ProjectAdminPage.tsx`'s own Members section gives.
      await expect(managerRoleSelect).toBeDisabled();

      const stakeholdersRoleSelect = modal.getByRole("combobox", { name: "Role for Stakeholders" });
      await expect(stakeholdersRoleSelect).toHaveValue("stakeholder");
      await expect(stakeholdersRoleSelect).toBeEnabled();
    });

    await test.step("changing a group's role calls the same PATCH .../groups/{id} endpoint the project's own admin page uses", async () => {
      const stakeholdersRoleSelect = modal.getByRole("combobox", { name: "Role for Stakeholders" });
      await stakeholdersRoleSelect.selectOption("project_administrator");
      await expect(page.getByText("Group updated")).toBeVisible();
      await expect(stakeholdersRoleSelect).toHaveValue("project_administrator");
    });

    await test.step("adding a direct member via the modal's own add control", async () => {
      await modal.getByRole("combobox", { name: "Role to grant" }).selectOption("member");
      await modal.getByPlaceholder("Type a name to add, or an email to invite…").fill(PERSONAS.projectMgrGamma.name);
      await page.getByText(PERSONAS.projectMgrGamma.email).click();
      // `exact: true`: Playwright's default substring matching would also
      // match the same row's Role cell, whose `MultiSelectDropdown`
      // trigger button's own accessible name ("<name>'s roles") contains
      // this name as a substring.
      await expect(modal.getByRole("cell", { name: PERSONAS.projectMgrGamma.name, exact: true })).toBeVisible();
    });

    await test.step("closing the modal returns to the plain project list row", async () => {
      await modal.getByRole("button", { name: "Close" }).click();
      await expect(modal).not.toBeVisible();
      await expect(projectRow.getByRole("button", { name: "Manage users" })).toBeVisible();
    });
  });
});
