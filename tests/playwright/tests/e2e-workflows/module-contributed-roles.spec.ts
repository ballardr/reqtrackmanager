import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, ORG_NAMES, PERSONAS, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: module system Phase 2 (docs/compliance-module-plan.md) —
 * module-contributed RBAC. Both surfaces this phase touches (`OrgAdminPage`'s
 * Users table Roles column, `ProjectMembersTable`'s own Role column) merge in
 * module-contributed role options alongside the fixed core-role ones.
 *
 * Scope note, same reasoning `org-admin-modules.spec.ts` (Phase 1) already
 * documents: this deployment's real `INSTALLED_MODULES` registry
 * (`backend/app/modules/registry.py`) is genuinely empty until Phase 5 adds
 * the first real first-party module (Compliance), so there is no real
 * module-contributed role to toggle end-to-end here without fabricating a
 * fake production module package — explicitly against this repo's own
 * testing conventions. Interactive toggle coverage (a module-role option
 * present, checked/unchecked, grant/revoke calling the new endpoints) lives
 * at the Storybook level instead (`ProjectMembersTable.stories.tsx`'s
 * `ModuleRolesAvailable` story, `OrgAdminPage.stories.tsx`'s
 * `UsersSectionModuleRoleGrantAndRevoke` story, both of which mock the new
 * endpoints) and the backend pytest level
 * (`backend/tests/test_module_contributed_roles.py`). This spec is
 * deliberately scoped to what's real and verifiable end-to-end today:
 * confirming nothing regressed for the current no-modules-yet reality — the
 * Roles dropdown on both surfaces still renders exactly its fixed core-role
 * option set (no stray/broken extra option, no crash from the new
 * `GET .../module-roles` fetch failing) and still grants/revokes a core role
 * correctly. Revisit once Phase 5 gives this spec a real module-contributed
 * role to interact with.
 */
test.describe("module-contributed roles: no modules registered yet", () => {
  test("org admin Users table Roles dropdown renders only the fixed OrgRole options and still grants/revokes", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/orgs");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Users");
    await ensureExpanded(page, "Organisation users");

    const rolesButton = page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
    await rolesButton.click();
    const rolesGroup = page.getByRole("group", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });

    // Exactly the three fixed OrgRole options — no fourth, module-
    // contributed option leaked in from a failed/empty `GET .../module-
    // roles` fetch, and no crash rendering an empty `availableOrgModuleRoles`.
    await expect(rolesGroup.getByRole("checkbox")).toHaveCount(3);
    await expect(rolesGroup.getByText("Member", { exact: true })).toBeVisible();
    await expect(rolesGroup.getByText("Project creator", { exact: true })).toBeVisible();
    await expect(rolesGroup.getByText("Org admin", { exact: true })).toBeVisible();

    const grantCheckbox = rolesGroup.getByRole("checkbox", {
      name: new RegExp(`Grant Project creator to ${PERSONAS.memberAlphaBeta.name}`),
    });
    await grantCheckbox.click();
    await expect(
      rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Project creator from ${PERSONAS.memberAlphaBeta.name}`) })
    ).toBeChecked();

    // Clean up: revoke it back off, so this spec leaves no lingering state
    // for another spec sharing this persona (this repo's standing
    // test-idempotency rule).
    await rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke Project creator from ${PERSONAS.memberAlphaBeta.name}`) }).click();
    await expect(
      rolesGroup.getByRole("checkbox", { name: new RegExp(`Grant Project creator to ${PERSONAS.memberAlphaBeta.name}`) })
    ).not.toBeChecked();
    await page.keyboard.press("Escape");
  });

  test("project Members table Role dropdown renders only the fixed ProjectRole options with no module-role options", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get("http://localhost:8000/api/v1/orgs", { headers: authHeaders })).json();
    const alphaOrg = orgs.find((o: { name: string }) => o.name === ORG_NAMES.alpha);

    const suffix = Date.now();
    const project = await (
      await page.request.post("http://localhost:8000/api/v1/projects", {
        headers: authHeaders,
        data: { organization_id: alphaOrg.id, name: `E2E Module Roles Project ${suffix}`, summary: "" },
      })
    ).json();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Members");

    // The project's creator (this persona) is its own direct project
    // manager — same fixture shape `project-admin-members.spec.ts` already
    // relies on for its own last-manager step.
    const rolesButton = page.getByRole("button", { name: `${PERSONAS.orgAdminAlphaBeta.name}'s roles` });
    await rolesButton.click();
    const rolesGroup = page.getByRole("group", { name: `${PERSONAS.orgAdminAlphaBeta.name}'s roles` });

    // Exactly the four fixed ProjectRole options — no module-contributed
    // option leaked in from `GET /{project_id}/module-roles` returning an
    // empty list (the real state of this deployment today, no module has
    // any roles until Phase 5).
    await expect(rolesGroup.getByRole("checkbox")).toHaveCount(4);
    await page.keyboard.press("Escape");
  });
});
