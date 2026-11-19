import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * Job to be done: Org Resources (`/orgs/:orgId/resources`) is the page of what the organisation owns and shares with
 * its projects. It is reached from the navigation rail (a person in several organisations picks one first), names the
 * organisation, offers the organisation switcher and a link to Organisation settings, and lists the sections of the
 * organisation's enabled modules. Module gating, the empty state and the redirect from an earlier Overview address are
 * covered with the module toggle in `org-overview.spec.ts`.
 *
 * Persona: `orgAdminAlphaBeta` (`org_admin` of Alpha and Beta, see backend/scripts/seed_e2e_dataset.py), a genuine
 * multi-org account. The spec only reads, so it needs no clean-up and can be repeated against the same database.
 */
test.describe("Org Resources page", () => {
  test("opens from the navigation rail, switches organisation and links to Organisation settings", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await page.getByRole("navigation").getByRole("link", { name: "Organisation resources" }).click();
    // Multi-org account: lands on the organisation picker first.
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/resources$/);
    await expect(page.getByRole("heading", { name: ORG_NAMES.alpha })).toBeVisible();
    await expect(page.getByRole("navigation").getByRole("link", { name: "Organisation resources" })).toHaveClass(/\bactive\b/);

    await page.getByRole("button", { name: "Switch organisation" }).click();
    const dialog = page.getByRole("dialog", { name: "Switch organisation" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("link", { name: ORG_NAMES.beta }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/resources$/);
    await expect(page.getByRole("heading", { name: ORG_NAMES.beta })).toBeVisible();

    await page.getByRole("main").getByRole("link", { name: "Organisation settings" }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin/);
  });

  test("an unknown section address returns to the page", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/org-resources");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    const base = page.url();
    await page.goto(`${base}/no-such-section`);
    await expect(page).toHaveURL(base);
  });
});
