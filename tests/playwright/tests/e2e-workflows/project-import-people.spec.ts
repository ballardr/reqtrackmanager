import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { loginAs, openProject, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: importing a project bundle into an organisation where some of the people it names are not
 * members. The import dialog's People step shows each person and how they will be recorded, lets the importer
 * change that, and the organisation administrator sees the imported people on the Users page.
 */
test.describe("project import: people in the bundle", () => {
  test("the People step lists the bundle's people, accepts a choice and the import completes", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.beta1);
    await page.getByRole("link", { name: "Project admin" }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export project bundle" }).click();
    const exportedPath = (await (await downloadPromise).path())!;

    await page.goto("/projects");
    await page.getByRole("button", { name: "More options" }).click();
    await page.getByRole("button", { name: "Import project" }).click();
    const dialog = page.getByRole("dialog", { name: "Import project" });
    await dialog.getByLabel("Name", { exact: true }).fill(`E2E People Import (${Date.now()})`);
    const orgSelect = dialog.locator("select").first();
    await expect(orgSelect).toContainText(ORG_NAMES.alpha);
    await orgSelect.selectOption({ label: ORG_NAMES.alpha });
    await dialog.locator('input[type="file"][accept*="zip"]').setInputFiles(exportedPath);

    const people = dialog.getByRole("table", { name: "People in the bundle" });
    await expect(people).toBeVisible();
    // Every person can be sent to "Me"; the keep-email switch is off by default.
    const first = people.getByRole("combobox").first();
    await first.selectOption({ label: "Me" });
    await expect(people.getByText("Me", { exact: true }).first()).toBeVisible();
    await expect(dialog.getByRole("checkbox", { name: "Keep original email addresses in the history" })).not.toBeChecked();

    await dialog.getByRole("button", { name: "Import", exact: true }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/, { timeout: 15000 });
    fs.rmSync(exportedPath, { force: true });
  });

  test("the organisation Users page lists imported people", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const orgs: { id: string; name: string }[] = await (
      await page.request.get("http://localhost:8000/api/v1/orgs", { headers: { Authorization: `Bearer ${token}` } })
    ).json();
    const alpha = orgs.find((o) => o.name === ORG_NAMES.alpha)!;
    await page.goto(`/orgs/${alpha.id}/admin/users`);
    await expect(page.getByRole("heading", { name: "Imported people" })).toBeVisible();
    await expect(page.getByLabel("Offer unused imported people for removal after (days)")).toBeVisible();
  });
});
