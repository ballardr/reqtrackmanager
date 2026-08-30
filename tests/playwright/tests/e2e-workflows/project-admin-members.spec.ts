import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: Phase 5 (docs/decisions.md) — the new "Members" section
 * (`MemberRoleTable`, direct users + groups with an editable role control
 * each) and its interplay with the Groups section: changing a group's role
 * from the Members table (`PATCH .../groups/{id}`, the fix for "project
 * groups' role was fixed at creation"), the C-U-08 last-manager guard
 * surfacing as a disabled control, and the `?openGroup=` deep link from a
 * Members-page group row into the Groups section's own `SidePanel`.
 *
 * Uses a brand-new, dedicated throwaway project (created via the API under
 * the shared Beta org) rather than a shared seeded project — the
 * last-manager scenario specifically needs a project whose *only* manager
 * source is knowable and won't have been mutated by another spec sharing
 * this suite's run.
 */
test.describe("project admin: Members section", () => {
  test("change a group's role from Members, add a direct member, last-manager guard, and the openGroup deep link", async ({ page }) => {
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
    const groupName = `E2E Reviewers ${suffix}`;

    await test.step("create a group on the Groups page", async () => {
      await selectProjectAdminGroup(page, "Project groups");
      await page.getByRole("button", { name: "New group" }).click();
      const dialog = page.getByRole("dialog", { name: "New group" });
      await dialog.getByPlaceholder("e.g. Reviewers").fill(groupName);
      await dialog.getByLabel("Role").selectOption("stakeholder");
      await dialog.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText("Group created")).toBeVisible();
      await expect(page.getByRole("button", { name: new RegExp(`^${groupName}`) })).toContainText("Stakeholder");
    });

    await test.step("change its role from the Members table's own dropdown", async () => {
      await selectProjectAdminGroup(page, "Members");
      const roleSelect = page.getByRole("combobox", { name: `Role for ${groupName}` });
      await expect(roleSelect).toHaveValue("stakeholder");
      await roleSelect.selectOption("project_administrator");
      await expect(page.getByText("Group updated")).toBeVisible();
    });

    await test.step("the change is reflected on the Groups page's own SidePanel, no refetch needed", async () => {
      await selectProjectAdminGroup(page, "Project groups");
      await page.getByRole("button", { name: new RegExp(`^${groupName}`) }).click();
      const panel = page.getByRole("dialog", { name: `${groupName} details` });
      await expect(panel.getByRole("combobox", { name: "Group role" })).toHaveValue("project_administrator");
      await page.getByRole("button", { name: "Close" }).click();
    });

    await test.step("add a direct member with a role via the Members page's own add control", async () => {
      await selectProjectAdminGroup(page, "Members");
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

    await test.step("C-U-08 last-manager guard: the default Project Managers group is this fresh project's only manager source, so its role control is disabled", async () => {
      const managerSelect = page.getByRole("combobox", { name: "Role for Project Managers" });
      await expect(managerSelect).toBeDisabled();
      await expect(managerSelect).toHaveAttribute("title", /only manager source/);
    });

    await test.step("?openGroup= deep link opens that group's SidePanel directly", async () => {
      const groups: { id: string; name: string }[] = await page
        .request.get(`http://localhost:8000/api/v1/projects/${project.id}/groups`, { headers: authHeaders })
        .then((r) => r.json());
      const group = groups.find((g) => g.name === groupName)!;

      await page.goto(`/projects/${project.id}/admin/groups?openGroup=${group.id}`);
      const panel = page.getByRole("dialog", { name: `${groupName} details` });
      await expect(panel).toBeVisible();
      // The param is cleared once consumed (`ProjectAdminPage.tsx`'s own
      // `useSearchParams` effect), so browser-back doesn't reopen it
      // unexpectedly — a real URL, not client-only state, per
      // `ResourceMenu`'s own bookmarkability principle.
      await expect(page).not.toHaveURL(/openGroup=/);
    });
  });
});
