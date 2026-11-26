import { expect, test } from "@playwright/test";

import { apiHeaders, createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a project that turned the Review step off for its stages is not offered a Review phase on the Delivery
 * status page; the phase is shown unavailable with the reason in its label, the other phases stay choosable, and the
 * server refuses the move if it is attempted anyway.
 *
 * Uses a disposable project (archived by the cleanup hook); the lifecycle setting belongs to that project only.
 */
test.describe("allowed stage phases", () => {
  installCleanupHook();

  test("a turned-off Review phase is unavailable in the stage picker", async ({ page }) => {
    test.setTimeout(60_000);
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Allowed Phases");
    const headers = await apiHeaders(page.request, email);
    const off = await page.request.put(`${API}/projects/${project.projectId}/lifecycles/project_stage`, {
      headers, data: { disabled_states: ["review"] },
    });
    expect(off.ok()).toBeTruthy();
    const stages: { id: string; name: string }[] = await (await page.request.get(`${API}/projects/${project.projectId}/stages`, { headers })).json();

    await loginAs(page, email);
    await page.goto(`/projects/${project.projectId}/stage-phases`);
    await page.getByRole("button", { name: "Table view" }).click();

    await test.step("the Review phase is unavailable, with its reason, and the others are choosable", async () => {
      const picker = page.getByRole("combobox", { name: `Phase of ${stages[0].name}` });
      await expect(picker.getByRole("option", { name: "Review (turned off in this project)" })).toBeDisabled();
      await expect(picker.getByRole("option", { name: "Approved" })).toBeEnabled();
    });

    await test.step("the server refuses the move when it is attempted anyway", async () => {
      const workflows: { phases: { id: string; name: string }[] }[] = await (
        await page.request.get(`${API}/projects/${project.projectId}/stage-workflows`, { headers })
      ).json();
      const review = workflows[0].phases.find((p) => p.name === "Review");
      expect(review).toBeTruthy();
      const refused = await page.request.post(`${API}/projects/${project.projectId}/stages/${stages[0].id}/transition`, {
        headers, data: { phase_id: review!.id },
      });
      expect(refused.status()).toBe(409);
    });
  });
});
