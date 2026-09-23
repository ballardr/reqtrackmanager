import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * Job to be done: `/orgs` (`OrgListPage.tsx`) rebuilt onto the shared
 * `DirectoryTable` + `FilterPanel` shell — previously a bare `orgs.map`
 * list of links with no search. Covers the search box narrowing the table
 * to matching organisation names.
 *
 * Persona: OrgAdminAlphaBeta (org admin of exactly two organisations, Alpha
 * and Beta) — `/orgs` only renders the list at all for a user in more than
 * one org; a single-org user is auto-redirected straight past it.
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
