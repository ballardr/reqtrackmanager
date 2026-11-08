import { expect, test } from "@playwright/test";

import { apiHeaders, createDisposableProject, installCleanupHook, loginAs, onCleanup, ORG_NAMES, PERSONAS } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: an organisation administrator keeps a project as a template, which stays out of the everyday
 * project list until asked for, and creates a new project from it that starts with the template's tag vocabulary
 * and components.
 *
 * Uses a disposable template project (archived by cleanup) and archives the project it creates.
 */
test.describe("template projects", () => {
  installCleanupHook();

  test("a template is hidden until shown, badged, and a project created from it receives its configuration", async ({ page }) => {
    test.setTimeout(90_000);
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const template = await createDisposableProject(page.request, email, "E2E Template Source", ORG_NAMES.alpha);
    const headers = await apiHeaders(page.request, email);
    const tagName = `starter-${Date.now()}`;
    expect((await page.request.patch(`${API}/projects/${template.projectId}`, { headers, data: { is_template: true } })).ok()).toBeTruthy();
    expect((await page.request.post(`${API}/projects/${template.projectId}/tags`, { headers, data: { name: tagName } })).ok()).toBeTruthy();
    const newName = `E2E From Template ${Date.now()}`;
    onCleanup(async (request) => {
      const cleanupHeaders = await apiHeaders(request, email);
      const projects: { id: string; name: string }[] = await (await request.get(`${API}/projects?archived=false`, { headers: cleanupHeaders })).json();
      for (const project of projects.filter((p) => p.name === newName)) {
        await request.post(`${API}/projects/${project.id}/archive`, { headers: cleanupHeaders });
      }
    });

    await test.step("the template is not in the project list until templates are shown, then it is badged", async () => {
      await loginAs(page, email);
      await page.goto(`/projects?q=${encodeURIComponent(template.projectName)}`);
      await expect(page.getByText("No projects to show.")).toBeVisible();
      await page.getByRole("checkbox", { name: "Show templates" }).check();
      const card = page.locator(".card", { hasText: template.projectName }).first();
      await expect(card).toBeVisible();
      await expect(card.getByText("Template", { exact: true })).toBeVisible();
    });

    await test.step("a new project created from the template receives its tags and components", async () => {
      await page.getByRole("checkbox", { name: "Show templates" }).uncheck();
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.getByLabel("Name", { exact: true }).fill(newName);
      await dialog.getByLabel("Create from template").selectOption({ label: template.projectName });
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: newName })).toBeVisible();

      const created: { id: string; name: string }[] = await (await page.request.get(`${API}/projects?archived=false`, { headers })).json();
      const project = created.find((p) => p.name === newName)!;
      const tags = await (await page.request.get(`${API}/projects/${project.id}/tags`, { headers })).json();
      expect(tags.tags.map((t: { name: string }) => t.name)).toContain(tagName);
      const components = await (await page.request.get(`${API}/projects/${project.id}/components`, { headers })).json();
      expect(components.length).toBe(template.components.length);
    });
  });
});
