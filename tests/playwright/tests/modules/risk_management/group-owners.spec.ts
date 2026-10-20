import { expect, test } from "@playwright/test";

import { installCleanupHook, openOrgGroupPanel, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, createRisk, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: users and groups on parity, Risk Management's owner
 * — a Risk can be owned by an
 * organisation group or a project group, the register and the Risk page name a
 * group owner with its kind, and deleting a group that still owns a Risk lets
 * the admin hand it to someone else.
 *
 * Disposable org, admin and project via `setUpOrg` (Risk Management switched
 * on); the groups and one Risk are created through the API, the owner choice
 * and the group deletion through the UI.
 */
test.describe("Risk Management: groups as owners", () => {
  test("a group owns a Risk, the register names it with its kind, and deleting it hands the Risk to someone else", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "RiskGroups");
    const boardName = `Safety Board ${suffix}`;
    const squadName = `Release Squad ${suffix}`;
    const groups = {
      board: await (await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/groups`, { headers: adminHeaders, data: { name: boardName } })).json(),
      squad: await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/groups`, { headers: adminHeaders, data: { name: squadName } })).json(),
    };
    const squadRiskTitle = `Squad-owned risk ${suffix}`;
    await createRisk(page, project.id, adminHeaders, { title: squadRiskTitle, owner: { type: "project_group", id: groups.squad.id } });

    // --- Create a Risk owned by the organisation group, through the form.
    const title = `Board-owned risk ${suffix}`;
    await page.goto(`/projects/${project.id}/modules/risk_management/risks`);
    await page.getByRole("button", { name: "New risk" }).click();
    const dialog = page.getByRole("dialog", { name: "New risk" });
    await dialog.getByLabel("Risk title").fill(title);
    await dialog.getByRole("combobox", { name: "Owner" }).fill("Safety Board");
    await dialog.getByRole("option", { name: new RegExp(boardName) }).click();
    await expect(dialog.getByText(/^Org group/)).toBeVisible();
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Risk created.")).toBeVisible();

    // --- The register names each group with its kind, rather than a person's name.
    const boardRow = page.locator("tr", { hasText: title });
    await expect(boardRow.getByText(boardName)).toBeVisible();
    await expect(boardRow.getByText(/^Org group/)).toBeVisible();
    const squadRow = page.locator("tr", { hasText: squadRiskTitle });
    await expect(squadRow.getByText(squadName)).toBeVisible();
    await expect(squadRow.getByText(/^Project group/)).toBeVisible();

    // --- The Risk page shows the owner, and the register report prints the kind in text.
    await boardRow.getByRole("link", { name: /RSK-/ }).click();
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    await expect(page.getByText(boardName).first()).toBeVisible();
    await page.goto(`/projects/${project.id}/reports?report=risk-register`);
    await expect(page.getByText(`${boardName} (Org group)`).first()).toBeVisible();

    // --- Deleting the org group is blocked while it owns a Risk; hand the Risk to the admin.
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Groups");
    const panel = await openOrgGroupPanel(page, boardName);
    await panel.getByRole("button", { name: "Delete group" }).click();
    await page.getByRole("dialog", { name: `Delete "${boardName}"?` }).getByRole("button", { name: "Delete group" }).click();

    const inUse = page.getByRole("dialog", { name: `Delete “${boardName}”?` });
    await expect(inUse.getByText(/1 risk owners/)).toBeVisible();
    // A Risk's owner is optional, so no replacement is required.
    await expect(inUse.getByText("Some of these fields are required, so a replacement is needed.")).toHaveCount(0);
    await inUse.getByRole("combobox", { name: "New owner" }).fill("E2E RiskGroups Admin");
    await inUse.getByRole("option", { name: /E2E RiskGroups Admin/ }).click();
    await inUse.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.getByText("Group deleted", { exact: true })).toBeVisible();

    // The Risk now names the admin; the project-group Risk is untouched.
    await page.goto(`/projects/${project.id}/modules/risk_management/risks`);
    await expect(page.locator("tr", { hasText: title }).getByText(/E2E RiskGroups Admin/)).toBeVisible();
    await expect(page.getByText(boardName)).toHaveCount(0);
    await expect(page.locator("tr", { hasText: squadRiskTitle }).getByText(squadName)).toBeVisible();
  });
});
