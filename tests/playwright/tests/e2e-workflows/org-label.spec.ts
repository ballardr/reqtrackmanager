import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: a server admin can relabel the word "organisation"
 * deployment-wide (`ServerSettings.org_label_singular`/`org_label_plural`,
 * `GET/PUT /api/v1/system/branding`) to a custom term (e.g. "Tenant"), and
 * that term shows up in the app's primary chrome — nav, page titles, list
 * column headers — without needing per-organisation configuration.
 *
 * Global setting — mutates deployment-wide state, so it always restores the
 * original values in `afterAll`, the same pattern `self-signup.spec.ts` uses
 * for `ServerSettings.signup_mode`.
 */

const apiBaseUrl = "http://localhost:8000";

type BrandingSettings = {
  accent_color_hex: string;
  default_header_title: string | null;
  email_footer_company_name: string | null;
  email_footer_website: string | null;
  email_footer_address: string | null;
  org_label_singular: string | null;
  org_label_plural: string | null;
};

async function adminToken(page: import("@playwright/test").Page): Promise<string> {
  const resp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: "admin@example.com", password: "ChangeMe123!" },
  });
  return (await resp.json()).access_token;
}

async function getBranding(page: import("@playwright/test").Page, token: string): Promise<BrandingSettings> {
  const resp = await page.request.get(`${apiBaseUrl}/api/v1/system/branding`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return resp.json();
}

async function putBranding(
  page: import("@playwright/test").Page,
  token: string,
  settings: Pick<
    BrandingSettings,
    "accent_color_hex" | "default_header_title" | "email_footer_company_name" | "email_footer_website" | "email_footer_address" | "org_label_singular" | "org_label_plural"
  >,
) {
  const resp = await page.request.put(`${apiBaseUrl}/api/v1/system/branding`, {
    headers: { Authorization: `Bearer ${token}` },
    data: settings,
  });
  expect(resp.ok()).toBeTruthy();
}

test.describe("deployment-wide organisation label override", () => {
  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    const token = await adminToken(page);
    const current = await getBranding(page, token);
    await putBranding(page, token, { ...current, org_label_singular: null, org_label_plural: null });
    await page.close();
  });

  test("setting a custom label swaps the word in nav and page chrome", async ({ page }) => {
    const token = await adminToken(page);
    const original = await getBranding(page, token);

    await test.step("set a custom label via the platform branding admin form", async () => {
      await loginAs(page, PERSONAS.serverAdmin.email);
      await page.goto("/server/management");
      await page.getByRole("tab", { name: "Platform branding" }).click();
      await page.getByLabel(/^Organisation label \(singular\)/).fill("tenant");
      await page.getByLabel(/^Organisation label \(plural\)/).fill("Tenants");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/system/branding") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save platform branding" }).click(),
      ]);
      await expect(page.getByText("Saved.")).toBeVisible();
    });

    await test.step("the nav rail now reads the custom label", async () => {
      await page.reload();
      // exact: true — the nav rail's own "My {org label}" link (linking to
      // the personal org directory, /orgs) now also contains "Tenants" as
      // a substring ("My tenants"), so a non-exact match would resolve to
      // both it and this server-admin-only "Tenants" directory link.
      await expect(page.getByRole("link", { name: "Tenants", exact: true })).toBeVisible();
    });

    await test.step("the server organisations page title and list use the custom label", async () => {
      await page.getByRole("link", { name: "Tenants", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Tenants" })).toBeVisible();
      await expect(page.getByPlaceholder("Search tenants")).toBeVisible();
    });

    await test.step("restoring the default (blank) label reverts the nav to \"Organisations\"", async () => {
      await page.goto("/server/management");
      await page.getByRole("tab", { name: "Platform branding" }).click();
      await page.getByLabel(/^Organisation label \(singular\)/).fill("");
      await page.getByLabel(/^Organisation label \(plural\)/).fill("");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/system/branding") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save platform branding" }).click(),
      ]);
      await page.reload();
      await expect(page.getByRole("link", { name: "Organisations", exact: true })).toBeVisible();
    });

    // Belt-and-braces: also restore via API in case the UI step above ever
    // regresses, so this test never leaves the deployment-wide label
    // mutated for later specs in the same run even on partial failure.
    await putBranding(page, token, { ...original, org_label_singular: null, org_label_plural: null });
  });
});
