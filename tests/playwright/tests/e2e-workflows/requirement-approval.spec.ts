import { expect, test } from "@playwright/test";

import { approveRequirementFromDetail, recordActionNames, loginAs, logout, openProject, openRequirementByName, PERSONAS, PROJECT_NAMES, expectNoPromote, expectRecordLocked } from "./helpers";

/**
 * Proves the standalone approve action: a project manager sees and can use "Approve" on a draft requirement; a
 * stakeholder (who can otherwise edit the same requirement directly) does not see it, matching C-U-03's clarification
 * that approval is a project-manager-specific privilege; and "Make change request" appears only once the requirement
 * is locked, since a change request against a still-draft requirement is rejected server-side.
 *
 * Creates its own throwaway requirement rather than approving seeded data: approving is not reversible from the UI
 * (no "unapprove" action exists, unlike completion), so mutating a shared seeded requirement would corrupt it for
 * every other spec and for a repeat run of this one.
 */
test.describe("requirement approval", () => {
  test("a project manager approves a draft requirement directly; a stakeholder cannot", async ({ page }) => {
    const name = `E2E Approval ${Date.now()}`;
    const approvalComment = `Checked against the interface spec ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await openRequirementByName(page, name);

    await test.step("a stakeholder can edit the still-draft requirement but sees neither Approve nor Make change request", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await openProject(page, PROJECT_NAMES.alpha1);
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByName(page, name);
      await expect(page.getByLabel("Name", { exact: true })).toBeVisible();
      await expectNoPromote(page, "Approved");
      await expect(page.getByRole("button", { name: "Requirement actions" })).toBeVisible();
      expect(await recordActionNames(page, "Requirement")).not.toContain("Make change request");
    });

    await test.step("a direct API call to approve it as the stakeholder is rejected server-side", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const url = page.url();
      const projectMatch = url.match(/projects\/([0-9a-f-]+)/);
      const requirementMatch = url.match(/requirements\/([0-9a-f-]+)/);
      const resp = await page.request.post(
        `http://localhost:8000/api/v1/projects/${projectMatch?.[1]}/requirements/${requirementMatch?.[1]}/approve`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      expect(resp.status()).toBe(403);
    });

    await test.step("the project manager sees and uses Approve; the requirement locks", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await openProject(page, PROJECT_NAMES.alpha1);
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByName(page, name);
      await expect(page.getByRole("button", { name: "Requirement actions" })).toBeVisible();
      expect(await recordActionNames(page, "Requirement")).not.toContain("Make change request");
      await approveRequirementFromDetail(page, approvalComment);
      await expect(page.getByText("Requirement approved")).toBeVisible();
      await expectRecordLocked(page);
      await expectNoPromote(page, "Approved");
      expect(await recordActionNames(page, "Requirement")).toContain("Make change request");
    });

    await test.step("the approval comment is quoted under the approval in the Activity tab", async () => {
      await page.getByRole("tab", { name: "Activity" }).click();
      await expect(page.locator("blockquote.activity-note", { hasText: approvalComment })).toBeVisible();
      // The selected aside tab is a remembered per-user preference on this shared persona, so put
      // it back: later specs on this persona expect to find the Links panel without switching.
      await page.getByRole("tab", { name: "Links" }).click();
    });
  });
});
