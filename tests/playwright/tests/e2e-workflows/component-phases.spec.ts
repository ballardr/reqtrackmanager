import { expect, test } from "@playwright/test";

import { apiHeaders, createDisposableProject, ensureExpanded, installCleanupHook, loginAs, PERSONAS } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a project manager turns on component phases so each component follows its own workflow per
 * stage — moving one component into a locked phase approves only that component's requirements for the stage,
 * and the other component stays editable; a component can be marked not applicable to a stage.
 *
 * Uses a disposable project (archived by the cleanup hook), so nothing shared is changed.
 */
test.describe("component phases", () => {
  installCleanupHook();

  test("a component's locked phase approves only its own requirements", async ({ page }) => {
    test.setTimeout(60_000);
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Component Phases");
    const headers = await apiHeaders(page.request, email);
    const [hardware, software] = project.components;
    const [hardwareCategory, softwareCategory] = [project.categories[0], project.categories[1]];
    const stamp = Date.now();

    const create = async (name: string, componentId: string, categoryId: string) =>
      (await (await page.request.post(`${API}/projects/${project.projectId}/requirements`, {
        headers, data: { name, component_id: componentId, category_id: categoryId },
      })).json()).id as string;
    const hardwareRequirement = await create(`E2E Hardware ${stamp}`, hardware.id, hardwareCategory.id);
    const softwareRequirement = await create(`E2E Software ${stamp}`, software.id, softwareCategory.id);
    const status = async (id: string) =>
      (await (await page.request.get(`${API}/projects/${project.projectId}/requirements/${id}`, { headers })).json()).status as string;

    await test.step("the manager turns component phases on in Project Admin", async () => {
      await loginAs(page, email);
      await page.goto(`/projects/${project.projectId}/admin/structure`);
      await ensureExpanded(page, "Component phases");
      await page.getByRole("combobox", { name: /Component phases/ }).selectOption({ label: "On" });
      await expect(page.getByRole("combobox", { name: new RegExp(`Phase of ${software.name} in`) })).toBeVisible();
    });

    await test.step("moving Software into its locked phase approves only Software", async () => {
      const phase = page.getByRole("combobox", { name: new RegExp(`Phase of ${software.name} in`) });
      await phase.selectOption({ label: "Approved" });
      await expect(phase.locator("option:checked")).toHaveText("Approved");
      await expect.poll(() => status(softwareRequirement)).toBe("approved");
      expect(await status(hardwareRequirement)).toBe("draft");
    });

    await test.step("a component can be marked not applicable to a stage", async () => {
      await page.getByRole("button", { name: new RegExp(`Edit ${hardware.name} in`) }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("switch", { name: /Not applicable/ }).click();
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Not applicable", { exact: true })).toBeVisible();
    });
  });
});
