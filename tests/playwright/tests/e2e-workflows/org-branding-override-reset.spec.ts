import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, ORG_NAMES, PERSONAS, selectOrgAdminGroup } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Style guide "Pattern: platform default vs. override": an organisation's company settings carry no "Custom" pill
 * and no reset link. An empty text field uses the platform value, which the field shows as its placeholder; the
 * logo and login background cannot be emptied, so each has a Remove button while the organisation has its own file.
 * The seeded Alpha org has its email footer fields set (`seed_e2e_dataset.py`) and its header title empty. The header
 * title is on Branding & defaults; the company details and the logo are on Organisation details.
 *
 * Mutates real org branding, so it restores the seeded values afterward
 * (`afterEach`, runs even if an assertion above it fails) rather than
 * leaving this shared org's data changed for later spec runs.
 */
test.describe("org branding: the platform value is the placeholder; files have a Remove button", () => {
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
    await page.request.delete(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding-image?kind=logo`, { headers: authHeaders });
    await page.request.delete(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding-image?kind=login_background`, {
      headers: authHeaders,
    });
  });

  test("an empty field shows the platform value as its placeholder; emptying a field reverts it", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: authHeaders })).json();
    alphaOrgId = orgs.find((o: { name: string; id: string }) => o.name === ORG_NAMES.alpha).id;
    const platform = await (await page.request.get(`${apiBaseUrl}/api/v1/system/branding`)).json();

    await page.goto(`/orgs/${alphaOrgId}/admin`);
    await selectOrgAdminGroup(page, "Branding & defaults");
    await ensureExpanded(page, "Branding");

    await test.step("no pill and no reset link; the header title is empty with the platform title as placeholder", async () => {
      await expect(page.getByText("Custom", { exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Reset to platform default" })).toHaveCount(0);
      await expect(page.getByLabel(/^Header title/)).toHaveValue("");
      await expect(page.getByLabel(/^Header title/)).toHaveAttribute("placeholder", platform.default_header_title || "ReqTrackManager");
      await expect(page.getByLabel("Company name")).toHaveCount(0);
    });

    await selectOrgAdminGroup(page, "Organisation details");
    await expect(page.getByLabel("Company name")).toHaveValue(original.email_footer_company_name);

    await test.step("emptying the company name and saving reverts it to the platform value", async () => {
      await page.getByLabel("Company name").fill("");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/branding") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save", exact: true }).click(),
      ]);
      await page.reload();
      await selectOrgAdminGroup(page, "Organisation details");
      await expect(page.getByLabel("Company name")).toHaveValue("");
      if (platform.email_footer_company_name) {
        await expect(page.getByLabel("Company name")).toHaveAttribute("placeholder", platform.email_footer_company_name);
      }
    });
  });

  test("Logo and login-background are removed immediately via the DELETE endpoints, with no separate Save step", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: authHeaders })).json();
    alphaOrgId = orgs.find((o: { name: string; id: string }) => o.name === ORG_NAMES.alpha).id;

    await page.goto(`/orgs/${alphaOrgId}/admin`);
    await selectOrgAdminGroup(page, "Organisation details");

    await test.step("uploading a logo shows a Remove button and no pill", async () => {
      const logoRow = page.locator('label[for="org-logo-input"]').locator("../..");
      await expect(logoRow.getByRole("button", { name: "Remove" })).toHaveCount(0);
      await page.locator("#org-logo-input").setInputFiles({
        name: "logo.png", mimeType: "image/png", buffer: Buffer.from("fake-png-bytes"),
      });
      await expect(page.getByText("Logo uploaded.")).toBeVisible();
      await expect(logoRow.getByRole("button", { name: "Remove" })).toBeVisible();
      await expect(logoRow.getByText("Custom", { exact: true })).toHaveCount(0);
    });

    await test.step("removing the logo takes effect immediately — no Save button involved", async () => {
      const logoRow = page.locator('label[for="org-logo-input"]').locator("../..");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("kind=logo") && r.request().method() === "DELETE"),
        logoRow.getByRole("button", { name: "Remove" }).click(),
      ]);
      await expect(page.getByText("Logo removed.")).toBeVisible();
      await expect(logoRow.getByRole("button", { name: "Remove" })).toHaveCount(0);
    });

    await test.step("the login background, on Branding & defaults, has the same behaviour", async () => {
      await selectOrgAdminGroup(page, "Branding & defaults");
      await ensureExpanded(page, "Branding");
      const backgroundRow = page.locator('label[for="org-login-background-input"]').locator("../..");
      await page.locator("#org-login-background-input").setInputFiles({
        name: "bg.png", mimeType: "image/png", buffer: Buffer.from("fake-png-bytes"),
      });
      await expect(page.getByText("Background image uploaded.")).toBeVisible();
      await expect(backgroundRow.getByRole("button", { name: "Remove" })).toBeVisible();

      await Promise.all([
        page.waitForResponse((r) => r.url().includes("kind=login_background") && r.request().method() === "DELETE"),
        backgroundRow.getByRole("button", { name: "Remove" }).click(),
      ]);
      await expect(page.getByText("Background image removed.")).toBeVisible();
      await expect(backgroundRow.getByRole("button", { name: "Remove" })).toHaveCount(0);
    });
  });
});
