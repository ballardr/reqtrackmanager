import { expect, test } from "@playwright/test";

import { loginAs, openProject, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Project Overview's "+ New Requirement" button deep-links to `/requirements?new=1` rather than opening a form
 * itself. The deep link opens the create form in the same `Modal` as the Requirements page's "+ New requirement"
 * split button (a plain click performs "Add one" with no menu; style guide "Pattern: split-button trigger"), so
 * this proves the deep-linked path matches the page's own.
 */
test.describe("Project Overview '+ New Requirement' opens the same create-form modal", () => {
  test("deep-linked create form is a layer, not a page reflow", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Overview", exact: true }).click();

    await page.getByRole("link", { name: "New requirement" }).click();
    // `?new=1` is consumed and stripped by RequirementsPage.tsx almost as soon as it lands, so waiting for that
    // intermediate URL can miss it; the settled final URL proves the deep link landed and was consumed.
    await page.waitForURL(/\/requirements$/);

    const dialog = page.getByRole("dialog", { name: "New requirement" });
    await expect(dialog).toBeVisible();
    // The list/search UI underneath stays visible and untouched while the
    // panel is open — the page didn't reflow to make room for the form.
    await expect(page.getByPlaceholder("Search by name or ID")).toBeVisible();

    const name = `E2E Overview Deep Link ${Date.now()}`;
    await dialog.getByPlaceholder("Name", { exact: true }).fill(name);
    await dialog.getByRole("button", { name: "Create", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    // Search rather than assume the new row is on the paginated list's
    // first page (shared Alpha-1 grows every run).
    await page.getByPlaceholder("Search by name or ID").fill(name);
    await expect(page.getByText(name)).toBeVisible();
  });
});
