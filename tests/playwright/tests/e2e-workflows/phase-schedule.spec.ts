import { expect, test } from "@playwright/test";

import { apiHeaders, createDisposableProject, ensureExpanded, installCleanupHook, loginAs, PERSONAS } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a project manager gives the phases of a stage an expected range, sees the current phase marked
 * overdue once its end has passed, and the actual completion is recorded when the stage moves on.
 *
 * Uses a disposable project (archived by the cleanup hook), so nothing shared is changed.
 */
test.describe("phase schedule", () => {
  installCleanupHook();

  test("a manager schedules a phase and sees it overdue, then completed", async ({ page }) => {
    test.setTimeout(60_000);
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Phase Schedule");
    const headers = await apiHeaders(page.request, email);

    await test.step("the manager sets an expected range that has already ended on the current phase", async () => {
      await loginAs(page, email);
      await page.goto(`/projects/${project.projectId}/admin/stagesPhases`);
      await ensureExpanded(page, "Stage schedule");
      await page.getByRole("button", { name: "Schedule phase Scoping" }).first().click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Expected start").fill("2020-01-01");
      await dialog.getByLabel("Expected end").fill("2020-01-10");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Overdue", { exact: true })).toBeVisible();
    });

    await test.step("an end before the start is refused in the dialog", async () => {
      await page.getByRole("button", { name: "Schedule phase Review" }).first().click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Expected start").fill("2030-02-01");
      await dialog.getByLabel("Expected end").fill("2030-01-01");
      await expect(dialog.getByText("The expected end must not be before the expected start.")).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
      await page.keyboard.press("Escape");
    });

    await test.step("moving the stage on records the phase as completed", async () => {
      const stages = await (await page.request.get(`${API}/projects/${project.projectId}/stages`, { headers })).json();
      const stage = stages[0];
      const workflows = await (await page.request.get(`${API}/projects/${project.projectId}/stage-workflows`, { headers })).json();
      const workflow = workflows.find((w: { id: string }) => w.id === stage.workflow_id);
      const review = workflow.phases.find((p: { name: string }) => p.name === "Review");
      const moved = await page.request.post(`${API}/projects/${project.projectId}/stages/${stage.id}/transition`, {
        headers, data: { phase_id: review.id },
      });
      expect(moved.ok()).toBeTruthy();
      await page.reload();
      await ensureExpanded(page, "Stage schedule");
      await expect(page.getByText(/Completed .* late/)).toBeVisible();
    });
  });
});
