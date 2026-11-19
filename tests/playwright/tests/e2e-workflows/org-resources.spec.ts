import { expect, test } from "@playwright/test";

import { installCleanupHook, loginAs, ORG_NAMES, PERSONAS, selectOrgAdminGroup, selectOrgResourcesGroup } from "./helpers";
import { setUpOrg } from "../modules/stakeholders/helpers";

/**
 * Job to be done: Org Resources (`/orgs/:orgId/resources`) is the page of what the organisation owns and shares with
 * its projects. It is reached from the navigation rail (a person in several organisations picks one first), names the
 * organisation, offers the organisation switcher and a link to Organisation settings, and lists the sections of the
 * organisation's enabled modules, followed by Reports and Tags. Module gating and the redirect from an earlier Overview
 * address are covered with the module toggle in `org-overview.spec.ts`; the earlier Organisation settings addresses of
 * what moved here redirect, and Settings no longer lists Reports or Tags.
 *
 * Persona: `orgAdminAlphaBeta` (`org_admin` of Alpha and Beta, see backend/scripts/seed_e2e_dataset.py), a genuine
 * multi-org account. The spec only reads, so it needs no clean-up and can be repeated against the same database.
 */
// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

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

  test("offers Reports and Tags, and Settings no longer lists them", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/org-resources");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    const orgPath = new URL(page.url()).pathname.replace(/\/resources.*$/, "");

    await selectOrgResourcesGroup(page, "Reports");
    await expect(page).toHaveURL(/\/resources\/reports$/);
    await expect(page.getByRole("button", { name: "Report layouts section" })).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("button", { name: "Configuration section" })).toBeVisible();

    await selectOrgResourcesGroup(page, "Tags");
    await expect(page).toHaveURL(/\/resources\/tags$/);
    await expect(page.getByText("Tags for records the organisation owns")).toBeVisible();

    await page.goto(`${orgPath}/admin`);
    await expect(page.getByRole("heading", { name: ORG_NAMES.alpha })).toBeVisible();
    const menu = page.locator("nav.resource-menu-nav");
    await expect(menu.getByRole("link", { name: "Users" })).toBeVisible();
    await expect(menu.getByRole("link", { name: "Reports" })).toHaveCount(0);
    await expect(menu.getByRole("link", { name: "Tags" })).toHaveCount(0);
  });

  test("the earlier Organisation settings addresses redirect here, keeping the query string", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/org-resources");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    const orgPath = new URL(page.url()).pathname.replace(/\/resources.*$/, "");

    await page.goto(`${orgPath}/admin/reports?from=bookmark`);
    await expect(page).toHaveURL(new RegExp(`${orgPath}/resources/reports\\?from=bookmark$`));
    await expect(page.getByRole("button", { name: "Report layouts section" })).toBeVisible();

    await page.goto(`${orgPath}/admin/tags`);
    await expect(page).toHaveURL(new RegExp(`${orgPath}/resources/tags$`));

    // The older Templates & reports address still reaches Reports, now on this page.
    await page.goto(`${orgPath}/admin/templates-reports`);
    await expect(page).toHaveURL(new RegExp(`${orgPath}/resources/reports$`));
  });

  test("a module's organisation record list moved from Settings: the earlier address redirects and Settings drops the entry", async ({ page }) => {
    const { org } = await setUpOrg(page, "ArchMoved", false, "System Architecture");

    await page.goto(`/orgs/${org.id}/admin/architecture/architecture-elements`);
    await expect(page).toHaveURL(new RegExp(`/orgs/${org.id}/resources/architecture-elements$`));
    await expect(page.getByRole("button", { name: "New element" })).toBeVisible();

    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Element Types", "System Architecture");
    await expect(page.locator("nav.resource-menu-nav").getByRole("link", { name: "Elements and Collections" })).toHaveCount(0);
  });
});
