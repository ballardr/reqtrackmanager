import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Two real gaps from a first-pass UX review of the 2026-08 audit's own
 * fixes:
 *
 * 1. Org Admin's resource-menu restructure (docs/decisions.md, "Org Admin
 *    -> resource-menu restructure") left the organisation's own name
 *    visible only on the Overview group's content — every other group
 *    (Users, Groups, Projects & workflow, Branding & defaults, ...) had no
 *    page title at all, so there was no way to tell which org you were
 *    editing once you'd navigated off Overview. Fixed by giving
 *    `ResourceMenu` a `title`/`subtitle` rendered once, above the
 *    menu+content grid, so it persists across every group.
 * 2. Project Admin's own `<h1>` was the generic "{Project} admin" label
 *    with no project name anywhere on the page — fixed the same way,
 *    showing the project's own name as the heading.
 *
 * A third, unrelated first-pass finding — no way to see the running
 * frontend/backend build version from the UI — is covered by the nav
 * rail's new version footer, asserted in its own test below.
 */

test("Org Admin shows the organisation's own name as the page title, persisting across every group", async ({
  page,
}) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.getByRole("link", { name: "My organisations" }).click();
  await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
  await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]+\/admin/);
  await expect(page.getByRole("heading", { level: 1, name: ORG_NAMES.alpha })).toBeVisible();

  await page.getByRole("link", { name: "Users" }).click();
  await expect(page.getByRole("heading", { level: 1, name: ORG_NAMES.alpha })).toBeVisible();

  await page.getByRole("link", { name: "Groups" }).click();
  await expect(page.getByRole("heading", { level: 1, name: ORG_NAMES.alpha })).toBeVisible();
});

test("Project Admin shows the project's own name as the page title", async ({ page }) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.getByText(PROJECT_NAMES.alpha1).click();
  await page.getByRole("link", { name: "Project admin", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: PROJECT_NAMES.alpha1 })).toBeVisible();
});

test("the nav rail shows the frontend and backend's own build versions", async ({ page }) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await expect(page.getByText(/^App v\S+$/)).toBeVisible();
  // The backend build identity is fetched async (GET /api/v1/system/version)
  // and defaults to "unknown"/"dev" placeholders in this dev/test stack
  // (no build ARGs supplied), rather than a real semantic version — the
  // point of this assertion is that it resolves and renders at all, not a
  // specific value.
  await expect(page.getByText(/^API v\S+$/)).toBeVisible();
});
