import { expect, test, type Page } from "@playwright/test";

import { apiHeaders, loginAs, ORG_NAMES, PERSONAS, SERVER_ADMIN_LOGIN, selectServerManagementGroup } from "./helpers";

/**
 * Job to be done: the platform administrator chooses whether the footer of the signed-out pages sits below the sign-in
 * card or at the bottom of the window, an organisation may choose its own position for its sign-in page, and at any
 * width no line of the footer begins or ends with a separator.
 *
 * Mutates the platform footer position and details and the Alpha organisation's position, and restores them through
 * the API in `afterAll`.
 */

const apiBaseUrl = "http://localhost:8000";
const ORG_SLUG = "e2e-footer-org";

/** The distance in pixels from the footer's bottom edge to the bottom of the page shell. */
async function footerGapToPageBottom(page: Page): Promise<number> {
  return page.evaluate(() => {
    const footer = document.querySelector("footer.app-footer")!.getBoundingClientRect();
    const shell = document.querySelector(".signed-out-page")!.getBoundingClientRect();
    return Math.abs(shell.bottom - footer.bottom);
  });
}

/** Per footer group: its line (vertical offset) and whether it draws a separator before it. */
async function footerGroups(page: Page): Promise<{ top: number; separator: boolean }[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLElement>("footer.app-footer .app-footer-group"), (group) => ({
      top: group.offsetTop,
      separator: getComputedStyle(group, "::before").content.includes("|"),
    })),
  );
}

test.describe("footer position", () => {
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
      headers: adminHeaders,
      data: { footer_position: "after_content", footer_prefix: null, company_id_label: null, company_id: null, email_footer_address: null },
    });
    await request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding`, { headers: orgHeaders, data: { footer_position: null } });
  });

  test("the position is chosen on Server details and applies to the sign-in page", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    await selectServerManagementGroup(page, "Server details");
    await page.getByLabel("Footer position").selectOption("bottom_of_page");
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/system/branding") && r.request().method() === "PUT"),
      page.getByRole("button", { name: "Save", exact: true }).click(),
    ]);
    await expect(page.getByText("Server details saved.")).toBeVisible();

    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear());
    await page.goto("/login");
    await expect(page.locator("footer.app-footer")).toBeVisible();
    await expect.poll(() => footerGapToPageBottom(page)).toBeLessThanOrEqual(1);
    const card = await page.locator("form.card").boundingBox();
    const footer = await page.locator("footer.app-footer").boundingBox();
    expect(footer!.y - (card!.y + card!.height)).toBeGreaterThan(80);

    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    await selectServerManagementGroup(page, "Server details");
    await page.getByLabel("Footer position").selectOption("after_content");
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/system/branding") && r.request().method() === "PUT"),
      page.getByRole("button", { name: "Save", exact: true }).click(),
    ]);
    await page.evaluate(() => localStorage.clear());
    await page.context().clearCookies();
    await page.goto("/login");
    const after = await page.locator("footer.app-footer").boundingBox();
    const cardAfter = await page.locator("form.card").boundingBox();
    expect(after!.y - (cardAfter!.y + cardAfter!.height)).toBeLessThan(80);
  });

  test("an organisation's own position wins on its sign-in page while another page keeps the platform's", async ({ page, request }) => {
    expect((await request.put(`${apiBaseUrl}/api/v1/system/branding`, { headers: adminHeaders, data: { footer_position: "after_content" } })).ok()).toBeTruthy();
    expect((await request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding`, { headers: orgHeaders, data: { footer_position: "bottom_of_page" } })).ok()).toBeTruthy();

    await page.goto(`/login/${ORG_SLUG}`);
    await expect(page.locator("footer.app-footer")).toBeVisible();
    await expect.poll(() => footerGapToPageBottom(page)).toBeLessThanOrEqual(1);
    await page.goto("/login");
    await expect(page.locator("footer.app-footer")).toBeVisible();
    const shell = await page.locator(".signed-out-page").boundingBox();
    const footer = await page.locator("footer.app-footer").boundingBox();
    expect(shell!.y + shell!.height - (footer!.y + footer!.height)).toBeGreaterThan(80);
  });

  test("the organisation chooses its position on Branding & defaults and can return to the platform setting", async ({ page, request }) => {
    await request.put(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/branding`, { headers: orgHeaders, data: { footer_position: null } });
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/orgs/${alphaOrgId}/admin`);
    await page.getByRole("link", { name: "Branding & defaults" }).click();
    const select = page.getByLabel("Footer position");
    await expect(select).toHaveValue("");
    await select.selectOption("bottom_of_page");
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/branding") && r.request().method() === "PUT"),
      page.getByRole("button", { name: "Save branding" }).click(),
    ]);
    const saved = await (await request.get(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}`, { headers: orgHeaders })).json();
    expect(saved.footer_position).toBe("bottom_of_page");
    await select.selectOption("");
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/branding") && r.request().method() === "PUT"),
      page.getByRole("button", { name: "Save branding" }).click(),
    ]);
    const cleared = await (await request.get(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}`, { headers: orgHeaders })).json();
    expect(cleared.footer_position).toBeNull();
  });

  test("no line of a wrapped footer begins or ends with a separator at any width", async ({ page, request }) => {
    const set = await request.put(`${apiBaseUrl}/api/v1/system/branding`, {
      headers: adminHeaders,
      data: {
        footer_prefix: "Hosted by", company_id_label: "ABN", company_id: "12 345 678 901",
        email_footer_address: "Level 12, 100 Collins Street\nMelbourne VIC 3000",
      },
    });
    expect(set.ok()).toBeTruthy();
    for (const width of [1280, 700, 480, 360, 320]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/login");
      await expect(page.locator("footer.app-footer .app-footer-group").first()).toBeVisible();
      await expect.poll(async () => (await footerGroups(page)).length).toBeGreaterThanOrEqual(3);
      await expect.poll(async () => {
        const groups = await footerGroups(page);
        return groups.every((group, index) => group.separator === (index > 0 && group.top === groups[index - 1].top));
      }, { message: `separators at width ${width}` }).toBe(true);
    }
  });
});
