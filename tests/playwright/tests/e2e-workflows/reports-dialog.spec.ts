import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, onCleanup, PERSONAS } from "./helpers";

/**
 * Job to be done: choose and download a report from the project (or organisation) overview, in one dialog, and have
 * the organisation's default branding template used unless a report names another.
 *
 * Each test works in its own disposable project and removes the templates it makes, since a default template
 * would otherwise brand every later export in the shared organisation.
 */
test.describe("Reports dialog", () => {
  installCleanupHook();
  const API = "http://localhost:8000/api/v1";

  test("the overview's Reports button opens the report chooser in one click", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Reports Dialog");
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}`);

    await test.step("the project has no Reports page or navigation entry", async () => {
      await expect(page.getByRole("navigation").getByRole("link", { name: "Reports", exact: true })).toHaveCount(0);
    });

    await test.step("Choose a report opens the dialog on the first report", async () => {
      await page.getByRole("button", { name: "Reports", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Reports" });
      await expect(dialog.getByRole("button", { name: /^Report:/ })).toBeVisible();
      await expect(page).toHaveURL(/reports=choose/);
    });

    await test.step("closing it removes the dialog and its address parameter", async () => {
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect(page).not.toHaveURL(/reports=/);
    });
  });

  test("a link with the reports parameter opens the dialog on that report", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Reports Link");
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}?reports=choose&report=record-list`);
    await expect(page.getByRole("dialog", { name: "Reports" }).getByLabel("Record type")).toBeVisible();
  });

  test("the organisation's default template is offered by name and a layout can choose its own", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Default Template");
    const name = `E2E Default ${Date.now()}`;
    const created = await page.request.post(`${API}/orgs/${project.organizationId}/report-templates`, {
      headers: project.headers, data: { name, is_default: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const templateId: string = (await created.json()).id;
    onCleanup(async (cleanupRequest) => {
      await cleanupRequest.delete(`${API}/orgs/${project.organizationId}/report-templates/${templateId}`, { headers: project.headers });
    });

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}?reports=choose`);

    await test.step("the requirement report names the default instead of 'none'", async () => {
      const dialog = page.getByRole("dialog", { name: "Reports" });
      await expect(dialog.getByLabel("Report template")).toHaveValue("");
      await expect(dialog.getByLabel("Report template").locator("option", { hasText: `Default (${name})` })).toHaveCount(1);
    });

    await test.step("only one template is the default", async () => {
      const second = await page.request.post(`${API}/orgs/${project.organizationId}/report-templates`, {
        headers: project.headers, data: { name: `${name} second`, is_default: true },
      });
      expect(second.ok()).toBeTruthy();
      const secondId: string = (await second.json()).id;
      onCleanup(async (cleanupRequest) => {
        await cleanupRequest.delete(`${API}/orgs/${project.organizationId}/report-templates/${secondId}`, { headers: project.headers });
      });
      const listed: { id: string; is_default: boolean }[] = await (
        await page.request.get(`${API}/orgs/${project.organizationId}/report-templates`, { headers: project.headers })
      ).json();
      expect(listed.filter((t) => t.is_default).map((t) => t.id)).toEqual([secondId]);
    });
  });
});
