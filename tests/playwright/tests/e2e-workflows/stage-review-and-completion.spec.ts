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
 *
 * Creates its own dynamically-named stage and two dynamically-named
 * requirements targeting it, rather than reusing Alpha-2's single seeded
 * stage/requirements — a stage transition is one-way (scoping -> review ->
 * approved -> completed is terminal, with no "reopen" endpoint), so a
 * fixed stage exhausted by one run of this test would leave every
 * subsequent run unable to find "Start review" at all. Per this repo's
 * idempotent-test convention (test independence, standalone/repeat-safe),
 * each run gets its own fresh stage to cycle through and its own fresh
 * requirements to lock/complete, rather than mutating shared seed state.
 */
test.describe("stage review deadlines and completion", () => {
  test("scoping -> review (with a deadline and a stakeholder response) -> approved -> completed, cascaded", async ({
    page,
  }) => {
    let projectId = "";
    let stageId = "";
    const stageName = `E2E Stage Cycle ${Date.now()}`;
    const reqNameA = `E2E Stage Cycle Req A ${Date.now()}`;
    const reqNameB = `E2E Stage Cycle Req B ${Date.now()}`;

    await test.step("PM creates a fresh stage for this run", async () => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.getByText(PROJECT_NAMES.alpha2).click();
      projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      // Project stages now lives inside the merged "Structure" tab
      // (2026-08 UX audit roadmap: Project Admin's 8 tabs -> 5).
      await selectProjectAdminGroup(page, "Structure");
      // Scoped to the "Project stages" card: its own "Name" placeholder
      // would otherwise collide with the identically-labelled "new
      // component"/"new category" inputs elsewhere on the same Structure
      // tab (`ProjectAdminPage.tsx` reuses `strings.admin.name` for all
      // three "add a new X" forms).
      const stagesSection = page.locator("div.card.stack", {
        has: page.getByRole("heading", { name: "Project stages" }),
      });
      await stagesSection.getByPlaceholder("Name", { exact: true }).fill(stageName);
      await stagesSection.getByRole("button", { name: "New stage" }).click();
      await expect(page.locator(`input[value="${stageName}"]`)).toBeVisible();
    });

    await test.step("PM creates two requirements explicitly targeting the new stage", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      for (const name of [reqNameA, reqNameB]) {
        await page.getByRole("button", { name: "New requirement" }).click();
        const dialog = page.getByRole("dialog", { name: "New requirement" });
        await dialog.getByPlaceholder("Name", { exact: true }).fill(name);
        await dialog.getByLabel("Target version").selectOption({ label: stageName });
        await dialog.getByRole("button", { name: "Create", exact: true }).click();
        await expect(page.getByText(name)).toBeVisible();
      }
    });

    // Every subsequent step scopes to this stage's own row (found by its
    // current display value in the rename `<input>`) rather than assuming
    // it's the project's only stage, since Alpha-2 already has the
    // original seeded stage (and, after a repeat run of this spec, any
    // number of previous runs' now-`completed` stages) coexisting with it.
    function stageContainer() {
      return page.locator(`input[value="${stageName}"]`).locator("xpath=../../..");
    }

    await test.step("PM starts the stage's review and sets a deadline", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Structure");
      await stageContainer().getByRole("button", { name: "Start review" }).click();
      await expect(stageContainer().getByText("In review", { exact: true })).toBeVisible();

      const future = new Date(Date.now() + 24 * 60 * 60 * 1000);
      await stageContainer().locator('input[type="datetime-local"]').fill(future.toISOString().slice(0, 16));
      await stageContainer().getByRole("button", { name: "Set review deadline" }).click();
      await expect(stageContainer().getByText("Review deadline:")).toBeVisible();
    });

    await test.step("a plain member cannot approve the stage via a direct API call, even while it's in review", async () => {
      const pmToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const stagesResp = await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/stages`, {
        headers: { Authorization: `Bearer ${pmToken}` },
      });
      const allStages: { id: string; name: string }[] = await stagesResp.json();
      stageId = allStages.find((s) => s.name === stageName)!.id;

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
      // Idempotent regardless of whether a previous run already granted
      // this role — POST /roles is a plain grant, tolerant of re-granting
      // an already-held role.
      await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/roles`, {
        headers: { Authorization: `Bearer ${pmToken}` },
        data: { user_id: stakeholderId, role: "stakeholder" },
      });

      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.goto(`/projects/${projectId}/admin`);
      await selectProjectAdminGroup(page, "Structure");
      await stageContainer().getByRole("button", { name: "Approve", exact: true }).click();
      await expect(stageContainer().getByText("In review", { exact: true })).toBeVisible();
    });

    await test.step("PM approves the stage, which locks its requirements and writes a baseline", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.goto(`/projects/${projectId}/admin`);
      await selectProjectAdminGroup(page, "Structure");
      await stageContainer().getByRole("button", { name: "Approve stage" }).click();
      await expect(stageContainer().getByRole("button", { name: "Approve stage" })).toHaveCount(0);

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await expect(page.getByText("Locked (approved)").first()).toBeVisible();
    });

    await test.step("a locked requirement can be marked completed directly by the PM (no change request needed)", async () => {
      // C-G-11: completion is an overlay marker independent of lifecycle
      // status (`Requirement.is_completed`), not its own status value — the
      // status badge stays "Approved" throughout; a separate "Completed"
      // badge appears/disappears alongside it instead.
      await page.getByText(reqNameA).click();
      await page.getByRole("button", { name: "Mark completed" }).click();
      await expect(page.getByText("Status: Approved")).toBeVisible();
      await expect(page.getByText("Completed", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Revert completion" }).click();
      await expect(page.getByText("Status: Approved")).toBeVisible();
      await expect(page.getByText("Completed", { exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "Mark completed" }).click();
      await expect(page.getByText("Completed", { exact: true })).toBeVisible();
    });

    await test.step("PM completes the stage with cascade, which also completes its still-approved requirements", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Structure");
      await stageContainer()
        .getByLabel("Also mark this stage's approved requirements as completed")
        .check();
      await stageContainer().getByRole("button", { name: "Mark stage completed" }).click();
      await expect(stageContainer().getByText("Implemented", { exact: true })).toBeVisible();

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      // reqNameB was never manually completed — only the cascade above
      // should have marked it, proving the cascade (not the earlier manual
      // step) is what completed it.
      await page.getByText(reqNameB).click();
      await expect(page.getByText("Status: Approved")).toBeVisible();
      await expect(page.getByText("Completed", { exact: true })).toBeVisible();
    });
  });
});
