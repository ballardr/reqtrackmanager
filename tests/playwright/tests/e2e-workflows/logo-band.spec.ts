import { expect, test } from "@playwright/test";

import { apiHeaders, loginAs, ORG_NAMES, PERSONAS, SERVER_ADMIN_LOGIN, selectServerManagementGroup } from "./helpers";

/**
 * Job to be done: a logo that is white on a transparent background is visible on the sign-in card, because the
 * logo sits on a band. The band follows the colour of the top bar until a platform or organisation colour is
 * chosen, and the organisation's colour wins on its own sign-in page.
 *
 * Mutates the platform band colour and the Alpha organisation's, and restores both through the API in `afterAll`.
 */

const apiBaseUrl = "http://localhost:8000";
const ORG_SLUG = "e2e-logo-band-org";

test.describe("logo band colour", () => {
  let alphaOrgId = "";
  let adminHeaders: Record<string, string> = {};
  let orgHeaders: Record<string, string> = {};

  test.beforeAll(async ({ request }) => {
    adminHeaders = await apiHeaders(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
    orgHeaders = await apiHeaders(request, PERSONAS.orgAdminAlphaBeta.email);
    const orgs = await (await request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: orgHeaders })).json();
    alphaOrgId = orgs.find((o: { name: string; id: string }) => o.name === ORG_NAMES.alpha).id;
    const slug = await request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/sso-config`, {
      headers: orgHeaders, data: { slug: ORG_SLUG, sso_enabled: false, sso_only: false },
    });
    expect(slug.ok()).toBeTruthy();
  });

  test.afterAll(async ({ request }) => {
    await request.put(`${apiBaseUrl}/api/v1/system/branding`, {
      headers: adminHeaders, data: { logo_band_color_hex: null, logo_band_text_color_hex: null },
    });
    await request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding`, {
      headers: orgHeaders, data: { logo_band_color_hex: null, logo_band_text_color_hex: null },
    });
  });

  test("the platform colour is chosen on Platform branding and removed to return to the top bar colour", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    await selectServerManagementGroup(page, "Platform branding");

    const save = page.getByRole("button", { name: "Save", exact: true });
    await page.getByLabel("Logo band colour (hex code)").fill("#0b5fa5");
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/system/branding") && r.request().method() === "PUT"),
      save.click(),
    ]);
    await expect(page.getByText("Platform branding saved.")).toBeVisible();

    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear());
    await page.goto("/login");
    const band = page.locator("form.card .logo-band");
    await expect(band).toHaveCSS("background-color", "rgb(11, 95, 165)");

    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    await selectServerManagementGroup(page, "Platform branding");
    await page.getByRole("button", { name: "Remove" }).first().click();
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/system/branding") && r.request().method() === "PUT"),
      page.getByRole("button", { name: "Save", exact: true }).click(),
    ]);
    const topBar = await page.locator("header.app-header").evaluate((el) => getComputedStyle(el).backgroundColor);

    await page.evaluate(() => localStorage.clear());
    await page.goto("/login");
    await expect(page.locator("form.card .logo-band")).toHaveCSS("background-color", topBar);
  });

  test("the organisation colour wins on its sign-in page while another page keeps the platform colour", async ({ page, request }) => {
    const platform = await request.put(`${apiBaseUrl}/api/v1/system/branding`, { headers: adminHeaders, data: { logo_band_color_hex: "#0b5fa5" } });
    expect(platform.ok()).toBeTruthy();
    const own = await request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding`, { headers: orgHeaders, data: { logo_band_color_hex: "#7a1f3d" } });
    expect(own.ok()).toBeTruthy();

    await page.goto(`/login/${ORG_SLUG}`);
    await expect(page.locator(".card .logo-band")).toHaveCSS("background-color", "rgb(122, 31, 61)");
    await page.goto("/login");
    await expect(page.locator("form.card .logo-band")).toHaveCSS("background-color", "rgb(11, 95, 165)");
  });

  test("the name sits on the band in black or white by contrast, or in the chosen colour", async ({ page, request }) => {
    await request.put(`${apiBaseUrl}/api/v1/system/branding`, {
      headers: adminHeaders, data: { logo_band_color_hex: "#ffffff", logo_band_text_color_hex: null },
    });
    await page.goto("/login");
    const title = page.locator("form.card .logo-band").getByRole("heading");
    await expect(title).toHaveCSS("color", "rgb(0, 0, 0)");
    await request.put(`${apiBaseUrl}/api/v1/system/branding`, { headers: adminHeaders, data: { logo_band_text_color_hex: "#0b5fa5" } });
    await page.goto("/login");
    await expect(title).toHaveCSS("color", "rgb(11, 95, 165)");
    await page.goto(`/login/${ORG_SLUG}`);
    await expect(page.locator(".card .logo-band").getByRole("heading")).toHaveCSS("color", "rgb(11, 95, 165)");
  });

  test("saving the other branding fields leaves the colour as it was", async ({ request }) => {
    const set = await request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding`, { headers: orgHeaders, data: { logo_band_color_hex: "#102030" } });
    expect(set.ok()).toBeTruthy();
    const other = await request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding`, { headers: orgHeaders, data: { header_title: "E2E Alpha" } });
    expect((await other.json()).logo_band_color_hex).toBe("#102030");
    await request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding`, { headers: orgHeaders, data: { header_title: null } });
  });
});
