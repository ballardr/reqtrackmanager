import { expect, test } from "@playwright/test";

import { loginAs, logout, PERSONAS, PROJECT_NAMES, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: a project stage's full lifecycle — scoping, a review
 * period stakeholders can explicitly approve or reject (C-R-05), PM
 * approval (which locks requirements and writes a baseline, C-G-10/C-G-12),
 * and completion, optionally cascaded to the stage's requirements (C-P-02,
 * C-P-03).
 *
 * Uses Alpha-2 (untouched by other specs in this suite) so its stage's
 * lifecycle state doesn't collide with Alpha-1's, which other specs lock
 * via their own "Approve stage" flow. Alpha-2 has no stakeholder seeded, so
 * this test grants one via a direct API call (this codebase's own
 * established pattern for setup steps the seed script doesn't cover)
 * purely to exercise the review-response UI as a real stakeholder.
 */
test.describe("stage review deadlines and completion", () => {
  test("scoping -> review (with a deadline and a stakeholder response) -> approved -> completed, cascaded", async ({
    page,
  }) => {
    let projectId = "";
    let stageId = "";

    await test.step("PM starts the stage's review and sets a deadline", async () => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.getByText(PROJECT_NAMES.alpha2).click();
      projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      // Project stages now lives inside the merged "Structure" tab
      // (2026-08 UX audit roadmap: Project Admin's 8 tabs -> 5).
      await selectProjectAdminGroup(page, "Structure");
      await page.getByRole("button", { name: "Start review" }).click();
      await expect(page.getByText("In review", { exact: true })).toBeVisible();

      const future = new Date(Date.now() + 24 * 60 * 60 * 1000);
      await page.locator('input[type="datetime-local"]').fill(future.toISOString().slice(0, 16));
      await page.getByRole("button", { name: "Set review deadline" }).click();
      await expect(page.getByText("Review deadline:")).toBeVisible();
    });

    await test.step("a plain member cannot approve the stage via a direct API call, even while it's in review", async () => {
      const pmToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const stagesResp = await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/stages`, {
        headers: { Authorization: `Bearer ${pmToken}` },
      });
      stageId = (await stagesResp.json())[0].id;

      await logout(page);
      await loginAs(page, PERSONAS.memberAlphaBeta.email);
      // memberAlphaBeta has no role at all on Alpha-2 — proves the check is
      // a real project-manager gate, not merely UI absence.
      const memberToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const resp = await page.request.post(
        `http://localhost:8000/api/v1/projects/${projectId}/stages/${stageId}/transition?new_status=approved`,
        { headers: { Authorization: `Bearer ${memberToken}` } }
      );
      expect(resp.status()).toBe(403);
    });

    await test.step("a stakeholder responds to the review through the real UI", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      const pmToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const projectResp = await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}`, {
        headers: { Authorization: `Bearer ${pmToken}` },
      });
      const { organization_id: orgId } = await projectResp.json();
      const usersResp = await page.request.get(`http://localhost:8000/api/v1/orgs/${orgId}/users`, {
        headers: { Authorization: `Bearer ${pmToken}` },
      });
      const users: { user_id: string; email: string }[] = await usersResp.json();
      const stakeholderId = users.find((u) => u.email === PERSONAS.stakeholderAlpha.email)!.user_id;
      await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/roles`, {
        headers: { Authorization: `Bearer ${pmToken}` },
        data: { user_id: stakeholderId, role: "stakeholder" },
      });

      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.goto(`/projects/${projectId}/admin`);
      await selectProjectAdminGroup(page, "Structure");
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByText("In review", { exact: true })).toBeVisible();
    });

    await test.step("PM approves the stage, which locks its requirements and writes a baseline", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.goto(`/projects/${projectId}/admin`);
      await selectProjectAdminGroup(page, "Structure");
      await page.getByRole("button", { name: "Approve stage" }).click();
      await expect(page.getByRole("button", { name: "Approve stage" })).toHaveCount(0);

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await expect(page.getByText("Locked (approved)").first()).toBeVisible();
    });

    await test.step("a locked requirement can be marked completed directly by the PM (no change request needed)", async () => {
      await page.getByRole("link", { name: "Must respond to input within 50ms", exact: true }).click();
      await page.getByRole("button", { name: "Mark completed" }).click();
      await expect(page.getByText("Status: Completed")).toBeVisible();
      await page.getByRole("button", { name: "Revert completion" }).click();
      await expect(page.getByText("Status: Approved")).toBeVisible();
      await page.getByRole("button", { name: "Mark completed" }).click();
      await expect(page.getByText("Status: Completed")).toBeVisible();
    });

    await test.step("PM completes the stage with cascade, which also completes its still-approved requirements", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Structure");
      await page.getByLabel("Also mark this stage's approved requirements as completed").check();
      await page.getByRole("button", { name: "Mark stage completed" }).click();
      await expect(page.getByText("Implemented", { exact: true })).toBeVisible();

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("link", { name: "Must support configuration via file", exact: true }).click();
      await expect(page.getByText("Status: Completed")).toBeVisible();
    });
  });
});
