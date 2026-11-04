import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: choose and download a report from the project (or organisation) overview, in one dialog, and have
 * the organisation's one report look applied by the server (a download names no branding).
 *
 * Each test works in its own disposable project.
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

  test("the requirement report names no branding: the organisation's report look is applied by the server", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Report Look");
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}?reports=choose`);

    await test.step("the requirement report offers no template choice and no requirement filters", async () => {
      const dialog = page.getByRole("dialog", { name: "Reports" });
      await expect(dialog.getByRole("button", { name: "Generate PDF" })).toBeVisible();
      await expect(dialog.getByLabel("Report template")).toHaveCount(0);
      await expect(dialog.getByLabel("Branding template")).toHaveCount(0);
      await expect(dialog.getByText("Filters", { exact: true })).toHaveCount(0);
    });

    await test.step("a download names no template", async () => {
      const request = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith(`/projects/${project.projectId}/reports`));
      await page.getByRole("dialog", { name: "Reports" }).getByRole("button", { name: "Generate PDF" }).click();
      expect((await request).postDataJSON()).not.toHaveProperty("report_template_id");
    });

    await test.step("report templates no longer exist", async () => {
      const gone = await page.request.get(`${API}/orgs/${project.organizationId}/report-templates`, { headers: project.headers });
      expect(gone.status()).toBe(404);
    });
  });
});
