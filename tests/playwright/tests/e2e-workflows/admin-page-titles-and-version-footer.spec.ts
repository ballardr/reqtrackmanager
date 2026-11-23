import { expect, test } from "@playwright/test";

import { loginAs, openProject, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Pins the admin page titles and the version footer:
 *
 * 1. Org Admin shows the organisation's name as the page title in every group (Users, Groups, Projects & workflow,
 *    Branding & defaults, ...), through the `title`/`subtitle` that `ResourceMenu` renders once above the
 *    menu and content grid (docs/decisions.md, "Org Admin -> resource-menu restructure").
 * 2. Project Admin's `<h1>` shows the project's own name.
 *
 * The nav rail's version footer shows the running frontend and backend build version, asserted in its own test.
 */

test("Org Admin shows the organisation's own name as the page title, persisting across every group", async ({
  page,
}) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.getByRole("link", { name: "Organisation settings" }).click();
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
  await openProject(page, PROJECT_NAMES.alpha1);
  await page.getByRole("link", { name: "Project admin", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: PROJECT_NAMES.alpha1 })).toBeVisible();
});

test("the page footer shows the frontend and backend's own build versions", async ({ page }) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  // The backend build identity is fetched async (GET /api/v1/system/version)
  // and defaults to "unknown"/"dev" placeholders in this dev/test stack
  // (no build ARGs supplied), rather than a real semantic version — the
  // point of this assertion is that it resolves and renders at all, not a
  // specific value.
  await expect(page.getByText(/^Version: v\S+\/v\S+$/)).toBeVisible();
});
