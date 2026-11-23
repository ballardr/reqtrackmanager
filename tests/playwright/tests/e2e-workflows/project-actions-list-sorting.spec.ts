import { expect, test } from "@playwright/test";

import { loginAs, openProject, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: ProjectActionsPage's table headers cycle unsorted, ascending, descending, unsorted on click.
 * Unlike RequirementsPage/ChangeRequestsPage, this list has no backend pagination (`routers/actions.py::list_actions`
 * returns every match), so sorting reorders the loaded rows client-side and a header click makes no network request.
 *
 * Two actions are created with timestamped, bounding titles ("AAA"/"ZZZ" prefixes) rather than relying on the shared
 * project's existing actions, so the ordering assertion does not depend on how many other actions the project has.
 */
test.describe("project actions list sorting", () => {
  test("sort by title ascending and descending via the column header", async ({ page }) => {
    const suffix = Date.now();
    const firstTitle = `AAA Sort Test Action ${suffix}`;
    const secondTitle = `ZZZ Sort Test Action ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Actions", exact: true }).click();

    async function createAction(title: string) {
      await page.getByRole("button", { name: "New action" }).click();
      await page.getByLabel("Title").fill(title);
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
