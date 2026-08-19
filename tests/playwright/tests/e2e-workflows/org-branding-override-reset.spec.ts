import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, ORG_NAMES, PERSONAS, selectOrgAdminGroup } from "./helpers";

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
    // No-op when nothing's set (idempotent, see backend/tests/test_files.py),
    // so this is safe to run unconditionally rather than only when the logo
    // test below actually ran.
    await page.request.delete(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/logo`, { headers: authHeaders });
    await page.request.delete(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/login-background`, { headers: authHeaders });
  });

  test("Custom fields show a reset action; resetting reverts to Platform default", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: authHeaders })).json();
    alphaOrgId = orgs.find((o: { name: string; id: string }) => o.name === ORG_NAMES.alpha).id;

    await page.goto(`/orgs/${alphaOrgId}/admin`);
    // Branding moved into the "Branding & defaults" resource-menu group
    // (2026-08 UX audit's Org Admin restructure) — a real navigation, so
    // it must be selected before the section is reachable at all.
    await selectOrgAdminGroup(page, "Branding & defaults");
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
      // `page.reload()` preserves the current URL, so the "Branding &
      // defaults" group segment (already navigated to above) is still
      // active after the reload — this is a harmless no-op guard, not a
      // fresh navigation.
      await selectOrgAdminGroup(page, "Branding & defaults");
      await ensureExpanded(page, "Branding");
      const companyRowAfter = page.locator("span").filter({ hasText: "Company name" }).first();
      await expect(companyRowAfter.getByText("Platform default")).toBeVisible();
      await expect(page.getByLabel("Company name")).toHaveValue("");
    });
  });

  test("Logo and login-background reset immediately via the new DELETE endpoints, with no separate Save step", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: authHeaders })).json();
    alphaOrgId = orgs.find((o: { name: string; id: string }) => o.name === ORG_NAMES.alpha).id;

    await page.goto(`/orgs/${alphaOrgId}/admin`);
    await selectOrgAdminGroup(page, "Branding & defaults");
    await ensureExpanded(page, "Branding");

    await test.step("uploading a logo shows Custom + a reset action, no Platform default pill anymore", async () => {
      const logoRow = page.locator('label[for="org-logo-input"]').locator("..");
      await expect(logoRow.getByText("Platform default")).toBeVisible();
      await page.locator("#org-logo-input").setInputFiles({
        name: "logo.png", mimeType: "image/png", buffer: Buffer.from("fake-png-bytes"),
      });
      await expect(page.getByText("Logo uploaded.")).toBeVisible();
      await expect(logoRow.getByText("Custom")).toBeVisible();
      await expect(logoRow.getByRole("button", { name: "Reset to platform default" })).toBeVisible();
    });

    await test.step("resetting the logo reverts it immediately — no Save button involved", async () => {
      const logoRow = page.locator('label[for="org-logo-input"]').locator("..");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/logo") && r.request().method() === "DELETE"),
        logoRow.getByRole("button", { name: "Reset to platform default" }).click(),
      ]);
      await expect(page.getByText("Logo reset to the platform default.")).toBeVisible();
      await expect(logoRow.getByText("Platform default")).toBeVisible();
      await expect(logoRow.getByRole("button", { name: "Reset to platform default" })).toHaveCount(0);
    });

    await test.step("login-background image (now part of the same Branding card as the logo, moved out of Single sign-on) has the same reset behaviour", async () => {
      // No section/group change needed here — login-background moved into
      // the Branding card itself (2026-08 UX audit's Org Admin restructure:
      // it's a branding concern, not an SSO/OIDC one), which is already
      // open in the "Branding & defaults" group from the steps above.
      const backgroundRow = page.locator('label[for="org-login-background-input"]').locator("..");
      await expect(backgroundRow.getByText("Platform default")).toBeVisible();

      await page.locator("#org-login-background-input").setInputFiles({
        name: "bg.png", mimeType: "image/png", buffer: Buffer.from("fake-png-bytes"),
      });
      await expect(page.getByText("Background image uploaded.")).toBeVisible();
      await expect(backgroundRow.getByText("Custom")).toBeVisible();

      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/login-background") && r.request().method() === "DELETE"),
        backgroundRow.getByRole("button", { name: "Reset to platform default" }).click(),
      ]);
      await expect(page.getByText("Background image reset to the platform default.")).toBeVisible();
      await expect(backgroundRow.getByText("Platform default")).toBeVisible();
    });
  });
});
