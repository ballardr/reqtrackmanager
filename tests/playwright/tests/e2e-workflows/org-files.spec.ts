import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: finding a document without knowing which project holds it. The organisation Files page lists the
 * files of every project the person can open, each with its project, and narrows by project. See
 * backend/scripts/seed_e2e_dataset.py's "Files on Alpha-1" step, which seeds the three origins on Alpha-1.
 */
async function openOrganisationFiles(page: import("@playwright/test").Page, orgName: string) {
  await page.goto("/org-overview");
  await page.getByRole("link", { name: orgName }).click();
  await expect(page.getByRole("heading", { name: orgName })).toBeVisible();
  await page.getByRole("link", { name: "Organisation files" }).click();
  await expect(page).toHaveURL(/\/orgs\/[^/]+\/files/);
}

test.describe("organisation files", () => {
  test("an organisation member opens the page from the overview and sees files with their project", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openOrganisationFiles(page, ORG_NAMES.alpha);

    await test.step("a file is listed with the project that holds it and its origin", async () => {
      await expect(page.getByRole("heading", { level: 1, name: "Organisation files" })).toBeVisible();
      const row = page.locator("tr", { has: page.getByText("e2e-direct-attachment.txt") });
      await expect(row.getByRole("link", { name: PROJECT_NAMES.alpha1 })).toBeVisible();
      await expect(row.getByRole("link", { name: /Must expose a health-check endpoint/ })).toBeVisible();
    });

    await test.step("the project filter narrows the list and lives in the URL", async () => {
      await page.getByRole("combobox", { name: "Project" }).selectOption({ label: PROJECT_NAMES.alpha2 });
      await expect(page).toHaveURL(/project=/);
      await expect(page.getByText("e2e-direct-attachment.txt")).toBeHidden();
    });
  });

  test("a plain member reaches the page and it lists only what their projects hold", async ({ page }) => {
    await loginAs(page, PERSONAS.memberAlphaBeta.email);
    await openOrganisationFiles(page, ORG_NAMES.alpha);

    await expect(page.getByRole("heading", { level: 1, name: "Organisation files" })).toBeVisible();
    const projects = page.getByRole("combobox", { name: "Project" });
    await expect(projects).toBeVisible();
    // Every project offered is one the member can open: choosing each never shows a row from another project.
    for (const label of await projects.locator("option:not([value=''])").allTextContents()) {
      await projects.selectOption({ label });
      for (const link of await page.locator("tbody tr td:nth-child(2) a").allTextContents()) expect(link).toBe(label);
    }
  });
});
