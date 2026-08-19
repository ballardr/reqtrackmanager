import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Project Overview's own "+ New Requirement" button deep-links to
 * `/requirements?new=1` rather than opening a form itself — before this
 * fix that deep link set `showNewForm` directly, which rendered
 * RequirementsPage's create form as an always-inline block above the list
 * (reflowing/hiding it), skipping the `SidePanel` layer the same form now
 * opens as when triggered from the Requirements page's own "+ New
 * requirement" → "Add one" popover. Both entry points now converge on the
 * same `SidePanel`, so this proves the deep-linked path stopped being the
 * odd one out.
 */
test.describe("Project Overview '+ New Requirement' opens the same side-panel form", () => {
  test("deep-linked create form is a layer, not a page reflow", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await page.getByRole("link", { name: new RegExp(PROJECT_NAMES.alpha1) }).click();
    await page.getByRole("link", { name: "Overview", exact: true }).click();

    await page.getByRole("link", { name: "New requirement" }).click();
    // `?new=1` is consumed and stripped by RequirementsPage.tsx almost as
    // soon as it lands, so waiting for that exact intermediate URL is a
    // race that can miss it entirely — waiting for the settled final URL
    // is enough to prove the deep link landed and was consumed.
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
    await expect(page.getByText(name)).toBeVisible();
  });
});
