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
      // "New project" opens a Modal (style guide "Pattern: modal dialog for
      // entity create/rename") — scoped to it rather than "the first
      // <select> on the page", since the org/role filter rows in the main
      // page (still visible behind the modal's backdrop) have their own
      // <select>s too. orgAdminAlphaBeta always belongs to 2 orgs, so the
      // org picker is always rendered here — but it (and the Visibility
      // select next to it) both mount asynchronously with orgs.length, so a
      // one-shot `isVisible()` check can latch onto whichever select
      // happens to already be in the DOM at that instant rather than
      // waiting for the org picker specifically. Waiting for its actual
      // option content (a retrying assertion, unlike an action's one-shot
      // actionability wait) is robust to that race.
      const form = page.getByRole("dialog", { name: "New project" });
      await form.getByLabel("Name", { exact: true }).fill(newName);
      const orgSelect = form.locator("select").first();
      await expect(orgSelect).toContainText(ORG_NAMES.beta);
      await orgSelect.selectOption({ label: ORG_NAMES.beta });
      const fileInput = form.locator('input[type="file"][accept*="zip"]');
      await fileInput.setInputFiles(exportedPath);
      await form.getByRole("button", { name: "Create" }).click();

      await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/, { timeout: 15000 });
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await expect(page.getByRole("link", { name: knownRequirementName, exact: true })).toBeVisible();
    });

    fs.rmSync(exportedPath!, { force: true });
  });
});
