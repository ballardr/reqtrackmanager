import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * Job to be done: `/orgs` (`OrgListPage.tsx`) uses the shared `DirectoryTable` + `FilterPanel` shell; the search
 * box narrows the table to matching organisation names.
 *
 * Persona: OrgAdminAlphaBeta (org admin of Alpha and Beta): `/orgs` renders the list only for a user in more than
 * one organisation; a single-organisation user is redirected past it.
 */
test.describe("/orgs directory search", () => {
  test("typing in the search box narrows the table to matching organisation names", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/orgs");

    await expect(page.getByRole("cell", { name: ORG_NAMES.alpha })).toBeVisible();
    await expect(page.getByRole("cell", { name: ORG_NAMES.beta })).toBeVisible();

    await page.getByPlaceholder(/Search /).fill("Alpha");
    await expect(page.getByRole("cell", { name: ORG_NAMES.alpha })).toBeVisible();
    await expect(page.getByRole("cell", { name: ORG_NAMES.beta })).toHaveCount(0);

    await page.getByPlaceholder(/Search /).fill("");
    await expect(page.getByRole("cell", { name: ORG_NAMES.alpha })).toBeVisible();
    await expect(page.getByRole("cell", { name: ORG_NAMES.beta })).toBeVisible();

    await page.getByPlaceholder(/Search /).fill("nonexistent org name");
    await expect(page.getByText(/match these filters/i)).toBeVisible();
  });

  test("a matching org name is still a real link into its own admin page", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/orgs");

    await page.getByPlaceholder(/Search /).fill("Beta");
    await page.getByRole("cell", { name: ORG_NAMES.beta }).getByRole("link").click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
  });
});
