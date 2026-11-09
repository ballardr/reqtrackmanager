import { expect, test } from "@playwright/test";

import {
  apiHeaders, createDisposableProject, ensureExpanded, ensureRowExpanded, installCleanupHook, loginAs, moveStageToPhase, onCleanup, ORG_NAMES,
  PERSONAS, selectOrgAdminGroup,
} from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: an organisation defines its own stage workflow (phases with kinds), and a project's stage
 * follows it — a locked phase writes the baseline whatever it is called, phases can be visited in any order,
 * and a project can hide an organisation workflow and restore it.
 *
 * Creates a uniquely named organisation workflow and a disposable project. The project is archived by
 * `onCleanup`; the workflow is deleted there too unless the project's stage still follows it (a workflow in use
 * cannot be deleted, by design), in which case the unique name keeps later runs apart.
 */
test.describe("stage workflows", () => {
  installCleanupHook();

  test("an organisation workflow with a custom locked phase drives a project's stage", async ({ page }) => {
    test.setTimeout(60_000);
    const stamp = Date.now();
    const workflowName = `E2E Tender ${stamp}`;
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Workflow Project", ORG_NAMES.alpha);
    const headers = await apiHeaders(page.request, email);

    onCleanup(async (request) => {
      const cleanupHeaders = await apiHeaders(request, email);
      const workflows: { id: string; name: string; in_use: boolean }[] = await (
        await request.get(`${API}/orgs/${project.organizationId}/stage-workflows`, { headers: cleanupHeaders })
      ).json();
      for (const workflow of workflows.filter((w) => w.name === workflowName)) {
        // Still followed by the disposable project's stage, so only an unused one can go; the rest is harmless.
        if (!workflow.in_use) await request.delete(`${API}/orgs/${project.organizationId}/stage-workflows/${workflow.id}`, { headers: cleanupHeaders });
      }
    });

    await test.step("the organisation administrator builds the workflow in Organisation Admin", async () => {
      await loginAs(page, email);
      await page.goto(`/orgs/${project.organizationId}/admin`);
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Stage workflows");
      await page.getByRole("button", { name: "New workflow" }).click();
      const dialog = page.getByRole("dialog", { name: "New workflow" });
      await dialog.getByRole("textbox", { name: /Workflow name/ }).fill(workflowName);
      await dialog.getByRole("textbox", { name: "Phase name 1" }).fill("Scoping");
      await dialog.getByRole("button", { name: "Add phase" }).click();
      await dialog.getByRole("textbox", { name: "Phase name 2" }).fill("Tendering");
      await dialog.getByRole("combobox", { name: "Kind 2" }).selectOption({ label: "On hold" });
      await dialog.getByRole("button", { name: "Add phase" }).click();
      await dialog.getByRole("textbox", { name: "Phase name 3" }).fill("Contract awarded");
      await dialog.getByRole("combobox", { name: "Kind 3" }).selectOption({ label: "Locked" });
      await dialog.getByRole("button", { name: "Save" }).click();
      // With more than one workflow, each is a closed row: named, with its step count, phases hidden until opened.
      const toggle = page.getByRole("button", { name: new RegExp(`^${workflowName}`) }).and(page.locator("[aria-expanded]"));
      await expect(toggle).toContainText("3 steps");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(page.getByRole("list", { name: `Phases of ${workflowName}` })).toHaveCount(0);
      const saved = page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH");
      await ensureRowExpanded(page, workflowName);
      await saved;
      // The choice is kept for this person across a reload.
      await page.reload();
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Stage workflows");
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      // The phases read as an ordered list of steps: names in order, the kind beside each, the first marked as the start.
      const steps = page.getByRole("list", { name: `Phases of ${workflowName}` }).getByRole("listitem");
      await expect(steps).toHaveCount(3);
      await expect(steps.nth(0)).toContainText("Scoping");
      await expect(steps.nth(0)).toContainText("Starting phase");
      await expect(steps.nth(2)).toContainText("Contract awarded");
      await expect(steps.nth(2)).toContainText("Locked");
      await expect(page.getByText("In use", { exact: true })).toHaveCount(0);
    });

    await test.step("a stage follows it, and a phase of kind locked baselines the requirements", async () => {
      const component = project.components[0];
      const category = project.categories[0];
      const requirement = await (await page.request.post(`${API}/projects/${project.projectId}/requirements`, {
        headers, data: { name: `E2E Workflow Req ${stamp}`, component_id: component.id, category_id: category.id },
      })).json();
      const workflows: { id: string; name: string }[] = await (
        await page.request.get(`${API}/projects/${project.projectId}/stage-workflows`, { headers })
      ).json();
      const workflowId = workflows.find((w) => w.name === workflowName)!.id;
      const stage = await (await page.request.post(`${API}/projects/${project.projectId}/stages`, {
        headers, data: { name: `Build ${stamp}`, workflow_id: workflowId },
      })).json();

      await page.goto(`/projects/${project.projectId}/admin/stagesPhases`);
      const phase = page.getByRole("combobox", { name: `Phase of Build ${stamp}` });
      await phase.selectOption({ label: "Tendering" });
      await expect(phase.locator("option:checked")).toHaveText("Tendering");
      await phase.selectOption({ label: "Contract awarded" });
      await expect(phase.locator("option:checked")).toHaveText("Contract awarded");

      const locked = await (await page.request.get(`${API}/projects/${project.projectId}/requirements/${requirement.id}`, { headers })).json();
      expect(locked.status).toBe("approved");

      // Phases can be visited in either direction; leaving the locked phase is allowed for the project manager.
      const back = await moveStageToPhase(page.request, headers, project.projectId, stage.id, "Scoping");
      expect(back.ok()).toBeTruthy();
    });

    await test.step("a project hides an organisation workflow and restores it", async () => {
      await page.goto(`/projects/${project.projectId}/admin/stagesPhases`);
      await ensureExpanded(page, "Stage workflows");
      await page.getByRole("button", { name: `Hide workflow ${workflowName}` }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Hide" }).click();
      await expect(page.getByRole("button", { name: `Hide workflow ${workflowName}` })).toHaveCount(0);
      await page.getByRole("button", { name: /Add organisation defaults/ }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Add 1 default" }).click();
      await expect(page.getByRole("button", { name: `Hide workflow ${workflowName}` })).toBeVisible();
    });
  });
});
