import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, ORG_NAMES, PERSONAS } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Style guide "Pattern: platform default vs. override" (2026-08 UX audit):
 * every overridable branding field now shows its current source as a pill
 * ("Platform default"/"Custom") and, when custom, an explicit "Reset to
 * platform default" action — previously the only way back was to know to
 * blank the field by hand. The seeded Alpha org already has its email
 * footer fields overridden (`seed_e2e_dataset.py`) and its header title on
 * the platform default, which conveniently exercises both pill states
 * without extra setup.
 *
 * Mutates real org branding, so it restores the seeded values afterward
 * (`afterEach`, runs even if an assertion above it fails) rather than
 * leaving this shared org's data changed for later spec runs.
 */
test.describe("org branding: platform-default/override pill and reset", () => {
  const original = {
    email_footer_company_name: "E2E Alpha Robotics",
    email_footer_website: "https://alpha-robotics.example.com",
    email_footer_address: "1 Test Fixture Way\nAlpha City, AC 00001",
  };
  let alphaOrgId = "";
  let authHeaders: Record<string, string> = {};

  test.afterEach(async ({ page }) => {
    if (!alphaOrgId) return;
    await page.request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding`, {
      headers: authHeaders,
      data: { accent_color_hex: null, header_title: null, ...original },
    });
  });

  test("Custom fields show a reset action; resetting reverts to Platform default", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: authHeaders })).json();
    alphaOrgId = orgs.find((o: { name: string; id: string }) => o.name === ORG_NAMES.alpha).id;

    await page.goto(`/orgs/${alphaOrgId}/admin`);
    await ensureExpanded(page, "Branding");

    await test.step("header title is on the platform default; company name is overridden", async () => {
      await expect(page.getByLabel(/^Header title/)).toHaveValue("");
      const headerRow = page.locator("span").filter({ hasText: "Header title" }).first();
      await expect(headerRow.getByText("Platform default")).toBeVisible();
      await expect(headerRow.getByRole("button", { name: "Reset to platform default" })).toHaveCount(0);

      const companyRow = page.locator("span").filter({ hasText: "Company name" }).first();
      await expect(companyRow.getByText("Custom")).toBeVisible();
      await expect(page.getByLabel("Company name")).toHaveValue(original.email_footer_company_name);
    });

    await test.step("resetting the company name clears it locally, then Save reverts it server-side", async () => {
      const companyRow = page.locator("span").filter({ hasText: "Company name" }).first();
      await companyRow.getByRole("button", { name: "Reset to platform default" }).click();
      await expect(page.getByLabel("Company name")).toHaveValue("");

      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/branding") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save branding" }).click(),
      ]);
      await page.reload();
      await ensureExpanded(page, "Branding");
      const companyRowAfter = page.locator("span").filter({ hasText: "Company name" }).first();
      await expect(companyRowAfter.getByText("Platform default")).toBeVisible();
      await expect(page.getByLabel("Company name")).toHaveValue("");
    });
  });
});
