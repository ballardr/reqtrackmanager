import { expect, test } from "@playwright/test";

import { installCleanupHook, openOrgGroupPanel, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: users and groups on parity, Phase 5 (docs/plans/
 * users-and-groups-parity-plan.md) — a Compliance standard can be owned by an
 * organisation group (never a project group), a required action can be assigned
 * to a project group, a scheduled review can be owned by one, and deleting an
 * organisation group that still owns a standard makes the admin choose a
 * replacement, because a standard always has an owner.
 *
 * Disposable org, admin and project via `setUpOrg`; the groups, the published
 * standard, its assignment and the review are created through the API, the
 * assignments and the group deletion through the UI.
 */
test.describe("Compliance: groups as owners and assignees", () => {
  test("a group owns a standard, is assigned a required action and owns a review, and deleting it hands the standard to someone else", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "ComplianceGroups", false, "Compliance");
    const teamName = `Compliance Office ${suffix}`;
    const squadName = `Field Squad ${suffix}`;
    const reference = `E2E-GRP-${suffix}`;
    const requirementName = `E2E Group Requirement ${suffix}`;
    const requiredActionName = `E2E Group Action ${suffix}`;
    const orgBase = `${API_BASE_URL}/api/v1/orgs/${org.id}/modules/compliance`;
    const projectBase = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/compliance`;

    const team = await (await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/groups`, { headers: adminHeaders, data: { name: teamName } })).json();
    const squad = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/groups`, { headers: adminHeaders, data: { name: squadName } })
    ).json();

    // A published standard owned by the organisation group, assigned to the project.
    const actionType = await (await page.request.post(`${orgBase}/action-types`, { headers: adminHeaders, data: { name: `Verify ${suffix}` } })).json();
    const standard = await (
      await page.request.post(`${orgBase}/standards`, {
        headers: adminHeaders,
        data: { reference, name: `E2E Group Standard ${suffix}`, initial_version_label: "1.0", owner: { type: "org_group", id: team.id } },
      })
    ).json();
    expect(standard.owner).toMatchObject({ type: "org_group", id: team.id });
    const versions = await (await page.request.get(`${orgBase}/standards/${standard.id}/versions`, { headers: adminHeaders })).json();
    const versionBase = `${orgBase}/standards/${standard.id}/versions/${versions[0].id}`;
    const requirement = await (await page.request.post(`${versionBase}/requirements`, { headers: adminHeaders, data: { name: requirementName } })).json();
    expect(
      (
        await page.request.post(`${versionBase}/requirements/${requirement.id}/required-actions`, {
          headers: adminHeaders, data: { action_type_id: actionType.id, name: requiredActionName },
        })
      ).ok(),
    ).toBeTruthy();
    expect((await page.request.post(`${versionBase}/publish`, { headers: adminHeaders })).ok()).toBeTruthy();
    const assignment = await (
      await page.request.post(`${orgBase}/projects/${project.id}/project-compliance`, {
        headers: adminHeaders, data: { standard_id: standard.id, standard_version_id: versions[0].id },
      })
    ).json();
    const review = await page.request.post(`${projectBase}/project-compliance/${assignment.id}/reviews`, {
      headers: adminHeaders,
      data: { frequency_label: `Quarterly board review ${suffix}`, next_due_date: "2030-01-01", owner: { type: "project_group", id: squad.id } },
    });
    expect(review.ok()).toBeTruthy();

    // --- The standard names its group owner with the kind; the edit dialog offers organisation groups only.
    await page.goto(`/standards/${standard.id}`);
    await expect(page.getByText(teamName).first()).toBeVisible();
    await expect(page.getByText(/^Org group/).first()).toBeVisible();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const editDialog = page.getByRole("dialog", { name: "Edit standard" });
    await editDialog.getByRole("combobox", { name: "Standard owner" }).fill("Field Squad");
    await expect(editDialog.getByRole("option", { name: new RegExp(squadName) })).toHaveCount(0);
    await editDialog.getByRole("button", { name: "Cancel" }).click();

    // --- A required action can be assigned to the project's group.
    await page.goto(`/projects/${project.id}/modules/compliance`);
    await page.getByText(new RegExp(reference)).click();
    await page.getByText(requirementName).click();
    await page.getByRole("combobox", { name: `Assignee for ${requiredActionName}` }).fill("Field Squad");
    await page.getByRole("option", { name: new RegExp(squadName) }).click();
    await expect(page.getByText(squadName).first()).toBeVisible();
    await expect(page.getByText(/^Project group/).first()).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();

    // --- The review names its project-group owner.
    await page.getByRole("tab", { name: "Reviews" }).click();
    await expect(page.getByText(`Quarterly board review ${suffix}`)).toBeVisible();
    await expect(page.getByText(squadName).first()).toBeVisible();

    // --- Deleting the org group is blocked while it owns the standard; the owner is required, so hand it to the admin.
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Groups");
    const panel = await openOrgGroupPanel(page, teamName);
    await panel.getByRole("button", { name: "Delete group" }).click();
    await page.getByRole("dialog", { name: `Delete "${teamName}"?` }).getByRole("button", { name: "Delete group" }).click();

    const inUse = page.getByRole("dialog", { name: `Delete “${teamName}”?` });
    await expect(inUse.getByText(/1 compliance standard owners/)).toBeVisible();
    await expect(inUse.getByText("Some of these fields are required, so a replacement is needed.")).toBeVisible();
    await inUse.getByRole("combobox", { name: "New owner" }).fill("E2E ComplianceGroups Admin");
    await inUse.getByRole("option", { name: /E2E ComplianceGroups Admin/ }).click();
    await inUse.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.getByText("Group deleted", { exact: true })).toBeVisible();

    // The standard now names the admin; the project group's assignment and review are untouched.
    await page.goto(`/standards/${standard.id}`);
    await expect(page.getByText(/E2E ComplianceGroups Admin/).first()).toBeVisible();
    await expect(page.getByText(teamName)).toHaveCount(0);
  });
});
