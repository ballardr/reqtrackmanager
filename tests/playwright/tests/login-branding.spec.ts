import { expect, test } from "@playwright/test";

import { ORG_NAMES, PERSONAS, loginAs } from "./e2e-workflows/helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * The platform login page (no org slug) renders `LoginBrandHeader`, as `OrgLoginPage` does: the title is
 * visible above the "Sign in" heading on the plain /login page.
 */
test("login page shows branding title above the sign-in form", async ({ page }) => {
  await page.goto("/login");
  const card = page.locator("form.card");
  await expect(card.getByText("ReqTrackManager")).toBeVisible();
  await expect(card.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

/**
 * `LoginBrandHeader` falls back to the bundled `builtInLogo` asset when `logoFileId` is null (no platform
 * logo uploaded), as `Layout.tsx`'s authenticated header does: the `<img>` exists and resolves to a bundled
 * asset path, not a broken or empty `src`.
 */
test("platform-default login page renders a logo image even with no custom branding configured", async ({ page }) => {
  await page.goto("/login");
  const card = page.locator("form.card");
  const logo = card.locator("img");
  await expect(logo).toBeVisible();
  const src = await logo.getAttribute("src");
  expect(src).toBeTruthy();
  // Not a fileUrl(...) API path — this is the platform-default (no org
  // logo, no platform logo uploaded) case, so it must be the bundled asset.
  expect(src).not.toMatch(/\/api\//);
});

/**
 * An org that has uploaded its own logo shows it on its branded `/login/:slug` page, not the built-in
 * fallback. Mutates the shared Alpha org's slug and logo. The slug write is a one-way ratchet
 * (`update_sso_config` in backend/app/routers/orgs.py only sets a slug, never clears it), so it is left in
 * place, as `org-login-2fa-handoff.spec.ts` does; the logo upload is removed in `afterEach` so it does not
 * leak into `org-branding-override-reset.spec.ts`'s assertions on Alpha's branding defaults.
 */
test.describe("org-branded login page: custom logo regression", () => {
  const ORG_SLUG = "e2e-login-brand-org";
  let alphaOrgId = "";
  let authHeaders: Record<string, string> = {};

  test.afterEach(async ({ page }) => {
    if (!alphaOrgId) return;
    await page.request.delete(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding-image?kind=logo`, {
      headers: authHeaders,
    });
  });

  test("org-branded login page still renders the org's own custom logo when one is set", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: authHeaders })).json();
    alphaOrgId = orgs.find((o: { name: string; id: string }) => o.name === ORG_NAMES.alpha).id;

    const slugResp = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/sso-config`, {
      headers: authHeaders,
      data: { slug: ORG_SLUG, sso_enabled: false, sso_only: false },
    });
    expect(slugResp.ok()).toBe(true);

    // A real (if tiny) PNG, not arbitrary bytes: the test asserts the `<img>` renders visibly with the org's
    // logo, so the browser must decode the file.
    const onePixelPng = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      "base64",
    );
    const logoResp = await page.request.post(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding-image`, {
      headers: authHeaders,
      multipart: { file: { name: "logo.png", mimeType: "image/png", buffer: onePixelPng }, kind: "logo" },
    });
    expect(logoResp.ok()).toBe(true);
    const { logo_file_id: logoFileId } = await logoResp.json();
    expect(logoFileId).toBeTruthy();

    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/login$/);

    await page.goto(`/login/${ORG_SLUG}`);
    await expect(page.getByRole("heading", { name: ORG_NAMES.alpha })).toBeVisible();
    const logo = page.locator("form.card, .card").locator("img").first();
    await expect(logo).toBeVisible();
    const src = await logo.getAttribute("src");
    expect(src).toContain(`/api/v1/files/${logoFileId}`);
  });
});

/**
 * The static default SVG favicon (`<link rel="icon">` in index.html, file under frontend/public/) is
 * served, not just referenced.
 */
test("favicon.svg is served", async ({ page }) => {
  const response = await page.request.get("/favicon.svg");
  expect(response.ok()).toBe(true);
  expect(response.headers()["content-type"]).toContain("svg");
});
