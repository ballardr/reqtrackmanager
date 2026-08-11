import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: exporting a project as a self-contained bundle (structure,
 * full requirement/change-request history, attachments) and re-importing it
 * to stand up a brand-new project — the actual UI path for project backup/
 * migration (`services.project_export`), not just the underlying API.
 */
test.describe("project bundle export/import", () => {
  test("export a project from its admin page, then import it as a new project", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.beta1).click();
    await page.getByRole("link", { name: "Project admin" }).click();
    await expect(page).toHaveURL(/\/admin$/);

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const projectId = page.url().match(/projects\/([0-9a-f-]+)\/admin/)![1];
    const sourceRequirements: { name: string }[] = await (
      await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/requirements`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json();
    expect(sourceRequirements.length).toBeGreaterThan(0);
    const knownRequirementName = sourceRequirements[0].name;

    let exportedPath: string;
    await test.step("export the project bundle from the admin page", async () => {
      const downloadPromise = page.waitForEvent("download");
      await page.getByRole("button", { name: "Export project bundle" }).click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toMatch(/-export\.zip$/);
      exportedPath = (await download.path())!;
    });

    await test.step("import the bundle as a new project", async () => {
      const newName = `E2E Imported Bundle (${Date.now()})`;
      await page.goto("/projects");
      await page.getByRole("button", { name: "New project" }).click();
      // Scoped to the "New project" form card specifically, not just "the
      // first <select> on the page" — the org filter and role filter rows
      // below the form have their own <select>s, and while the org select
      // is loading (orgs.length > 1 not yet true), an unscoped `.first()`
      // can latch onto one of those instead and then wait forever for an
      // option that will never appear in it.
      const form = page.locator(".card").filter({ has: page.getByPlaceholder("Name", { exact: true }) });
      await form.getByPlaceholder("Name", { exact: true }).fill(newName);
      const orgSelect = form.locator("select").first();
      if (await orgSelect.isVisible()) await orgSelect.selectOption({ label: ORG_NAMES.beta });
      const fileInput = form.locator('input[type="file"][accept*="zip"]');
      await fileInput.setInputFiles(exportedPath);
      await page.getByRole("button", { name: "Create" }).click();

      await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/, { timeout: 15000 });
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await expect(page.getByRole("link", { name: knownRequirementName, exact: true })).toBeVisible();
    });

    fs.rmSync(exportedPath!, { force: true });
  });
});
