import { expect, test } from "@playwright/test";

import { installCleanupHook, openOrgGroupPanel, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: users and groups on parity, Phase 4 (docs/plans/
 * users-and-groups-parity-plan.md) — a Pain Point, a Guiding Principle and an
 * Open Question can each be owned by an organisation group or a project group,
 * the Open Question register names a group owner with its kind, and deleting a
 * group that still owns them lets the admin hand them to someone else.
 *
 * Disposable org, admin and project via `setUpOrg` (Context & Strategy switched
 * on); the groups and records are created through the API, the assignments and
 * the group deletion through the UI.
 */
test.describe("Context & Strategy: groups as owners", () => {
  test("a group owns a Pain Point, Guiding Principle and Open Question, and deleting it hands them to someone else", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "ContextGroups", false, "Context & Strategy");
    const teamName = `Strategy Board ${suffix}`;
    const squadName = `Field Squad ${suffix}`;
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy`;

    const team = await (await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/groups`, { headers: adminHeaders, data: { name: teamName } })).json();
    expect(
      (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/groups`, { headers: adminHeaders, data: { name: squadName } })).ok(),
    ).toBeTruthy();

    const types = await (await page.request.get(`${base}/pain-point-types`, { headers: adminHeaders })).json();
    const painPoint = await (
      await page.request.post(`${base}/pain-points`, {
        headers: adminHeaders, data: { pain_point_type_id: types[0].id, title: `Reports arrive late ${suffix}`, priority: "high" },
      })
    ).json();
    const principle = await (
      await page.request.post(`${base}/guiding-principles`, {
        headers: adminHeaders,
        data: { name: `Capture once ${suffix}`, principle_statement: "Record each observation exactly once.", owner: { type: "org_group", id: team.id } },
      })
    ).json();
    const question = await (
      await page.request.post(`${base}/open-questions`, { headers: adminHeaders, data: { question: `One vendor ${suffix}?`, priority: "medium" } })
    ).json();

    // --- Assign the org group to the Pain Point and the project group to the Open Question.
    await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${painPoint.id}`);
    await expect(page.getByRole("heading", { name: `Reports arrive late ${suffix}` })).toBeVisible();
    await page.getByRole("combobox", { name: "Pain Point owner" }).fill("Strategy Board");
    await page.getByRole("option", { name: new RegExp(teamName) }).click();
    await expect(page.getByText("Owner updated.")).toBeVisible();

    await page.goto(`/projects/${project.id}/modules/context_strategy/open-questions/${question.id}`);
    await expect(page.getByRole("heading", { name: `One vendor ${suffix}?` })).toBeVisible();
    await page.getByRole("combobox", { name: "Open Question owner" }).fill("Field Squad");
    await page.getByRole("option", { name: new RegExp(squadName) }).click();
    await expect(page.getByText("Owner updated.")).toBeVisible();

    // The group is named with its kind, and survives a reload.
    await page.reload();
    await expect(page.getByText(squadName).first()).toBeVisible();
    await expect(page.getByText(/^Project group/).first()).toBeVisible();
    await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${painPoint.id}`);
    await expect(page.getByText(teamName).first()).toBeVisible();
    await expect(page.getByText(/^Org group/).first()).toBeVisible();

    // The Guiding Principle created with a group owner shows it too.
    await page.goto(`/projects/${project.id}/modules/context_strategy/guiding-principles/${principle.id}`);
    await expect(page.getByText(teamName).first()).toBeVisible();

    // --- The Open Question register prints the group with its kind, rather than a person's name.
    await page.goto(`/projects/${project.id}/reports?report=open-question-register`);
    await expect(page.getByText(`${squadName} (Project group)`).first()).toBeVisible();

    // --- Deleting the org group is blocked while it owns records; hand them to the admin.
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Groups");
    const panel = await openOrgGroupPanel(page, teamName);
    await panel.getByRole("button", { name: "Delete group" }).click();
    await page.getByRole("dialog", { name: `Delete "${teamName}"?` }).getByRole("button", { name: "Delete group" }).click();

    const inUse = page.getByRole("dialog", { name: `Delete “${teamName}”?` });
    await expect(inUse.getByText(/1 pain point owners/)).toBeVisible();
    await expect(inUse.getByText(/1 guiding principle owners/)).toBeVisible();
    // Every Context & Strategy owner is optional, so no replacement is required.
    await expect(inUse.getByText("Some of these fields are required, so a replacement is needed.")).toHaveCount(0);
    await inUse.getByRole("combobox", { name: "New owner" }).fill("E2E ContextGroups Admin");
    await inUse.getByRole("option", { name: /E2E ContextGroups Admin/ }).click();
    await inUse.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.getByText("Group deleted", { exact: true })).toBeVisible();

    // The records now name the admin; the project-group Open Question is untouched.
    await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${painPoint.id}`);
    await expect(page.getByText(/E2E ContextGroups Admin/).first()).toBeVisible();
    await expect(page.getByText(teamName)).toHaveCount(0);
    await page.goto(`/projects/${project.id}/modules/context_strategy/open-questions/${question.id}`);
    await expect(page.getByText(squadName).first()).toBeVisible();
  });
});
