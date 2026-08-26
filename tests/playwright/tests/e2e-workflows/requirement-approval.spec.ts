import { expect, test } from "@playwright/test";

import { loginAs, logout, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Before this feature, a requirement only ever reached "approved" as a side
 * effect of a change request being approved — there was no standalone
 * approve action anywhere (2026-08 UX audit roadmap, "No requirement
 * approval action; change requests can target draft requirements"). This
 * proves the new direct path: a project manager sees and can use "Approve"
 * on a draft requirement; a stakeholder (who can otherwise edit the same
 * requirement directly) does not see it, matching C-U-03's clarification
 * that approval is a project-manager-specific privilege; and "Make change
 * request" only appears once the requirement is actually locked, since a
 * change request against a still-draft requirement is now rejected
 * server-side.
 *
 * Creates its own throwaway requirement rather than approving seeded data —
 * approving isn't reversible from the UI (no "unapprove" action exists,
 * unlike completion), so mutating a shared seeded requirement would corrupt
 * it for every other spec and for a repeat run of this one.
 */
test.describe("requirement approval", () => {
  test("a project manager approves a draft requirement directly; a stakeholder cannot", async ({ page }) => {
    const name = `E2E Approval ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await page.getByRole("link", { name: /Alpha-1/ }).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.getByText(name).click();

    await test.step("a stakeholder can edit the still-draft requirement but sees neither Approve nor Make change request", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(name).click();
      await expect(page.getByLabel("Name", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Make change request" })).toHaveCount(0);
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
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(name).click();
      await expect(page.getByRole("link", { name: "Make change request" })).toHaveCount(0);
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByText("Requirement approved")).toBeVisible();
      await expect(page.getByText("Locked (approved)")).toBeVisible();
      await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Make change request" })).toBeVisible();
    });
  });
});
