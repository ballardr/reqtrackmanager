import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "../../e2e-workflows/helpers";
import { createStandardWithVersion, openComplianceStatusTab } from "./helpers";

/**
 * Job to be done: the organisation-wide compliance views (By standard, Outstanding) have one home, the Standards
 * page, beside the standards list, and Org Resources has no Compliance section.
 *
 * `orgAdminAlphaBeta` administers two organisations, so the Organisation filter is present, and is an organisation
 * administrator, so the status tabs are offered.
 */
test.describe("Compliance Module: status tabs of the Standards page", () => {
  test("the Standards page offers three tabs, each an address of its own, and the nav link stays active", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/standards");
    await expect(page.getByRole("tab", { name: "Standards", exact: true })).toHaveAttribute("aria-selected", "true");

    await page.getByRole("tab", { name: "By standard", exact: true }).click();
    // The list has no organisation chosen, so the tab reads every organisation the person may read.
    await expect(page).toHaveURL(/\/standards\/by-standard$/);
    await expect(page.getByRole("tab", { name: "By standard", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("navigation").getByRole("link", { name: "Compliance Standards" })).toHaveClass(/\bactive\b/);

    await page.getByRole("tab", { name: "Outstanding", exact: true }).click();
    await expect(page).toHaveURL(/\/standards\/outstanding$/);

    await page.getByRole("tab", { name: "Standards", exact: true }).click();
    await expect(page).toHaveURL(/\/standards$/);
  });

  test("the Organisation filter chooses the organisation and is kept in the address", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openComplianceStatusTab(page, "Outstanding", ORG_NAMES.beta);
    await expect(page).toHaveURL(/\/standards\/outstanding\?org=[^&]+/);
    const betaUrl = page.url();
    await expect(page.getByRole("combobox", { name: "Organisation", exact: true })).toHaveValue(new URL(betaUrl).searchParams.get("org")!);

    // Switching tab keeps the organisation.
    await page.getByRole("tab", { name: "By standard", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/standards/by-standard\\?org=${new URL(betaUrl).searchParams.get("org")}`));
  });

  test("the status tabs read every organisation until the filter chooses one", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/standards/by-standard");
    const organisation = page.getByRole("combobox", { name: "Organisation", exact: true });
    await expect(organisation).toHaveValue("");
    await expect(organisation.locator("option").first()).toHaveText("All organisations");
    await expect(organisation.locator("option")).toContainText(["All organisations", ORG_NAMES.alpha, ORG_NAMES.beta]);
    // A report is made for one organisation, so Export appears once the filter chooses one.
    await expect(page.getByRole("button", { name: "Export", exact: true })).toHaveCount(0);
    await organisation.selectOption({ label: ORG_NAMES.alpha });
    await expect(page.getByRole("button", { name: "Export", exact: true })).toBeVisible();
    await organisation.selectOption({ label: "All organisations" });
    await expect(page).toHaveURL(/\/standards\/by-standard$/);
    await expect(page.getByRole("button", { name: "Export", exact: true })).toHaveCount(0);
  });

  test("By standard has one Organisation column for several organisations, none for one", async ({ page }) => {
    const suffix = Date.now();
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference: `OCA-${suffix}`, name: `E2E Org Column Alpha ${suffix}` });

    await page.goto("/standards/by-standard");
    // Several organisations are read: an Organisation column of its own, and its header is left of the figures.
    await expect(page.getByRole("columnheader", { name: "Organisation", exact: true })).toHaveCount(1);

    // One organisation chosen: the column is absent.
    await page.getByRole("combobox", { name: "Organisation", exact: true }).selectOption({ label: ORG_NAMES.alpha });
    await expect(page.getByRole("columnheader", { name: "Standard", exact: true })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Organisation", exact: true })).toHaveCount(0);
    await page.getByRole("combobox", { name: "Organisation", exact: true }).selectOption({ label: "All organisations" });
  });

  test("the Standards list has an Organisation filter, every organisation by default, and names each standard's organisation", async ({ page }) => {
    const suffix = Date.now();
    const alphaName = `E2E Org Filter Alpha ${suffix}`;
    const betaName = `E2E Org Filter Beta ${suffix}`;
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference: `OFA-${suffix}`, name: alphaName });
    await createStandardWithVersion(page, { orgName: ORG_NAMES.beta, reference: `OFB-${suffix}`, name: betaName });

    await page.goto("/standards");
    await page.getByRole("textbox", { name: "Search standards" }).fill(String(suffix));
    const alphaCard = page.locator(".tile-card", { hasText: alphaName });
    const betaCard = page.locator(".tile-card", { hasText: betaName });
    await expect(alphaCard).toBeVisible();
    await expect(betaCard).toBeVisible();
    // Each standard states its organisation.
    await expect(alphaCard).toContainText(ORG_NAMES.alpha);
    await expect(betaCard).toContainText(ORG_NAMES.beta);

    // The filter is in the filter panel, shows every organisation and narrows the list, kept in the address.
    const organisation = page.locator(".filter-panel").getByRole("combobox", { name: "Organisation", exact: true });
    await expect(organisation).toHaveValue("");
    await organisation.selectOption({ label: ORG_NAMES.beta });
    await expect(page).toHaveURL(/[?&]org=/);
    await expect(betaCard).toBeVisible();
    await expect(alphaCard).toHaveCount(0);
  });

  test("Org Resources no longer lists a Compliance section", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/org-resources");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page.locator(".resource-menu-nav").getByRole("link", { name: "Reports", exact: true })).toBeVisible();
    await expect(page.locator(".resource-menu-nav").getByRole("link", { name: /^Compliance by standard$|^Outstanding compliance items$/ })).toHaveCount(0);
  });

  test("Export stays in the same place on both status tabs", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    const positions: { left: number; top: number }[] = [];
    for (const tab of ["By standard", "Outstanding"] as const) {
      await openComplianceStatusTab(page, tab, ORG_NAMES.alpha);
      const exportButton = page.getByRole("button", { name: "Export", exact: true });
      await expect(exportButton).toBeVisible();
      const title = await page.getByRole("heading", { name: "Compliance Standards" }).boundingBox();
      const exported = await exportButton.boundingBox();
      expect(title && exported).toBeTruthy();
      // In the title row, to the right of the title.
      expect(Math.abs(exported!.y + exported!.height / 2 - (title!.y + title!.height / 2))).toBeLessThan(16);
      expect(exported!.x).toBeGreaterThan(title!.x);
      positions.push({ left: Math.round(exported!.x), top: Math.round(exported!.y) });
    }
    expect(positions[1].top).toBe(positions[0].top);
    expect(Math.abs(positions[1].left - positions[0].left)).toBeLessThan(2);
  });
});
