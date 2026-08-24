import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: ProjectActionsPage's table headers (2026-08 UX audit
 * roadmap, "Column-header sorting on data tables") are clickable and cycle
 * unsorted → ascending → descending → unsorted. Unlike RequirementsPage/
 * ChangeRequestsPage, this list has no backend pagination at all
 * (`routers/actions.py::list_actions` always returns every match), so
 * sorting is a purely client-side reorder of the already-loaded rows —
 * no network request is expected on a header click.
 *
 * Two actions are created here with timestamped, bounding titles ("AAA"/
 * "ZZZ" prefixes) rather than relying on the shared project's existing
 * actions, so the ordering assertion doesn't depend on how many other
 * actions this project happens to have when the suite runs (per this
 * repo's own test-independence rule — a spec must pass standalone or
 * repeated back-to-back against the same database).
 */
test.describe("project actions list sorting", () => {
  test("sort by title ascending and descending via the column header", async ({ page }) => {
    const suffix = Date.now();
    const firstTitle = `AAA Sort Test Action ${suffix}`;
    const secondTitle = `ZZZ Sort Test Action ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Actions", exact: true }).click();

    async function createAction(title: string) {
      await page.getByRole("button", { name: "New action" }).click();
      await page.getByPlaceholder("Title").fill(title);
      await page.getByRole("button", { name: "Create" }).click();
      await expect(page.getByRole("link", { name: title })).toBeVisible();
    }

    await createAction(firstTitle);
    await createAction(secondTitle);

    const titleHeader = page.getByRole("button", { name: "Title" });
    const titleHeaderCell = page.locator("th", { has: titleHeader });

    async function rowIndexOf(needle: string): Promise<number> {
      return page.locator("table tbody tr").evaluateAll(
        (rows, text) => rows.findIndex((row) => row.textContent?.includes(text)),
        needle
      );
    }

    await titleHeader.click();
    await expect(titleHeaderCell).toHaveAttribute("aria-sort", "ascending");
    expect(await rowIndexOf(firstTitle)).toBeLessThan(await rowIndexOf(secondTitle));

    await titleHeader.click();
    await expect(titleHeaderCell).toHaveAttribute("aria-sort", "descending");
    expect(await rowIndexOf(secondTitle)).toBeLessThan(await rowIndexOf(firstTitle));

    await titleHeader.click();
    await expect(titleHeaderCell).toHaveAttribute("aria-sort", "none");
  });
});
