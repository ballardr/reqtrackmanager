import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, ORG_NAMES, PERSONAS, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: module system Phase 2 (docs/compliance-module-plan.md) —
 * module-contributed RBAC. Both surfaces this phase touches (`OrgAdminPage`'s
 * Users table Roles column, `ProjectMembersTable`'s own Role column) merge in
 * module-contributed role options alongside the fixed core-role ones.
 *
 * Updated for Compliance Module Phase 12 (see docs/compliance-module-plan.md's
 * Phase 12 notes): this spec originally scoped itself to "no real module yet"
 * and explicitly said to revisit once Phase 5 gave it a real module-
 * contributed role to interact with — Phase 5 shipped Compliance's
 * `compliance_manager` (org-scoped)/`compliance_officer` (project-scoped)
 * roles well before this session, but nothing had run this spec against a
 * live, freshly-rebuilt backend container since (see
 * `org-admin-modules.spec.ts`'s own updated docstring for why). This is that
 * overdue revisit: both dropdowns now assert the real fourth/fifth
 * module-contributed option alongside the fixed core-role set, not its
 * former "still exactly N core options, nothing leaked in" absence check.
 */
test.describe("module-contributed roles: Compliance's real org/project roles", () => {
  test("org admin Users table Roles dropdown includes Compliance Manager and still grants/revokes core roles", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/orgs");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Users");
    await ensureExpanded(page, "Organisation users");

    const rolesButton = page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
    await rolesButton.click();
    const rolesGroup = page.getByRole("group", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });

    // The three fixed OrgRole options plus Compliance's own org-scoped
    // module role, merged into the same dropdown per Phase 2's own design
    // ("Compliance Manager (Compliance)" — module.py's role name plus its
    // owning module's display name, OrgAdminPage.tsx's own worked example).
    await expect(rolesGroup.getByRole("checkbox")).toHaveCount(4);
    await expect(rolesGroup.getByText("Member", { exact: true })).toBeVisible();
    await expect(rolesGroup.getByText("Project creator", { exact: true })).toBeVisible();
    await expect(rolesGroup.getByText("Org admin", { exact: true })).toBeVisible();
    await expect(rolesGroup.getByText("Compliance Manager (Compliance)", { exact: true })).toBeVisible();

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

  test("project Members table Role dropdown includes Compliance Officer alongside the fixed ProjectRole options", async ({ page }) => {
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

    // The four fixed ProjectRole options plus Compliance's own project-
    // scoped module role — `ProjectMembersTable.tsx` renders a module
    // role's own `name` directly with no owning-module suffix (Phase 2's
    // own deliberate difference from the org-admin surface above, since no
    // module with roles existed yet to force a same-name collision).
    await expect(rolesGroup.getByRole("checkbox")).toHaveCount(5);
    await expect(rolesGroup.getByText("Compliance Officer", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
  });
});
